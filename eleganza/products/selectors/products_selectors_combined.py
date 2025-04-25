
#========================================
# eleganza/products/selectors/category_selectors.py
#========================================

from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional, Iterable
from collections import defaultdict
from django.db.models import Value, F
from django.db.models.functions import Coalesce
from eleganza.products.models import ProductCategory, Product
from eleganza.products.constants import FieldLengths
from eleganza.products.validators import validate_id, validate_category_depth
from django.core.exceptions import ValidationError

# Reusable annotation for active product count
ACTIVE_PRODUCTS_COUNT = Count(
    'products', 
    filter=Q(products__is_active=True)
)

def get_category_tree_with_stats() -> Iterable[ProductCategory]:
    """
    Get full category tree with annotated product counts.
    Uses Coalesce to handle null values safely.
    """
    return ProductCategory.objects.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))
    ).order_by('tree_id', 'lft')

def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination support
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion.
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        offset: Pagination offset
        fields: Specific product fields to include (None for all)
    """
    validate_category_depth(depth)
    
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs))
    
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe null handling
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs.
    Uses Coalesce to ensure valid values.
    """
    products = Product.objects.filter(
        is_active=True
    ).annotate(
        category_slug=Coalesce(F('category__slug'), Value('uncategorized'))
    ).values_list('category_slug', 'id')
    
    result = defaultdict(list)
    for slug, prod_id in products:
        result[slug].append(prod_id)
    return dict(result)

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True,
    offset: int = 0  # Added pagination
) -> List[ProductCategory]:
    """
    Get categories with the most active products.
    Uses reusable ACTIVE_PRODUCTS_COUNT annotation.
    """
    queryset = ProductCategory.objects.annotate(
        active_products=ACTIVE_PRODUCTS_COUNT
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[offset:offset + limit])  # Pagination

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category.
    Uses centralized slug validation.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(
        category.get_ancestors(include_self=True)
        .only('id', 'name', 'slug')
        .annotate(product_count=ACTIVE_PRODUCTS_COUNT)  # Reused annotation
    )

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Product]:
    """
    Get products for a category with optional filtering.
    Uses centralized ID validation.
    """
    validate_id(category_id, "Category ID")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count.
    Uses Coalesce for safe null handling.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    queryset = ProductCategory.objects.filter(slug=slug)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe default
    ).only('id', 'name', 'slug', 'product_count').first()

#========================================
# eleganza/products/selectors/inventory_selectors.py
#========================================

# eleganza/products/selectors/inventory_selectors.py
from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce, Cast
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from eleganza.products.models import Inventory, InventoryHistory, ProductVariant
from eleganza.products.constants import Defaults
from eleganza.products.validators import validate_id, validate_threshold  # Centralized validator
from django.conf import settings


# Reusable annotations
STOCK_STATUS = Coalesce(F('stock_quantity'), Value(0))
LOW_STOCK_FLAG = Q(stock_quantity__lte=F('low_stock_threshold'))


def get_inventory_status_cache_key(variant_id: int) -> str:
    """Generate unique cache key per variant"""
    return f"inventory_status_{variant_id}"


def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant with safe defaults.
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with inventory status or None if not found
    """
    validate_id(variant_id, "Variant ID")
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS,  # Reusable annotation
        low_stock_flag=LOW_STOCK_FLAG  # Reusable condition
    ).values(
        'current_stock',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku',
        'low_stock_flag'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info.
    Uses reusable STOCK_STATUS annotation.
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    validate_threshold(threshold)
    
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")

    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS  # Reusable annotation
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'current_stock',
        'low_stock_threshold'
    ).order_by('current_stock'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant.
    Uses centralized days_back validation.
    """
    validate_id(variant_id, "Variant ID")
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    # Pagination support
    if limit:
        history = history[offset:offset + limit]
    
    base_values = [
        'timestamp',
        'old_stock',
        'new_stock',
        'notes'
    ]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            sku=F('inventory__variant__sku')
        ).values(*base_values, 'sku'))
    
    return list(history.annotate(
        delta=F('new_stock') - F('old_stock')
    ).values(*base_values))


