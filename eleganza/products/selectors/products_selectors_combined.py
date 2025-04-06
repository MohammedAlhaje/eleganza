
#========================================
# eleganza/products/selectors/category_selectors.py
#========================================

from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional ,Iterable
from django.core.exceptions import ValidationError

from collections import defaultdict
from ..models import ProductCategory, Product
from ..constants import FieldLengths
from django.views.decorators.cache import cache_page

def validate_category_depth(depth: Optional[int]) -> None:
    """Validate depth parameter for category queries"""
    if depth is not None and (depth < 1 or depth > 10):
        raise ValidationError("Depth must be between 1 and 10")


def get_category_tree_with_stats() -> Iterable[ProductCategory]:
    """
    Get full category tree with annotated product counts
    
    Returns:
        Queryset of categories with product_count annotation
    """
    return ProductCategory.objects.annotate(
        product_count=Count('products')
    ).order_by('tree_id', 'lft')


def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        fields: Specific product fields to include (None for all)
        
    Returns:
        List of root categories with children relationships
        
    Raises:
        ValidationError: For invalid depth parameter
    """
    validate_category_depth(depth)
    
    # Base queryset for root categories
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    # Apply depth filtering
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    # Product prefetch configuration
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    # Children prefetch with annotation
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Apply limit if specified
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_category_with_children(
    category_id: int,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get single category with its immediate children
    
    Args:
        category_id: ID of the parent category
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance with prefetched children or None
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = ProductCategory.objects.filter(pk=category_id)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.prefetch_related(
        Prefetch('children',
               queryset=ProductCategory.objects.annotate(
                   product_count=Count('products', filter=Q(products__is_active=True))
               ).only('id', 'name', 'slug', 'product_count'))
    ).first()

@cache_page(60 * 15)  # Cache for 15 minutes
def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs
    
    Returns:
        Dictionary {category_slug: [product_id1, product_id2]}
    """
    products = Product.objects.filter(
        is_active=True
    ).values_list('category__slug', 'id')
    
    result = defaultdict(list)
    for slug, prod_id in products:
        result[slug].append(prod_id)
    return dict(result)

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True
) -> List[ProductCategory]:
    """
    Get categories with the most active products
    
    Args:
        limit: Number of categories to return
        min_products: Minimum active products to include
        only_active: Only include active categories
        
    Returns:
        List of categories ordered by product count
    """
    queryset = ProductCategory.objects.annotate(
        active_products=Count('products', filter=Q(products__is_active=True))
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[:limit])

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category
    
    Args:
        slug: Category slug
        
    Returns:
        Ordered list from root to target category
        
    Raises:
        ValidationError: If slug is empty
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(category.get_ancestors(include_self=True).only('id', 'name', 'slug'))

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get products for a category with optional filtering
    
    Args:
        category_id: ID of the category
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        
    Returns:
        List of Product instances
        
    Raises:
        ValidationError: For invalid category ID
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count
    
    Args:
        slug: Category slug
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance or None
        
    Raises:
        ValidationError: If slug is empty
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
        product_count=Count('products', filter=Q(products__is_active=True))
    ).only('id', 'name', 'slug', 'product_count').first()

#========================================
# eleganza/products/selectors/inventory_selectors.py
#========================================

from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce
from typing import List, Dict, Optional
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from django.utils import timezone
from datetime import timedelta
from ..models import Inventory, InventoryHistory, ProductVariant
from ..constants import Defaults
from django.conf import settings


def validate_inventory_id(inventory_id: int) -> None:
    """Validate inventory ID parameter"""
    if inventory_id <= 0:
        raise ValidationError("Inventory ID must be positive")

def validate_variant_id(variant_id: int) -> None:
    """Validate variant ID parameter"""
    if variant_id <= 0:
        raise ValidationError("Variant ID must be positive")

