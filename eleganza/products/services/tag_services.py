# products/services/tag_services.py
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from .models import Tag, ProductTag

class TagService:
    """Services for managing tags (UC-T01, T02, T03)"""
    
    @classmethod
    @transaction.atomic
    def create_tag(cls, name: str, slug: str) -> Tag:
        """UC-T01: Create a new tag with duplicate validation"""
        if Tag.objects.filter(Q(name=name) | Q(slug=slug)).exists():
            raise ValidationError(_("The name or slug is already in use"))
        
        return Tag.objects.create(name=name, slug=slug)

    @classmethod
    @transaction.atomic
    def update_tag(cls, tag_id: int, **kwargs) -> Tag:
        """UC-T02: Update a tag with duplicate validation"""
        tag = Tag.objects.get(id=tag_id)
        
        # Validate duplicates for name and slug
        if 'name' in kwargs and Tag.objects.filter(name=kwargs['name']).exclude(id=tag_id).exists():
            raise ValidationError(_("The name is already in use"))
        if 'slug' in kwargs and Tag.objects.filter(slug=kwargs['slug']).exclude(id=tag_id).exists():
            raise ValidationError(_("The slug is already in use"))
        
        for field, value in kwargs.items():
            setattr(tag, field, value)
        tag.save()
        return tag

    @classmethod
    @transaction.atomic
    def delete_tag(cls, tag_id: int) -> None:
        """UC-T03: Delete a tag that is not linked to products"""
        tag = Tag.objects.get(id=tag_id)
        if tag.product_tags.exists():
            raise ValidationError(_("Cannot delete a tag linked to products"))
        tag.delete()

class ProductTagService:
    """Services for linking tags to products (UC-T04, T05)"""
    
    @classmethod
    @transaction.atomic
    def assign_tag(cls, product_id: int, tag_id: int) -> ProductTag:
        """UC-T04: Link a tag to a product with duplicate prevention"""
        if ProductTag.objects.filter(product_id=product_id, tag_id=tag_id).exists():
            raise ValidationError(_("The tag is already linked to the product"))
        
        return ProductTag.objects.create(product_id=product_id, tag_id=tag_id)

    @classmethod
    @transaction.atomic
    def remove_tag(cls, product_id: int, tag_id: int) -> None:
        """UC-T05: Remove a tag from a product"""
        ProductTag.objects.filter(product_id=product_id, tag_id=tag_id).delete()