def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics.
    Uses Coalesce for safe aggregation.
    """
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=LOW_STOCK_FLAG),  # Reusable condition
        average_stock=Coalesce(Avg('stock_quantity'), Value(0))
    )
    
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=Coalesce(F('variant__product__selling_price_amount'), Value(0)),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY
    }

def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
    queryset = Inventory.objects.filter(
        variant__product_id=product_id
    ).select_related('variant')
    
    if only_in_stock:
        queryset = queryset.filter(stock_quantity__gt=0)
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if include_options:
        queryset = queryset.prefetch_related(
            'variant__options__attribute'
        )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return [
        {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity or 0,  # Safe default
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= (inv.low_stock_threshold or 0),
            **({'options': [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]} if include_options else {})
        }
        for inv in queryset
    ]

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity.
    Uses Coalesce for safe division.
    """
    if min_sales_velocity < 0:
        raise ValidationError("Sales velocity cannot be negative")
    if max_weeks_of_stock <= 0:
        raise ValidationError("Weeks of stock must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
    queryset = Inventory.objects.annotate(
        weekly_sales=Coalesce(
            Sum('history__old_stock' - 'history__new_stock',
                filter=Q(
                    history__timestamp__gte=timezone.now() - timedelta(days=21),
                    history__new_stock__lt=F('history__old_stock')
                )) / 3,
            Value(0.0)
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       Coalesce(F('weekly_sales'), Value(0.1)),  # Safe division
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'stock_quantity',
        'weekly_sales',
        'weeks_remaining',
        'product_name'
    ).order_by('weeks_remaining'))

def get_inventory_alerts(
    *,
    threshold: Optional[int] = None,
    min_sales_velocity: float = 5.0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts.
    Reuses other selector functions.
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit,
            offset=offset
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit,
            offset=offset
        )
    }

#========================================
# eleganza/products/selectors/product_selectors.py
#========================================

# eleganza/products/selectors/product_selectors.py
from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from django.db.models.functions import Coalesce
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.db.models import Value, FloatField

from eleganza.products.models import Product, ProductVariant, ProductReview, ProductCategory
from eleganza.products.constants import Defaults
from eleganza.products.validators import (
    validate_id,
    validate_price_range,
    validate_rating,
)

# Reusable annotations
REVIEW_STATS = {
    'avg_rating': Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
    'review_count': Count('reviews', filter=Q(reviews__is_approved=True))
}

DISCOUNT_FILTER = Q(
    Q(discount_percent__gt=0) |
    Q(discount_amount__amount__gt=0)
)

def get_products_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"products_{md5(str(kwargs).encode()).hexdigest()}"