@cache_page(60 * 15)  # Cache for 15 minutes
def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with:
        - current_stock
        - low_stock_flag
        - last_restock_date
        - monthly_movement (avg)
        or None if not found
        
    Raises:
        ValidationError: If variant_id is invalid
    """
    validate_variant_id(variant_id)
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku')
    ).values(
        'stock_quantity',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'low_stock_flag': inventory['stock_quantity'] <= inventory['low_stock_threshold'],
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info
    
    Args:
        threshold: Custom threshold (uses default if None)
        only_active: Only include active variants
        min_stock: Minimum stock quantity to include
        limit: Maximum number of items to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    if threshold <= 0:
        raise ValidationError("Threshold must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'stock_quantity',
        'low_stock_threshold'
    ).order_by('stock_quantity'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None,
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant
    
    Args:
        variant_id: ID of the variant
        days_back: Number of days to look back (1-365)
        limit: Maximum records to return
        include_metadata: Include variant info in results
        
    Returns:
        List of historical records with:
        - date
        - old_stock
        - new_stock
        - delta
        - notes
        - variant_info (if include_metadata=True)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    if limit:
        history = history[:limit]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            date=F('timestamp'),
            sku=F('inventory__variant__sku')
        ).values(
            'date',
            'old_stock',
            'new_stock',
            'delta',
            'notes',
            'sku'
        ))
    else:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            date=F('timestamp')
        ).values(
            'date',
            'old_stock',
            'new_stock',
            'delta',
            'notes'
        ))

@cache_page(60 * 60)  # Cache for 1 hour
def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics
    
    Returns:
        Dictionary with:
        - total_items: Count of all inventory items
        - out_of_stock: Count of items with 0 stock
        - low_stock: Count below threshold
        - average_stock: Mean inventory level
        - total_value: Estimated inventory value
    """
    # Basic counts
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=Q(
            stock_quantity__gt=0,
            stock_quantity__lte=Defaults.LOW_STOCK_THRESHOLD
        )),
        average_stock=Avg('stock_quantity')
    )
    
    # Calculate total value using ORM
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=F('variant__product__selling_price_amount'),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY  #default currency
    }
def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product
    
    Args:
        product_id: ID of the parent product
        only_in_stock: Only include variants with stock > 0
        only_active: Only include active variants
        include_options: Include variant options data
        
    Returns:
        List of variant inventories with:
        - variant_id
        - sku
        - options (if include_options)
        - stock
        - last_updated
        - is_active
        
    Raises:
        ValidationError: For invalid product ID
    """
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")
    
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
    
    inventories = []
    for inv in queryset:
        inventory_data = {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity,
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= inv.low_stock_threshold
        }
        
        if include_options:
            inventory_data['options'] = [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]
        
        inventories.append(inventory_data)
    
    return inventories

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity
    
    Args:
        min_sales_velocity: Minimum weekly sales to consider
        max_weeks_of_stock: Maximum weeks of inventory to maintain
        min_stock: Current stock must be above this value
        limit: Maximum number of results to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - current_stock
        - weekly_sales
        - weeks_remaining
        - product_name
        
    Raises:
        ValidationError: For invalid parameters
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
                )) / 3,  # 3 weeks average
            Value(0.0, output_field=FloatField())
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       (F('weekly_sales') + 0.1),  # Avoid division by zero
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    if limit:
        queryset = queryset[:limit]
    
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
    limit: Optional[int] = None
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts
    
    Args:
        threshold: Low stock threshold
        min_sales_velocity: Minimum sales for restock candidates
        limit: Max alerts per type
        
    Returns:
        Dictionary with:
        - low_stock: List of low stock items
        - needs_restock: List of restock candidates
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit
        )
    }

#========================================
# eleganza/products/selectors/product_selectors.py
#========================================

from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from ..models import Product, ProductVariant, ProductReview, ProductCategory
from ..constants import Defaults

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_price_range(min_price: float, max_price: float) -> None:
    """Validate price range parameters"""
    if min_price < 0 or max_price < 0:
        raise ValidationError("Prices cannot be negative")
    if min_price > max_price:
        raise ValidationError("Min price cannot exceed max price")

@cache_page(60 * 60)  # Cache for 1 hour
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries
    
    Args:
        category_id: Filter by category
        only_active: Only include active products
        include_variants: Prefetch variants data
        include_review_stats: Include review aggregates
        discount_threshold: Minimum discount percentage/amount
        only_in_stock: Only include products with available inventory
        only_featured: Only include featured products
        fields: Specific fields to return (None for all)
        limit: Maximum number of products to return
        
    Returns:
        List of Product instances with requested data
        
    Raises:
        ValidationError: For invalid parameters
    """
    if category_id is not None and category_id <= 0:
        raise ValidationError("Category ID must be positive")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Basic filtering
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
                   queryset=variant_qs.select_related('inventory')))
    
    if include_review_stats:
        queryset = queryset.annotate(
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            review_count=Count('reviews', filter=Q(reviews__is_approved=True))
        )
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Ordering and limiting
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None
) -> Optional[Product]:
    """
    Get single product with optimized related data loading
    
    Args:
        product_id: ID of product to fetch
        with_variants: Include variants and inventory
        with_reviews: Include reviews and ratings
        with_category: Include category details
        review_limit: Maximum reviews to include
        
    Returns:
        Product instance with requested relations or None
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[:review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()

@cache_page(60 * 30)  # Cache for 30 minutes
def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get featured products with optimized query
    
    Args:
        limit: Maximum number of products to return
        only_in_stock: Only include products with inventory
        min_rating: Minimum average rating
        fields: Specific fields to return (None for all)
        
    Returns:
        List of featured Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None and (min_rating < 0 or min_rating > 5):
        raise ValidationError("Rating must be between 0 and 5")

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
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('?')[:limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products within price range with inventory check
    
    Args:
        min_price: Minimum price threshold
        max_price: Maximum price threshold
        currency: Currency code for price comparison
        only_in_stock: Only include available products
        only_active: Only include active products
        limit: Maximum number of products to return
        
    Returns:
        List of matching Product instances
        
    Raises:
        ValidationError: For invalid parameters
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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('final_price'))

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories
    
    Args:
        category_id: Parent category ID
        include_subcategories: Include products from child categories
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        limit: Maximum products per category
        
    Returns:
        Dictionary with category names as keys and product lists as values
        
    Raises:
        ValidationError: For invalid category ID
    """
    validate_product_id(category_id)
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
    if limit:
        product_qs = product_qs[:limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured'))
    )
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }

