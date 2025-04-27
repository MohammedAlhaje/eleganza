# products/selectors/tag_selectors.py
from django.db.models import Q
from .models import Tag, ProductTag, Product

class TagSelector:
    """Selectors for retrieving tag data"""
    
    @staticmethod
    def get_all_tags() -> list[Tag]:
        """Retrieve all tags ordered by name"""
        return Tag.objects.all().order_by("name")

    @staticmethod
    def search_tags(keyword: str) -> list[Tag]:
        """Search for tags by name or slug"""
        return Tag.objects.filter(
            Q(name__icontains=keyword) | 
            Q(slug__icontains=keyword)
        )

    @staticmethod
    def get_unused_tags() -> list[Tag]:
        """Retrieve tags not linked to any product"""
        return Tag.objects.filter(product_tags__isnull=True)

class ProductTagSelector:
    """Selectors for retrieving product-tag relationships"""
    
    @staticmethod
    def get_product_tags(product_id: int) -> list[Tag]:
        """Retrieve tags for a specific product"""
        return Tag.objects.filter(product_tags__product_id=product_id)

    @staticmethod
    def get_tagged_products(tag_id: int) -> list[Product]:
        """Retrieve products linked to a specific tag"""
        return Product.objects.filter(product_tags__tag_id=tag_id)