def get_products(
    *,
    category_id: Optional[int] = None,
    only_active: bool = True,
    include_variants: bool = False,
    include_review_stats: bool = False,
    discount_threshold: Optional[float] = None,
    only_in_stock: bool = False,
    only_featured: bool = False,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries.
    Uses reusable REVIEW_STATS annotations.
    """
    if category_id is not None:
        validate_id(category_id, "Category ID")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Base filtering
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    
    # Inventory filtering
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Discount filtering
    if discount_threshold:
        queryset = queryset.filter(
            Q(discount_percent__gte=discount_threshold) |
            Q(discount_amount__amount__gte=discount_threshold)
        )
    
    # Related data prefetching
    if include_variants:
        variant_qs = ProductVariant.objects.filter(is_active=True)
        if only_in_stock:
            variant_qs = variant_qs.filter(inventory__stock_quantity__gt=0)
            
        queryset = queryset.prefetch_related(
            Prefetch('variants', 
                   queryset=variant_qs.select_related('inventory'))
        )
    
    if include_review_stats:
        queryset = queryset.annotate(**REVIEW_STATS)
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None,
    review_offset: int = 0
) -> Optional[Product]:
    """
    Get single product with optimized related data loading.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch with pagination
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[review_offset:review_offset + review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()


def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get featured products with optimized query.
    Uses reusable REVIEW_STATS annotations.
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = Product.objects.filter(
        is_featured=True,
        is_active=True
    ).select_related('category')
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if min_rating:
        queryset = queryset.annotate(
            avg_rating=REVIEW_STATS['avg_rating']
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    return list(queryset.order_by('?')[offset:offset + limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products within price range with inventory check.
    Uses centralized price validation.
    """
    validate_price_range(min_price, max_price)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        final_price__amount__gte=min_price,
        final_price__amount__lte=max_price,
        final_price__currency=currency,
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('final_price')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories.
    Uses reusable annotations and validators.
    """
    validate_id(category_id, "Category ID")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    # Build category filter
    if include_subcategories:
        categories = ProductCategory.objects.filter(
            Q(id=category_id) | Q(parent_id=category_id)
        )
    else:
        categories = ProductCategory.objects.filter(id=category_id)
    
    # Prefetch products with filtering
    product_qs = Product.objects.all()
    if only_active:
        product_qs = product_qs.filter(is_active=True)
    if only_featured:
        product_qs = product_qs.filter(is_featured=True)
    if fields:
        product_qs = product_qs.only(*fields)
    
    # Pagination support
    if limit:
        product_qs = product_qs[offset:offset + limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured')))
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }


def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product.
    Uses reusable rating distribution logic.
    """
    validate_id(product_id, "Product ID")
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        **REVIEW_STATS,
        **{
            f'stars_{i}': Count('id', filter=Q(rating=i))
            for i in range(1, 6)
        }
    )
    
    return {
        'average_rating': stats['avg_rating'] or 0,
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'stars_{i}'] for i in range(1, 6)
        }
    }

def get_products_with_discounts(
    min_discount: float = 10.0,
    *,
    only_active: bool = True,
    only_in_stock: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with significant discounts.
    Uses reusable DISCOUNT_FILTER.
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        DISCOUNT_FILTER,
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('-discount_percent')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

#========================================
# eleganza/products/selectors/products_selectors_combined.py
#========================================


#========================================
# eleganza/products/selectors/category_selectors.py
#========================================

from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional, Iterable
from collections import defaultdict
from django.db.models import Value, F
from django.db.models.functions import Coalesce
from eleganza.products.models import ProductCategory, Product
from eleganza.products.constants import FieldLengths
from eleganza.products.validators import validate_id, validate_category_depth
from django.core.exceptions import ValidationError

# Reusable annotation for active product count
ACTIVE_PRODUCTS_COUNT = Count(
    'products', 
    filter=Q(products__is_active=True)
)

def get_category_tree_with_stats() -> Iterable[ProductCategory]:
    """
    Get full category tree with annotated product counts.
    Uses Coalesce to handle null values safely.
    """
    return ProductCategory.objects.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))
    ).order_by('tree_id', 'lft')

def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination support
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion.
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        offset: Pagination offset
        fields: Specific product fields to include (None for all)
    """
    validate_category_depth(depth)
    
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs))
    
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe null handling
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs.
    Uses Coalesce to ensure valid values.
    """
    products = Product.objects.filter(
        is_active=True
    ).annotate(
        category_slug=Coalesce(F('category__slug'), Value('uncategorized'))
    ).values_list('category_slug', 'id')
    
    result = defaultdict(list)
    for slug, prod_id in products:
        result[slug].append(prod_id)
    return dict(result)

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True,
    offset: int = 0  # Added pagination
) -> List[ProductCategory]:
    """
    Get categories with the most active products.
    Uses reusable ACTIVE_PRODUCTS_COUNT annotation.
    """
    queryset = ProductCategory.objects.annotate(
        active_products=ACTIVE_PRODUCTS_COUNT
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[offset:offset + limit])  # Pagination

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category.
    Uses centralized slug validation.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(
        category.get_ancestors(include_self=True)
        .only('id', 'name', 'slug')
        .annotate(product_count=ACTIVE_PRODUCTS_COUNT)  # Reused annotation
    )

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Product]:
    """
    Get products for a category with optional filtering.
    Uses centralized ID validation.
    """
    validate_id(category_id, "Category ID")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count.
    Uses Coalesce for safe null handling.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    queryset = ProductCategory.objects.filter(slug=slug)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe default
    ).only('id', 'name', 'slug', 'product_count').first()

#========================================
# eleganza/products/selectors/inventory_selectors.py
#========================================

# eleganza/products/selectors/inventory_selectors.py
from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce, Cast
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from eleganza.products.models import Inventory, InventoryHistory, ProductVariant
from eleganza.products.constants import Defaults
from eleganza.products.validators import validate_id, validate_threshold  # Centralized validator
from django.conf import settings


# Reusable annotations
STOCK_STATUS = Coalesce(F('stock_quantity'), Value(0))
LOW_STOCK_FLAG = Q(stock_quantity__lte=F('low_stock_threshold'))


def get_inventory_status_cache_key(variant_id: int) -> str:
    """Generate unique cache key per variant"""
    return f"inventory_status_{variant_id}"


def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant with safe defaults.
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with inventory status or None if not found
    """
    validate_id(variant_id, "Variant ID")
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS,  # Reusable annotation
        low_stock_flag=LOW_STOCK_FLAG  # Reusable condition
    ).values(
        'current_stock',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku',
        'low_stock_flag'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info.
    Uses reusable STOCK_STATUS annotation.
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    validate_threshold(threshold)
    
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")

    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS  # Reusable annotation
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'current_stock',
        'low_stock_threshold'
    ).order_by('current_stock'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant.
    Uses centralized days_back validation.
    """
    validate_id(variant_id, "Variant ID")
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    # Pagination support
    if limit:
        history = history[offset:offset + limit]
    
    base_values = [
        'timestamp',
        'old_stock',
        'new_stock',
        'notes'
    ]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            sku=F('inventory__variant__sku')
        ).values(*base_values, 'sku'))
    
    return list(history.annotate(
        delta=F('new_stock') - F('old_stock')
    ).values(*base_values))


def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics.
    Uses Coalesce for safe aggregation.
    """
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=LOW_STOCK_FLAG),  # Reusable condition
        average_stock=Coalesce(Avg('stock_quantity'), Value(0))
    )
    
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=Coalesce(F('variant__product__selling_price_amount'), Value(0)),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY
    }