@cache_page(60 * 60)  # Cache for 1 hour
def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product
    
    Args:
        product_id: Product to analyze
        
    Returns:
        Dictionary with:
        - average_rating
        - review_count
        - rating_distribution (1-5 stars)
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id'),
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with significant discounts
    
    Args:
        min_discount: Minimum discount percentage/amount
        only_active: Only include active products
        only_in_stock: Only include available products
        limit: Maximum number of products to return
        
    Returns:
        List of discounted Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        Q(discount_percent__gte=min_discount) |
        Q(discount_amount__amount__gte=min_discount),
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('-discount_percent'))

#========================================
# eleganza/products/selectors/products_selectors_combined.py
#========================================


#========================================
# eleganza/products/selectors/category_selectors.py
#========================================

from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional ,Iterable
from django.core.exceptions import ValidationError

from collections import defaultdict
from ..models import ProductCategory, Product
from ..constants import FieldLengths
from django.views.decorators.cache import cache_page

def validate_category_depth(depth: Optional[int]) -> None:
    """Validate depth parameter for category queries"""
    if depth is not None and (depth < 1 or depth > 10):
        raise ValidationError("Depth must be between 1 and 10")


def get_category_tree_with_stats() -> Iterable[ProductCategory]:
    """
    Get full category tree with annotated product counts
    
    Returns:
        Queryset of categories with product_count annotation
    """
    return ProductCategory.objects.annotate(
        product_count=Count('products')
    ).order_by('tree_id', 'lft')


def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        fields: Specific product fields to include (None for all)
        
    Returns:
        List of root categories with children relationships
        
    Raises:
        ValidationError: For invalid depth parameter
    """
    validate_category_depth(depth)
    
    # Base queryset for root categories
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    # Apply depth filtering
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    # Product prefetch configuration
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    # Children prefetch with annotation
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Apply limit if specified
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_category_with_children(
    category_id: int,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get single category with its immediate children
    
    Args:
        category_id: ID of the parent category
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance with prefetched children or None
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = ProductCategory.objects.filter(pk=category_id)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.prefetch_related(
        Prefetch('children',
               queryset=ProductCategory.objects.annotate(
                   product_count=Count('products', filter=Q(products__is_active=True))
               ).only('id', 'name', 'slug', 'product_count'))
    ).first()

@cache_page(60 * 15)  # Cache for 15 minutes
def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs
    
    Returns:
        Dictionary {category_slug: [product_id1, product_id2]}
    """
    products = Product.objects.filter(
        is_active=True
    ).values_list('category__slug', 'id')
    
    result = defaultdict(list)
    for slug, prod_id in products:
        result[slug].append(prod_id)
    return dict(result)

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True
) -> List[ProductCategory]:
    """
    Get categories with the most active products
    
    Args:
        limit: Number of categories to return
        min_products: Minimum active products to include
        only_active: Only include active categories
        
    Returns:
        List of categories ordered by product count
    """
    queryset = ProductCategory.objects.annotate(
        active_products=Count('products', filter=Q(products__is_active=True))
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[:limit])

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category
    
    Args:
        slug: Category slug
        
    Returns:
        Ordered list from root to target category
        
    Raises:
        ValidationError: If slug is empty
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(category.get_ancestors(include_self=True).only('id', 'name', 'slug'))

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get products for a category with optional filtering
    
    Args:
        category_id: ID of the category
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        
    Returns:
        List of Product instances
        
    Raises:
        ValidationError: For invalid category ID
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count
    
    Args:
        slug: Category slug
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance or None
        
    Raises:
        ValidationError: If slug is empty
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
        product_count=Count('products', filter=Q(products__is_active=True))
    ).only('id', 'name', 'slug', 'product_count').first()

