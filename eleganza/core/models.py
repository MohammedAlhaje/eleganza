# core/models/base.py
import uuid
from django.db import models
from django.utils import timezone

class SoftDeleteManager(models.Manager):
    """Custom manager to exclude soft-deleted objects"""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

class BaseModel(models.Model):
    """
    Abstract base model with common fields and soft delete functionality.
    
    Fields:
        id (UUID): Unique identifier (primary key)
        created_at (DateTime): Auto-set on creation
        updated_at (DateTime): Auto-updated on modification
        deleted_at (DateTime): Soft delete timestamp
    """
    
    id = models.UUIDField(
        default=uuid.uuid4,
        primary_key=True,
        editable=False,
        verbose_name="ID"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Deleted At"
    )

    # Managers
    objects = SoftDeleteManager()
    all_objects = models.Manager()  # Includes deleted items

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @property
    def is_deleted(self) -> bool:
        """Check if instance is soft-deleted"""
        return self.deleted_at is not None

    def delete(self, *args, **kwargs):
        """Soft delete implementation"""
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self, *args, **kwargs):
        """Permanent delete"""
        super().delete(*args, **kwargs)

    def restore(self):
        """Restore soft-deleted instance"""
        self.deleted_at = None
        self.save()

    def __str__(self) -> str:
        return f"{self.__class__.__name__} - {self.id}"