def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
    queryset = Inventory.objects.filter(
        variant__product_id=product_id
    ).select_related('variant')
    
    if only_in_stock:
        queryset = queryset.filter(stock_quantity__gt=0)
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if include_options:
        queryset = queryset.prefetch_related(
            'variant__options__attribute'
        )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return [
        {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity or 0,  # Safe default
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= (inv.low_stock_threshold or 0),
            **({'options': [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]} if include_options else {})
        }
        for inv in queryset
    ]

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity.
    Uses Coalesce for safe division.
    """
    if min_sales_velocity < 0:
        raise ValidationError("Sales velocity cannot be negative")
    if max_weeks_of_stock <= 0:
        raise ValidationError("Weeks of stock must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
    queryset = Inventory.objects.annotate(
        weekly_sales=Coalesce(
            Sum('history__old_stock' - 'history__new_stock',
                filter=Q(
                    history__timestamp__gte=timezone.now() - timedelta(days=21),
                    history__new_stock__lt=F('history__old_stock')
                )) / 3,
            Value(0.0)
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       Coalesce(F('weekly_sales'), Value(0.1)),  # Safe division
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'stock_quantity',
        'weekly_sales',
        'weeks_remaining',
        'product_name'
    ).order_by('weeks_remaining'))

def get_inventory_alerts(
    *,
    threshold: Optional[int] = None,
    min_sales_velocity: float = 5.0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts.
    Reuses other selector functions.
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit,
            offset=offset
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit,
            offset=offset
        )
    }

#========================================
# eleganza/products/selectors/product_selectors.py
#========================================

# eleganza/products/selectors/product_selectors.py
from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from django.db.models.functions import Coalesce
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.db.models import Value, FloatField

from eleganza.products.models import Product, ProductVariant, ProductReview, ProductCategory
from eleganza.products.constants import Defaults
from eleganza.products.validators import (
    validate_id,
    validate_price_range,
    validate_rating,
)

# Reusable annotations
REVIEW_STATS = {
    'avg_rating': Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
    'review_count': Count('reviews', filter=Q(reviews__is_approved=True))
}

DISCOUNT_FILTER = Q(
    Q(discount_percent__gt=0) |
    Q(discount_amount__amount__gt=0)
)

def get_products_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"products_{md5(str(kwargs).encode()).hexdigest()}"


def get_products(
    *,
    category_id: Optional[int] = None,
    only_active: bool = True,
    include_variants: bool = False,
    include_review_stats: bool = False,
    discount_threshold: Optional[float] = None,
    only_in_stock: bool = False,
    only_featured: bool = False,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries.
    Uses reusable REVIEW_STATS annotations.
    """
    if category_id is not None:
        validate_id(category_id, "Category ID")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Base filtering
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    
    # Inventory filtering
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Discount filtering
    if discount_threshold:
        queryset = queryset.filter(
            Q(discount_percent__gte=discount_threshold) |
            Q(discount_amount__amount__gte=discount_threshold)
        )
    
    # Related data prefetching
    if include_variants:
        variant_qs = ProductVariant.objects.filter(is_active=True)
        if only_in_stock:
            variant_qs = variant_qs.filter(inventory__stock_quantity__gt=0)
            
        queryset = queryset.prefetch_related(
            Prefetch('variants', 
                   queryset=variant_qs.select_related('inventory'))
        )
    
    if include_review_stats:
        queryset = queryset.annotate(**REVIEW_STATS)
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None,
    review_offset: int = 0
) -> Optional[Product]:
    """
    Get single product with optimized related data loading.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch with pagination
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[review_offset:review_offset + review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()


def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get featured products with optimized query.
    Uses reusable REVIEW_STATS annotations.
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = Product.objects.filter(
        is_featured=True,
        is_active=True
    ).select_related('category')
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if min_rating:
        queryset = queryset.annotate(
            avg_rating=REVIEW_STATS['avg_rating']
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    return list(queryset.order_by('?')[offset:offset + limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products within price range with inventory check.
    Uses centralized price validation.
    """
    validate_price_range(min_price, max_price)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        final_price__amount__gte=min_price,
        final_price__amount__lte=max_price,
        final_price__currency=currency,
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('final_price')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories.
    Uses reusable annotations and validators.
    """
    validate_id(category_id, "Category ID")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    # Build category filter
    if include_subcategories:
        categories = ProductCategory.objects.filter(
            Q(id=category_id) | Q(parent_id=category_id)
        )
    else:
        categories = ProductCategory.objects.filter(id=category_id)
    
    # Prefetch products with filtering
    product_qs = Product.objects.all()
    if only_active:
        product_qs = product_qs.filter(is_active=True)
    if only_featured:
        product_qs = product_qs.filter(is_featured=True)
    if fields:
        product_qs = product_qs.only(*fields)
    
    # Pagination support
    if limit:
        product_qs = product_qs[offset:offset + limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured')))
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }


def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product.
    Uses reusable rating distribution logic.
    """
    validate_id(product_id, "Product ID")
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        **REVIEW_STATS,
        **{
            f'stars_{i}': Count('id', filter=Q(rating=i))
            for i in range(1, 6)
        }
    )
    
    return {
        'average_rating': stats['avg_rating'] or 0,
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'stars_{i}'] for i in range(1, 6)
        }
    }