#========================================
# eleganza/products/selectors/inventory_selectors.py
#========================================

from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce
from typing import List, Dict, Optional
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from django.utils import timezone
from datetime import timedelta
from ..models import Inventory, InventoryHistory, ProductVariant
from ..constants import Defaults
from django.conf import settings


def validate_inventory_id(inventory_id: int) -> None:
    """Validate inventory ID parameter"""
    if inventory_id <= 0:
        raise ValidationError("Inventory ID must be positive")

def validate_variant_id(variant_id: int) -> None:
    """Validate variant ID parameter"""
    if variant_id <= 0:
        raise ValidationError("Variant ID must be positive")

@cache_page(60 * 15)  # Cache for 15 minutes
def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with:
        - current_stock
        - low_stock_flag
        - last_restock_date
        - monthly_movement (avg)
        or None if not found
        
    Raises:
        ValidationError: If variant_id is invalid
    """
    validate_variant_id(variant_id)
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku')
    ).values(
        'stock_quantity',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'low_stock_flag': inventory['stock_quantity'] <= inventory['low_stock_threshold'],
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info
    
    Args:
        threshold: Custom threshold (uses default if None)
        only_active: Only include active variants
        min_stock: Minimum stock quantity to include
        limit: Maximum number of items to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    if threshold <= 0:
        raise ValidationError("Threshold must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'stock_quantity',
        'low_stock_threshold'
    ).order_by('stock_quantity'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None,
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant
    
    Args:
        variant_id: ID of the variant
        days_back: Number of days to look back (1-365)
        limit: Maximum records to return
        include_metadata: Include variant info in results
        
    Returns:
        List of historical records with:
        - date
        - old_stock
        - new_stock
        - delta
        - notes
        - variant_info (if include_metadata=True)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    if limit:
        history = history[:limit]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            date=F('timestamp'),
            sku=F('inventory__variant__sku')
        ).values(
            'date',
            'old_stock',
            'new_stock',
            'delta',
            'notes',
            'sku'
        ))
    else:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            date=F('timestamp')
        ).values(
            'date',
            'old_stock',
            'new_stock',
            'delta',
            'notes'
        ))

@cache_page(60 * 60)  # Cache for 1 hour
def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics
    
    Returns:
        Dictionary with:
        - total_items: Count of all inventory items
        - out_of_stock: Count of items with 0 stock
        - low_stock: Count below threshold
        - average_stock: Mean inventory level
        - total_value: Estimated inventory value
    """
    # Basic counts
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=Q(
            stock_quantity__gt=0,
            stock_quantity__lte=Defaults.LOW_STOCK_THRESHOLD
        )),
        average_stock=Avg('stock_quantity')
    )
    
    # Calculate total value using ORM
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=F('variant__product__selling_price_amount'),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY  #default currency
    }
