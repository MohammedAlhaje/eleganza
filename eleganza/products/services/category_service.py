from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q  # Import Q for query filtering
from .models import ProductCategory

@transaction.atomic
def create_category(
    name: str,
    slug: str,
    parent_id: int = None,
    description: str = "",
    featured_image=None
) -> ProductCategory:
    """UC-PC01: Create a new category with constraint validation"""
    # Check for duplicates
    if ProductCategory.objects.filter(Q(name=name) | Q(slug=slug)).exists():
        raise ValidationError("The name or slug is already in use")
    
    category = ProductCategory(
        name=name,
        slug=slug,
        parent_id=parent_id,
        description=description,
        featured_image=featured_image
    )
    
    category.full_clean()
    category.save()
    return category

@transaction.atomic
def update_category(category_id: int, **kwargs) -> ProductCategory:
    """UC-PC02: Update category details"""
    category = ProductCategory.objects.get(id=category_id)
    
    # Check for duplicates
    if 'name' in kwargs and ProductCategory.objects.exclude(id=category_id).filter(name=kwargs['name']).exists():
        raise ValidationError("The name is already in use")
    
    if 'slug' in kwargs and ProductCategory.objects.exclude(id=category_id).filter(slug=kwargs['slug']).exists():
        raise ValidationError("The slug is already in use")
    
    # Update fields
    for field, value in kwargs.items():
        setattr(category, field, value)
    
    category.full_clean()
    category.save()
    return category

@transaction.atomic
def deactivate_category(category_id: int) -> ProductCategory:
    """UC-PC03: Deactivate a category"""
    category = ProductCategory.objects.get(id=category_id)
    
    if category.children.exists():
        raise ValidationError("Cannot deactivate a category that has subcategories")
    
    category.is_active = False
    category.save()
    return category

@transaction.atomic
def delete_category(category_id: int) -> None:
    """UC-PC04: Delete a category"""
    category = ProductCategory.objects.get(id=category_id)
    
    if category.products.exists() or category.children.exists():
        raise ValidationError("Cannot delete a category associated with products or subcategories")
    
    category.delete()