def get_products_with_discounts(
    min_discount: float = 10.0,
    *,
    only_active: bool = True,
    only_in_stock: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with significant discounts.
    Uses reusable DISCOUNT_FILTER.
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        DISCOUNT_FILTER,
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('-discount_percent')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


#========================================
# eleganza/products/selectors/review_selectors.py
#========================================

# eleganza/products/selectors/review_selectors.py
from django.db.models import Avg, Count, Q, F, Sum, FloatField
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import Trunc, Coalesce
from django.db.models import DateField, Value
from eleganza.products.models import ProductReview, Product
from eleganza.products.constants import Defaults
from eleganza.products.validators import (
    validate_id,
    validate_rating,
    validate_days_range,
)

# Reusable annotations and constants
BASE_REVIEW_STATS = {
    'avg_rating': Avg('rating'),
    'review_count': Count('id'),
    'helpful_percentage': Coalesce(
        Avg(F('helpful_votes') / (F('helpful_votes') + 1), 
        Value(0.0),
        output_field=FloatField()
    ) * 100)
}

RATING_DISTRIBUTION = {
    f'stars_{i}': Count('id', filter=Q(rating=i))
    for i in range(1, 6)
}

def get_reviews_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"reviews_{md5(str(kwargs).encode()).hexdigest()}"


def get_product_reviews(
    product_id: int,
    *,
    only_approved: bool = True,
    min_rating: Optional[int] = None,
    recent_days: Optional[int] = None,
    include_user_info: bool = False,
    include_product_info: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    order_by: str = '-created_at'
) -> List[ProductReview]:
    """
    Get filtered reviews for a product with optimized queries.
    Uses centralized validation and reusable annotations.
    """
    validate_id(product_id, "Product ID")
    if min_rating is not None:
        validate_rating(min_rating)
    if recent_days is not None:
        validate_days_range(recent_days)
    if limit is not None:
        validate_limit(limit)

    queryset = ProductReview.objects.filter(product_id=product_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if recent_days:
        cutoff = timezone.now() - timedelta(days=recent_days)
        queryset = queryset.filter(created_at__gte=cutoff)
    
    if include_user_info:
        queryset = queryset.select_related('user')
    
    if include_product_info:
        queryset = queryset.select_related('product')
    
    # Pagination support
    queryset = queryset.order_by(order_by)
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_review_stats(product_id: int) -> Dict[str, any]:
    """
    Get comprehensive review statistics for a product.
    Uses reusable BASE_REVIEW_STATS and RATING_DISTRIBUTION.
    """
    validate_id(product_id, "Product ID")
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        **BASE_REVIEW_STATS,
        **RATING_DISTRIBUTION
    )
    
    return {
        'average_rating': round(stats['avg_rating'] or 0, 1),
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'stars_{i}'] for i in range(1, 6)
        },
        'helpful_percentage': stats['helpful_percentage']
    }