def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product
    
    Args:
        product_id: ID of the parent product
        only_in_stock: Only include variants with stock > 0
        only_active: Only include active variants
        include_options: Include variant options data
        
    Returns:
        List of variant inventories with:
        - variant_id
        - sku
        - options (if include_options)
        - stock
        - last_updated
        - is_active
        
    Raises:
        ValidationError: For invalid product ID
    """
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")
    
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
    
    inventories = []
    for inv in queryset:
        inventory_data = {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity,
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= inv.low_stock_threshold
        }
        
        if include_options:
            inventory_data['options'] = [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]
        
        inventories.append(inventory_data)
    
    return inventories

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity
    
    Args:
        min_sales_velocity: Minimum weekly sales to consider
        max_weeks_of_stock: Maximum weeks of inventory to maintain
        min_stock: Current stock must be above this value
        limit: Maximum number of results to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - current_stock
        - weekly_sales
        - weeks_remaining
        - product_name
        
    Raises:
        ValidationError: For invalid parameters
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
                )) / 3,  # 3 weeks average
            Value(0.0, output_field=FloatField())
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       (F('weekly_sales') + 0.1),  # Avoid division by zero
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    if limit:
        queryset = queryset[:limit]
    
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
    limit: Optional[int] = None
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts
    
    Args:
        threshold: Low stock threshold
        min_sales_velocity: Minimum sales for restock candidates
        limit: Max alerts per type
        
    Returns:
        Dictionary with:
        - low_stock: List of low stock items
        - needs_restock: List of restock candidates
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit
        )
    }

#========================================
# eleganza/products/selectors/product_selectors.py
#========================================

from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from ..models import Product, ProductVariant, ProductReview, ProductCategory
from ..constants import Defaults

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_price_range(min_price: float, max_price: float) -> None:
    """Validate price range parameters"""
    if min_price < 0 or max_price < 0:
        raise ValidationError("Prices cannot be negative")
    if min_price > max_price:
        raise ValidationError("Min price cannot exceed max price")

@cache_page(60 * 60)  # Cache for 1 hour
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries
    
    Args:
        category_id: Filter by category
        only_active: Only include active products
        include_variants: Prefetch variants data
        include_review_stats: Include review aggregates
        discount_threshold: Minimum discount percentage/amount
        only_in_stock: Only include products with available inventory
        only_featured: Only include featured products
        fields: Specific fields to return (None for all)
        limit: Maximum number of products to return
        
    Returns:
        List of Product instances with requested data
        
    Raises:
        ValidationError: For invalid parameters
    """
    if category_id is not None and category_id <= 0:
        raise ValidationError("Category ID must be positive")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Basic filtering
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
                   queryset=variant_qs.select_related('inventory')))
    
    if include_review_stats:
        queryset = queryset.annotate(
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            review_count=Count('reviews', filter=Q(reviews__is_approved=True))
        )
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Ordering and limiting
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None
) -> Optional[Product]:
    """
    Get single product with optimized related data loading
    
    Args:
        product_id: ID of product to fetch
        with_variants: Include variants and inventory
        with_reviews: Include reviews and ratings
        with_category: Include category details
        review_limit: Maximum reviews to include
        
    Returns:
        Product instance with requested relations or None
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[:review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()

@cache_page(60 * 30)  # Cache for 30 minutes
def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get featured products with optimized query
    
    Args:
        limit: Maximum number of products to return
        only_in_stock: Only include products with inventory
        min_rating: Minimum average rating
        fields: Specific fields to return (None for all)
        
    Returns:
        List of featured Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None and (min_rating < 0 or min_rating > 5):
        raise ValidationError("Rating must be between 0 and 5")

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
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('?')[:limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products within price range with inventory check
    
    Args:
        min_price: Minimum price threshold
        max_price: Maximum price threshold
        currency: Currency code for price comparison
        only_in_stock: Only include available products
        only_active: Only include active products
        limit: Maximum number of products to return
        
    Returns:
        List of matching Product instances
        
    Raises:
        ValidationError: For invalid parameters
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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('final_price'))

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories
    
    Args:
        category_id: Parent category ID
        include_subcategories: Include products from child categories
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        limit: Maximum products per category
        
    Returns:
        Dictionary with category names as keys and product lists as values
        
    Raises:
        ValidationError: For invalid category ID
    """
    validate_product_id(category_id)
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
    if limit:
        product_qs = product_qs[:limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured'))
    )
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }

@cache_page(60 * 60)  # Cache for 1 hour
def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product
    
    Args:
        product_id: Product to analyze
        
    Returns:
        Dictionary with:
        - average_rating
        - review_count
        - rating_distribution (1-5 stars)
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id'),
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with significant discounts
    
    Args:
        min_discount: Minimum discount percentage/amount
        only_active: Only include active products
        only_in_stock: Only include available products
        limit: Maximum number of products to return
        
    Returns:
        List of discounted Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        Q(discount_percent__gte=min_discount) |
        Q(discount_amount__amount__gte=min_discount),
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('-discount_percent'))


#========================================
# eleganza/products/selectors/review_selectors.py
#========================================

from django.db.models import Avg, Count, Q, F, Sum, FloatField
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from ..models import ProductReview, Product
from ..constants import Defaults

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_user_id(user_id: int) -> None:
    """Validate user ID parameter"""
    if user_id <= 0:
        raise ValidationError("User ID must be positive")

