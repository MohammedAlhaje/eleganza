# core/models.py
import uuid
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

class SoftDeleteQuerySet(models.QuerySet):
    """Custom QuerySet supporting soft delete operations"""
    def delete(self):
        """Soft delete - set deleted_at timestamp"""
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        """Permanent deletion"""
        return super().delete()

    def alive(self):
        """Return only non-deleted items"""
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        """Return only deleted items"""
        return self.filter(deleted_at__isnull=False)

class SoftDeleteManager(models.Manager):
    """Custom manager supporting soft delete filtering"""
    def __init__(self, *args, **kwargs):
        self.alive_only = kwargs.pop('alive_only', True)
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        if self.alive_only:
            return SoftDeleteQuerySet(self.model).filter(deleted_at__isnull=True)
        return SoftDeleteQuerySet(self.model)

    def hard_delete(self):
        """Bypass soft delete for manager operations"""
        return self.get_queryset().hard_delete()

class SoftDeleteModel(models.Model):
    """
    Abstract model providing soft delete functionality
    """
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Deleted At"),
        help_text=_("Timestamp when object was soft-deleted")
    )

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager(alive_only=False)

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['deleted_at'])
        ]

    def delete(self, using=None, keep_parents=False):
        """Soft delete implementation"""
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])

    def restore(self):
        """Restore a soft-deleted instance"""
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])

    def hard_delete(self):
        """Permanent deletion"""
        super().delete()

    @property
    def is_deleted(self):
        """Check if instance is soft-deleted"""
        return self.deleted_at is not None

class TimeStampedModel(models.Model):
    """
    Abstract model providing self-updating created_at and updated_at fields
    """
    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
        help_text=_("Timestamp of creation")
    )
    updated_at = models.DateTimeField(
        _("Updated At"),
        auto_now=True,
        help_text=_("Timestamp of last update")
    )

    class Meta:
        abstract = True
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['-updated_at']),
        ]

class UUIDModel(models.Model):
    """
    Abstract model providing UUID primary key
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID")
    )

    class Meta:
        abstract = True

class BaseModel(SoftDeleteModel, TimeStampedModel, UUIDModel):
    """
    Comprehensive base model combining:
    - Soft delete functionality
    - Timestamp tracking
    - UUID primary key
    """
    class Meta:
        abstract = True
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.__class__.__name__} {self.id}"

class SystemConfig(models.Model):
    """
    Centralized system configuration settings
    """
    key = models.CharField(
        _("Configuration Key"),
        max_length=255,
        unique=True
    )
    value = models.JSONField(
        _("Configuration Value"),
        blank=True,
        null=True
    )
    description = models.TextField(
        _("Description"),
        blank=True
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True
    )

    class Meta:
        verbose_name = _("System Configuration")
        verbose_name_plural = _("System Configurations")
        ordering = ['key']
        indexes = [
            models.Index(fields=['key', 'is_active']),
        ]

    def __str__(self):
        return f"{self.key} ({'active' if self.is_active else 'inactive'})"

class AuditLog(models.Model):
    """
    System-wide audit logging
    """
    ACTION_CHOICES = (
        ('create', _("Create")),
        ('update', _("Update")),
        ('delete', _("Delete")),
        ('soft_delete', _("Soft Delete")),
        ('restore', _("Restore")),
    )

    actor = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Actor")
    )
    action = models.CharField(
        _("Action"),
        max_length=20,
        choices=ACTION_CHOICES
    )
    model_name = models.CharField(
        _("Model Name"),
        max_length=255
    )
    object_id = models.CharField(
        _("Object ID"),
        max_length=255
    )
    timestamp = models.DateTimeField(
        _("Timestamp"),
        auto_now_add=True
    )
    metadata = models.JSONField(
        _("Metadata"),
        default=dict,
        blank=True
    )

    class Meta:
        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['model_name', 'object_id']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} on {self.model_name} #{self.object_id} by {self.actor}"