def get_recent_reviews(
    *,
    limit: int = 5,
    min_rating: Optional[int] = None,
    with_product_info: bool = False,
    with_user_info: bool = False,
    days_back: Optional[int] = None,
    offset: int = 0
) -> List[ProductReview]:
    """
    Get most recent reviews across all products.
    Uses centralized validation and pagination.
    """
    validate_limit(limit, max_value=100)
    if min_rating is not None:
        validate_rating(min_rating)
    if days_back is not None:
        validate_days_range(days_back)

    queryset = ProductReview.objects.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if days_back:
        cutoff = timezone.now() - timedelta(days=days_back)
        queryset = queryset.filter(created_at__gte=cutoff)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    if with_user_info:
        queryset = queryset.select_related('user')
    
    # Pagination support
    return list(queryset.order_by('-created_at')[offset:offset + limit])

def get_user_reviews(
    user_id: int,
    *,
    only_approved: bool = True,
    with_product_info: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get all reviews by a specific user.
    Uses reusable validation and pagination.
    """
    validate_id(user_id, "User ID")
    if limit is not None:
        validate_limit(limit)
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(user_id=user_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    # Pagination support
    queryset = queryset.order_by('-created_at')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_most_helpful_reviews(
    product_id: int,
    *,
    limit: int = 3,
    min_helpful_votes: int = 5,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews with the most helpful votes.
    Uses centralized validation and reusable filters.
    """
    validate_id(product_id, "Product ID")
    validate_limit(limit, max_value=20)
    if min_helpful_votes < 0:
        raise ValidationError("Helpful votes cannot be negative")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True,
        helpful_votes__gte=min_helpful_votes
    )
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    return list(queryset.order_by('-helpful_votes', '-created_at')[:limit])


def get_review_histogram(
    product_id: int,
    *,
    time_period: str = 'monthly',  # 'daily', 'weekly', 'monthly'
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, any]]:
    """
    Get review count over time for trend analysis.
    Uses centralized validation and Trunc date functions.
    """
    validate_id(product_id, "Product ID")
    if time_period not in ['daily', 'weekly', 'monthly']:
        raise ValidationError("Invalid time period")
    if limit is not None:
        validate_limit(limit)

    trunc_map = {
        'daily': 'day',
        'weekly': 'week',
        'monthly': 'month'
    }
    
    queryset = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).annotate(
        period=Trunc('created_at', trunc_map[time_period], output_field=DateField())
    ).values(
        'period'
    ).annotate(
        review_count=Count('id'),
        average_rating=Avg('rating')
    ).order_by('period')
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_review_engagement_stats() -> Dict[str, any]:
    """
    Get store-wide review engagement metrics.
    Uses reusable BASE_REVIEW_STATS annotations.
    """
    stats = ProductReview.objects.aggregate(
        **BASE_REVIEW_STATS
    )
    
    # If tracking admin responses
    if hasattr(ProductReview, 'response_text'):
        stats['response_rate'] = ProductReview.objects.filter(
            response_text__isnull=False
        ).count() / stats['review_count'] * 100 if stats['review_count'] else 0
    
    return stats

def get_pending_reviews(
    *,
    limit: Optional[int] = None,
    days_old: Optional[int] = None,
    min_rating: Optional[int] = None,
    offset: int = 0
) -> List[ProductReview]:
    """
    Get reviews awaiting moderation.
    Uses centralized validation and pagination.
    """
    if limit is not None:
        validate_limit(limit)
    if days_old is not None and days_old <= 0:
        raise ValidationError("Days old must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(
        is_approved=False
    ).select_related(
        'user',
        'product'
    )
    
    if days_old:
        cutoff = timezone.now() - timedelta(days=days_old)
        queryset = queryset.filter(created_at__lte=cutoff)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    # Pagination support
    queryset = queryset.order_by('created_at')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_review_summary_by_category(
    category_id: int,
    *,
    include_subcategories: bool = False
) -> Dict[str, Dict[str, float]]:
    """
    Get review statistics aggregated by product category.
    Uses reusable BASE_REVIEW_STATS annotations.
    """
    validate_id(category_id, "Category ID")
    
    # Get category tree
    categories = ProductCategory.objects.filter(id=category_id)
    if include_subcategories:
        categories = categories.get_descendants(include_self=True)
    
    # Get stats for each category
    results = {}
    for category in categories:
        stats = ProductReview.objects.filter(
            product__category=category,
            is_approved=True
        ).aggregate(
            **BASE_REVIEW_STATS
        )
        
        results[category.name] = {
            'average_rating': stats['avg_rating'] or 0,
            'review_count': stats['review_count'],
            'helpful_percentage': stats['helpful_percentage'] or 0
        }
    
    return results

#========================================
# eleganza/products/selectors/variant_selectors.py
#========================================