def validate_rating(rating: int) -> None:
    """Validate rating value"""
    if not (1 <= rating <= 5):
        raise ValidationError("Rating must be between 1 and 5")

@cache_page(60 * 15)  # Cache for 15 minutes
def get_product_reviews(
    product_id: int,
    *,
    only_approved: bool = True,
    min_rating: Optional[int] = None,
    recent_days: Optional[int] = None,
    include_user_info: bool = False,
    include_product_info: bool = False,
    limit: Optional[int] = None,
    order_by: str = '-created_at'
) -> List[ProductReview]:
    """
    Get filtered reviews for a product with optimized queries
    
    Args:
        product_id: Target product ID
        only_approved: Filter by approved status
        min_rating: Minimum rating to include (1-5)
        recent_days: Only reviews from last N days (1-365)
        include_user_info: Prefetch user data
        include_product_info: Prefetch product data
        limit: Maximum number of reviews to return
        order_by: Field to order by (prefix with '-' for descending)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if min_rating is not None:
        validate_rating(min_rating)
    if recent_days is not None and not (1 <= recent_days <= 365):
        raise ValidationError("Recent days must be between 1 and 365")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

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
    
    queryset = queryset.order_by(order_by)
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache_page(60 * 60)  # Cache for 1 hour
def get_review_stats(product_id: int) -> Dict[str, any]:
    """
    Get comprehensive review statistics for a product
    
    Args:
        product_id: Product to analyze
        
    Returns:
        Dictionary with:
        - average_rating (float)
        - review_count (int)
        - rating_distribution (dict {1-5: count})
        - helpful_percentage (float)
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        average_rating=Avg('rating'),
        review_count=Count('id'),
        helpful_votes=Sum('helpful_votes'),
        total_votes=Sum('helpful_votes') + Count('id'),  # Assuming all reviews get at least 1 view
        **{
            f'rating_{i}': Count('id', filter=Q(rating=i))
            for i in range(1, 6)
        }
    )
    
    return {
        'average_rating': round(stats['average_rating'] or 0, 1),
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'rating_{i}'] for i in range(1, 6)
        },
        'helpful_percentage': (
            (stats['helpful_votes'] / stats['total_votes'] * 100 
            if stats['total_votes'] else 0)
        )
    }

@cache_page(60 * 30)  # Cache for 30 minutes
def get_recent_reviews(
    *,
    limit: int = 5,
    min_rating: Optional[int] = None,
    with_product_info: bool = False,
    with_user_info: bool = False,
    days_back: Optional[int] = 30
) -> List[ProductReview]:
    """
    Get most recent reviews across all products
    
    Args:
        limit: Number of reviews to return (1-100)
        min_rating: Minimum rating to include (1-5)
        with_product_info: Prefetch product data
        with_user_info: Prefetch user data
        days_back: Only include reviews from last N days (1-365)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if not (1 <= limit <= 100):
        raise ValidationError("Limit must be between 1 and 100")
    if min_rating is not None:
        validate_rating(min_rating)
    if days_back is not None and not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")

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
    
    return list(queryset.order_by('-created_at')[:limit])

def get_user_reviews(
    user_id: int,
    *,
    only_approved: bool = True,
    with_product_info: bool = False,
    limit: Optional[int] = None,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get all reviews by a specific user
    
    Args:
        user_id: Target user ID
        only_approved: Filter by approval status
        with_product_info: Prefetch product data
        limit: Maximum reviews to return
        min_rating: Minimum rating to include (1-5)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_user_id(user_id)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(user_id=user_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    queryset = queryset.order_by('-created_at')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache_page(60 * 60)  # Cache for 1 hour
def get_most_helpful_reviews(
    product_id: int,
    *,
    limit: int = 3,
    min_helpful_votes: int = 5,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews with the most helpful votes
    
    Args:
        product_id: Target product ID
        limit: Number of reviews to return (1-20)
        min_helpful_votes: Minimum votes to qualify
        min_rating: Minimum rating to include (1-5)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if not (1 <= limit <= 20):
        raise ValidationError("Limit must be between 1 and 20")
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
    
    return list(queryset.order_by(
        '-helpful_votes',
        '-created_at'
    )[:limit])

@cache_page(60 * 60 * 4)  # Cache for 4 hours
def get_review_histogram(
    product_id: int,
    *,
    time_period: str = 'monthly',  # 'daily', 'weekly', 'monthly'
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get review count over time for trend analysis
    
    Args:
        product_id: Target product ID
        time_period: Grouping interval
        limit: Maximum periods to return
        
    Returns:
        List of dictionaries with:
        - period_start (date)
        - review_count (int)
        - average_rating (float)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if time_period not in ['daily', 'weekly', 'monthly']:
        raise ValidationError("Invalid time period")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    from django.db.models.functions import Trunc
    from django.db.models import DateField
    
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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache_page(60 * 60 * 12)  # Cache for 12 hours
def get_review_engagement_stats() -> Dict[str, any]:
    """
    Get store-wide review engagement metrics
    
    Returns:
        Dictionary with:
        - total_reviews
        - avg_rating
        - helpful_percentage
        - response_rate (if replies are tracked)
    """
    stats = ProductReview.objects.aggregate(
        total_reviews=Count('id'),
        avg_rating=Avg('rating'),
        helpful_percentage=Avg(
            F('helpful_votes') / (F('helpful_votes') + 1),  # +1 to avoid division by zero
            output_field=FloatField()
        ) * 100
    )
    
    # If you track admin responses:
    if hasattr(ProductReview, 'response_text'):
        stats['response_rate'] = ProductReview.objects.filter(
            response_text__isnull=False
        ).count() / stats['total_reviews'] * 100 if stats['total_reviews'] else 0
    
    return stats

def get_pending_reviews(
    *,
    limit: Optional[int] = None,
    days_old: Optional[int] = None,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews awaiting moderation
    
    Args:
        limit: Maximum number to return
        days_old: Only reviews older than N days
        min_rating: Minimum rating to include
        
    Returns:
        List of unapproved ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")
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
    
    queryset = queryset.order_by('created_at')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_review_summary_by_category(
    category_id: int,
    *,
    include_subcategories: bool = False
) -> Dict[str, Dict[str, float]]:
    """
    Get review statistics aggregated by product category
    
    Args:
        category_id: Root category ID
        include_subcategories: Include child categories
        
    Returns:
        Dictionary with category names as keys and review stats as values
    """
    from django.db.models import Subquery, OuterRef
    
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
            avg_rating=Avg('rating'),
            review_count=Count('id'),
            helpful_percentage=Avg(
                F('helpful_votes') / (F('helpful_votes') + 1),
                output_field=FloatField()
            ) * 100
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

from django.db.models import Prefetch, Q, F, Count, Subquery, OuterRef, FloatField
from typing import List, Dict, Optional, Sequence
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from django.db.models.functions import Coalesce, Cast
from ..models import ProductVariant, ProductOption, Inventory
from ..constants import FieldLengths, Defaults

def validate_variant_id(variant_id: int) -> None:
    """Validate variant ID parameter"""
    if variant_id <= 0:
        raise ValidationError("Variant ID must be positive")

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_option_ids(option_ids: List[int]) -> None:
    """Validate option IDs"""
    if not option_ids:
        raise ValidationError("Option IDs cannot be empty")
    if any(oid <= 0 for oid in option_ids):
        raise ValidationError("Option IDs must be positive")

def get_variants_for_product(
    product_id: int,
    *,
    only_active: bool = True,
    include_inventory: bool = True,
    include_options: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> List[ProductVariant]:
    """
    Get variants for a product with configurable related data
    
    Args:
        product_id: Parent product ID
        only_active: Filter inactive variants
        include_inventory: Prefetch inventory data
        include_options: Prefetch option/attribute data
        fields: Specific fields to return (None for all)
        limit: Maximum variants to return
        
    Returns:
        List of ProductVariant instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('-is_default', 'sku'))

def get_variant_with_full_details(
    variant_id: int,
    *,
    include_inventory_history: bool = False,
    history_days: int = 30
) -> Optional[Dict[str, any]]:
    """
    Get single variant with complete related data
    
    Args:
        variant_id: Target variant ID
        include_inventory_history: Include inventory movement data
        history_days: Days of history to include (1-365)
        
    Returns:
        Dictionary with variant details and related data or None
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    if not (1 <= history_days <= 365):
        raise ValidationError("History days must be between 1 and 365")

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
        product_slug=F('product__slug')
    ).values(
        'id',
        'sku',
        'is_default',
        'is_active',
        'price_modifier',
        'product_id',
        'product_name',
        'product_slug',
        'inventory__stock_quantity',
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
    limit: Optional[int] = None
) -> List[ProductVariant]:
    """
    Find variants matching specific option combinations
    
    Args:
        product_id: Parent product ID
        option_ids: List of ProductOption IDs
        only_in_stock: Filter to items with inventory
        only_active: Only include active variants
        limit: Maximum variants to return
        
    Returns:
        List of matching ProductVariant instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    validate_option_ids(option_ids)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache_page(60 * 30)  # Cache for 30 minutes