# eleganza/products/selectors/variant_selectors.py
from django.db.models import Prefetch, Q, F, Count, Subquery, OuterRef, FloatField
from django.db.models.functions import Coalesce, Cast
from typing import List, Dict, Optional, Sequence
from django.core.exceptions import ValidationError
from django.db.models import Value
from eleganza.products.models import ProductVariant, ProductOption, Inventory
from eleganza.products.constants import FieldLengths, Defaults
from eleganza.products.validators import (
    validate_id,
    validate_option_ids,
    validate_threshold,
    validate_limit
)

# Reusable annotations
INVENTORY_STATUS = {
    'stock': Coalesce(F('inventory__stock_quantity'), Value(0)),
    'low_stock': Q(inventory__stock_quantity__lte=F('inventory__low_stock_threshold'))
}

PRICE_MODIFIER_FIELDS = {
    'price_amount': Cast(F('price_modifier__amount'), FloatField()),
    'price_currency': F('price_modifier__currency')
}

def get_variant_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"variant_{md5(str(kwargs).encode()).hexdigest()}"


def get_variants_for_product(
    product_id: int,
    *,
    only_active: bool = True,
    include_inventory: bool = True,
    include_options: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[ProductVariant]:
    """
    Get variants for a product with configurable related data.
    Uses centralized validation and reusable annotations.
    """
    validate_id(product_id, "Product ID")
    if limit is not None:
        validate_limit(limit)

    queryset = ProductVariant.objects.filter(product_id=product_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    if include_inventory:
        queryset = queryset.select_related('inventory')
    
    if include_options:
        option_qs = ProductOption.objects.select_related('attribute')
        if fields and 'options' not in fields:
            option_qs = option_qs.only('id', 'value', 'attribute__name')
        queryset = queryset.prefetch_related(
            Prefetch('options', queryset=option_qs)
        )
    
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.order_by('-is_default', 'sku'))


def get_variant_with_full_details(
    variant_id: int,
    *,
    include_inventory_history: bool = False,
    history_days: int = 30
) -> Optional[Dict[str, any]]:
    """
    Get single variant with complete related data.
    Uses reusable INVENTORY_STATUS annotations.
    """
    validate_id(variant_id, "Variant ID")
    validate_days_range(history_days)

    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'product',
        'inventory'
    ).prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    ).annotate(
        product_name=F('product__name'),
        product_slug=F('product__slug'),
        **INVENTORY_STATUS
    ).values(
        'id',
        'sku',
        'is_default',
        'is_active',
        'price_modifier',
        'product_id',
        'product_name',
        'product_slug',
        'stock',
        'low_stock',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = dict(variant)
    
    # Convert MoneyField to serializable format
    result['price_modifier'] = {
        'amount': float(variant['price_modifier'].amount),
        'currency': str(variant['price_modifier'].currency)
    }
    
    # Get options data
    options = ProductOption.objects.filter(
        variants=variant_id
    ).select_related('attribute').values(
        'id',
        'value',
        'attribute__name',
        'attribute__code'
    )
    result['options'] = list(options)
    
    # Include inventory history if requested
    if include_inventory_history:
        from .inventory_selectors import get_inventory_history
        result['inventory_history'] = get_inventory_history(
            variant_id,
            days_back=history_days
        )
    
    return result

def get_variants_by_options(
    product_id: int,
    option_ids: List[int],
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[ProductVariant]:
    """
    Find variants matching specific option combinations.
    Uses centralized validation for IDs.
    """
    validate_id(product_id, "Product ID")
    validate_option_ids(option_ids)
    if limit is not None:
        validate_limit(limit)

    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        options__in=option_ids
    ).annotate(
        option_count=Count('options')
    ).filter(
        option_count=len(option_ids)  # Must have all specified options
    ).distinct()
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    queryset = queryset.prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_default_variant(
    product_id: int,
    *,
    only_in_stock: bool = False
) -> Optional[ProductVariant]:
    """
    Get the default variant for a product.
    Uses reusable INVENTORY_STATUS annotations.
    """
    validate_id(product_id, "Product ID")

    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        is_default=True
    ).select_related('inventory')
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    return queryset.annotate(
        **INVENTORY_STATUS
    ).first()

def get_variant_inventory_status(
    variant_id: int,
    *,
    include_historical: bool = False,
    historical_days: int = 30
) -> Dict[str, any]:
    """
    Get comprehensive inventory status for a variant.
    Uses centralized validation and reusable components.
    """
    validate_id(variant_id, "Variant ID")
    validate_days_range(historical_days)

    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'inventory'
    ).annotate(
        sku=F('sku'),
        **INVENTORY_STATUS
    ).values(
        'id',
        'sku',
        'stock',
        'low_stock',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = {
        'variant_id': variant['id'],
        'sku': variant['sku'],
        'current_stock': variant['stock'],
        'low_stock': variant['low_stock'],
        'low_stock_threshold': variant['inventory__low_stock_threshold'],
        'last_restock': variant['inventory__last_restock']
    }
    
    if include_historical:
        from .inventory_selectors import get_inventory_history
        result['historical_changes'] = get_inventory_history(
            variant['id'],
            days_back=historical_days
        )
    
    return result

def get_variants_with_low_stock(
    product_id: Optional[int] = None,
    *,
    threshold: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, any]]:
    """
    Get variants below stock threshold.
    Uses reusable PRICE_MODIFIER_FIELDS and validation.
    """
    if product_id is not None:
        validate_id(product_id, "Product ID")
    if threshold is not None:
        validate_threshold(threshold)
    if limit is not None:
        validate_limit(limit)

    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    queryset = ProductVariant.objects.filter(
        inventory__stock_quantity__lte=threshold,
        is_active=True
    ).select_related(
        'product',
        'inventory'
    ).annotate(
        product_name=F('product__name'),
        current_stock=F('inventory__stock_quantity'),
        threshold=F('inventory__low_stock_threshold'),
        **PRICE_MODIFIER_FIELDS
    ).values(
        'id',
        'sku',
        'product_name',
        'current_stock',
        'threshold',
        'price_amount',
        'price_currency'
    ).order_by('current_stock')
    
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_variant_price_range(product_id: int) -> Optional[Dict[str, float]]:
    """
    Get min/max pricing for a product's variants.
    Uses reusable PRICE_MODIFIER_FIELDS.
    """
    validate_id(product_id, "Product ID")

    result = ProductVariant.objects.filter(
        product_id=product_id,
        is_active=True
    ).aggregate(
        min_price=Min('price_modifier'),
        max_price=Max('price_modifier')
    )
    
    if not result['min_price']:
        return None
        
    return {
        'min_price': float(result['min_price'].amount),
        'max_price': float(result['max_price'].amount),
        'currency': str(result['min_price'].currency)
    }

def get_variants_by_attribute(
    product_id: int,
    attribute_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_pricing: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> Dict[str, List[Dict[str, any]]]:
    """
    Group variants by attribute option.
    Uses centralized validation and reusable components.
    """
    validate_id(product_id, "Product ID")
    validate_id(attribute_id, "Attribute ID")
    if limit is not None:
        validate_limit(limit)

    variants = ProductVariant.objects.filter(
        product_id=product_id,
        options__attribute_id=attribute_id
    )
    
    if only_in_stock:
        variants = variants.filter(inventory__stock_quantity__gt=0)
    if only_active:
        variants = variants.filter(is_active=True)
    
    variants = variants.prefetch_related(
        'options'
    ).annotate(
        option_value=Subquery(
            ProductOption.objects.filter(
                attribute_id=attribute_id,
                variants=OuterRef('pk')
            ).values('value')[:1]
        ),
        in_stock=Q(inventory__stock_quantity__gt=0),
        **PRICE_MODIFIER_FIELDS
    )
    
    result = {}
    for variant in variants:
        value = variant.option_value
        if value not in result:
            result[value] = []
        
        variant_data = {
            'id': variant.id,
            'sku': variant.sku,
            'in_stock': variant.in_stock,
            'is_default': variant.is_default
        }
        
        if include_pricing:
            variant_data.update({
                'price_amount': float(variant.price_amount),
                'price_currency': str(variant.price_currency)
            })
        
        result[value].append(variant_data)
    
    # Apply pagination per option group
    if limit:
        for key in result:
            result[key] = result[key][offset:offset + limit]
    
    return result

def get_variant_availability(
    variant_ids: Sequence[int],
    *,
    threshold: Optional[int] = None
) -> Dict[int, Dict[str, any]]:
    """
    Get availability status for multiple variants.
    Uses reusable INVENTORY_STATUS annotations.
    """
    if not variant_ids:
        return {}
    
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    variants = ProductVariant.objects.filter(
        id__in=variant_ids
    ).select_related('inventory').annotate(
        **INVENTORY_STATUS
    ).values(
        'id',
        'stock',
        'low_stock'
    )
    
    return {
        v['id']: {
            'in_stock': v['stock'] > 0,
            'low_stock': v['low_stock'],
            'stock_quantity': v['stock']
        }
        for v in variants
    }