def get_default_variant(
    product_id: int,
    *,
    only_in_stock: bool = False
) -> Optional[ProductVariant]:
    """
    Get the default variant for a product
    
    Args:
        product_id: Parent product ID
        only_in_stock: Only return if variant has inventory
        
    Returns:
        Default ProductVariant or None
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)

    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        is_default=True
    ).select_related('inventory')
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    return queryset.first()

def get_variant_inventory_status(
    variant_id: int,
    *,
    include_historical: bool = False,
    historical_days: int = 30
) -> Dict[str, any]:
    """
    Get comprehensive inventory status for a variant
    
    Args:
        variant_id: Target variant ID
        include_historical: Include recent movement data
        historical_days: Days of history to include (1-365)
        
    Returns:
        Dictionary with:
        - variant_id
        - sku
        - current_stock
        - low_stock_threshold
        - last_restock
        - historical_changes (if requested)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    if not (1 <= historical_days <= 365):
        raise ValidationError("Historical days must be between 1 and 365")

    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'inventory'
    ).annotate(
        sku=F('sku')
    ).values(
        'id',
        'sku',
        'inventory__stock_quantity',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = {
        'variant_id': variant['id'],
        'sku': variant['sku'],
        'current_stock': variant['inventory__stock_quantity'],
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

@cache_page(60 * 60)  # Cache for 1 hour
def get_variants_with_low_stock(
    product_id: Optional[int] = None,
    *,
    threshold: Optional[int] = None,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants below stock threshold
    
    Args:
        product_id: Optional parent product filter
        threshold: Custom low stock threshold
        limit: Maximum results to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
        
    Raises:
        ValidationError: For invalid parameters
    """
    if product_id is not None:
        validate_product_id(product_id)
    if threshold is not None and threshold <= 0:
        raise ValidationError("Threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    queryset = ProductVariant.objects.filter(
        inventory__stock_quantity__lte=threshold,
        is_active=True
    ).select_related(
        'product',
        'inventory'
    )
    
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    
    queryset = queryset.annotate(
        product_name=F('product__name'),
        current_stock=F('inventory__stock_quantity'),
        threshold=F('inventory__low_stock_threshold')
    ).values(
        'id',
        'sku',
        'product_name',
        'current_stock',
        'threshold'
    ).order_by('current_stock')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache_page(60 * 60)  # Cache for 1 hour
def get_variant_price_range(product_id: int) -> Optional[Dict[str, float]]:
    """
    Get min/max pricing for a product's variants
    
    Args:
        product_id: Parent product ID
        
    Returns:
        Dictionary with:
        - min_price
        - max_price
        - currency
        or None if no variants
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)

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
    include_pricing: bool = True
) -> Dict[str, List[Dict[str, any]]]:
    """
    Group variants by attribute option
    
    Args:
        product_id: Parent product ID
        attribute_id: Target attribute ID
        only_in_stock: Filter to available variants
        only_active: Only include active variants
        include_pricing: Include price modifier in results
        
    Returns:
        Dictionary {option_value: [variant_data]}
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if attribute_id <= 0:
        raise ValidationError("Attribute ID must be positive")

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
        in_stock=Q(inventory__stock_quantity__gt=0)
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
            variant_data['price_modifier'] = {
                'amount': float(variant.price_modifier.amount),
                'currency': str(variant.price_modifier.currency)
            }
        
        result[value].append(variant_data)
    
    return result

def get_variant_availability(
    variant_ids: Sequence[int],
    *,
    threshold: Optional[int] = None
) -> Dict[int, Dict[str, any]]:
    """
    Get availability status for multiple variants
    
    Args:
        variant_ids: Sequence of variant IDs
        threshold: Custom low stock threshold
        
    Returns:
        Dictionary with variant IDs as keys and status info as values
    """
    if not variant_ids:
        return {}
    
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    variants = ProductVariant.objects.filter(
        id__in=variant_ids
    ).select_related('inventory').values(
        'id',
        'inventory__stock_quantity',
        'inventory__low_stock_threshold'
    )
    
    return {
        v['id']: {
            'in_stock': v['inventory__stock_quantity'] > 0,
            'low_stock': v['inventory__stock_quantity'] <= threshold,
            'stock_quantity': v['inventory__stock_quantity']
        }
        for v in variants
    }
