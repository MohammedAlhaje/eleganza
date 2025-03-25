# orders/signals.py
import logging
from django.db import transaction
from django.db.models.signals import (
    post_save,
    post_delete,
    pre_save
)
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import AuditLog
from .models import Order, OrderItem, Cart, CartItem,InventoryShortageError

logger = logging.getLogger(__name__)

# ======================
# ORDER-RELATED SIGNALS
# ======================

@receiver([post_save, post_delete], sender=OrderItem)
def handle_order_item_changes(sender, instance, **kwargs):
    """
    Update order total and validate inventory when items change
    Uses transaction.on_commit for data consistency
    """
    def _update_order():
        try:
            order = instance.order
            order.total_price = order.calculate_total()
            order.save(update_fields=['total_price'])
            logger.debug(f"Updated total for order {order.id}")
            
            # Validate inventory after update
            if order.status in [Order.Status.RESERVED, Order.Status.PENDING]:
                order.full_clean()
                
        except Order.DoesNotExist:
            logger.warning("Orphaned OrderItem detected", extra={
                'order_item_id': instance.id
            })
        except Exception as e:
            logger.error(f"Order update failed: {str(e)}", exc_info=True)
            raise

    if instance.order_id:  # Only if item is linked to an order
        transaction.on_commit(_update_order)

@receiver(pre_save, sender=Order)
def capture_order_state(sender, instance, **kwargs):
    """
    Store previous state for audit logging and validation
    Handles status transitions and field changes
    """
    if instance.pk:
        try:
            instance._pre_save_state = Order.objects.get(pk=instance.pk)
        except Order.DoesNotExist:
            instance._pre_save_state = None

@receiver(post_save, sender=Order)
def handle_order_audit_log(sender, instance, created, **kwargs):
    """
    Comprehensive audit logging for order lifecycle events
    Tracks status changes and financial updates
    """
    def _create_audit_entry():
        try:
            action = 'create' if created else 'update'
            changes = {}
            
            if hasattr(instance, '_pre_save_state'):
                original = instance._pre_save_state
                if original:
                    changes = {
                        'status': {
                            'from': original.status,
                            'to': instance.status
                        },
                        'total_price': {
                            'from': str(original.total_price),
                            'to': str(instance.total_price)
                        }
                    }

            AuditLog.objects.create(
                actor=instance.customer,
                action=action,
                model_name='Order',
                object_id=str(instance.id),
                metadata={
                    'status': instance.status,
                    'total_price': str(instance.total_price),
                    'currency': instance.currency,
                    'changes': changes,
                    'system_note': _("Automatic audit entry")
                }
            )
        except Exception as e:
            logger.error(f"Audit log failed: {str(e)}", exc_info=True)

    transaction.on_commit(_create_audit_entry)

@receiver(pre_save, sender=Order)
def validate_status_transitions(sender, instance, **kwargs):
    """
    Enforce status transition rules before saving
    Prevent invalid state machine transitions
    """
    if instance.pk and not created:
        original = Order.objects.get(pk=instance.pk)
        if original.status != instance.status:
            allowed = Order.STATUS_TRANSITIONS.get(original.status, [])
            if instance.status not in allowed:
                logger.error(f"Invalid status transition: {original.status} → {instance.status}")
                raise ValidationError(
                    _("Invalid status transition from %(from)s to %(to)s") % {
                        'from': original.status,
                        'to': instance.status
                    }
                )

# ======================
# CART-RELATED SIGNALS
# ======================

@receiver([post_save, post_delete], sender=CartItem)
def handle_cart_changes(sender, instance, **kwargs):
    """
    Update cart timestamps and validate inventory
    Handle both authenticated and anonymous carts
    """
    def _update_cart():
        try:
            # Update cart timestamp
            Cart.objects.filter(pk=instance.cart_id).update(updated_at=timezone.now())
            
            # Validate inventory stock
            instance.full_clean()
            
        except Cart.DoesNotExist:
            logger.warning("Cart not found for update", extra={
                'cart_item_id': instance.id
            })
        except Exception as e:
            logger.error(f"Cart update failed: {str(e)}", exc_info=True)

    transaction.on_commit(_update_cart)

@receiver(pre_save, sender=CartItem)
def validate_cart_item_stock(sender, instance, **kwargs):
    """
    Pre-save validation for cart items
    Ensure quantity doesn't exceed available stock
    """
    try:
        if instance.product.inventory.available_stock < instance.quantity:
            raise ValidationError(
                _("Only %(stock)s items available in stock") % {
                    'stock': instance.product.inventory.available_stock
                }
            )
    except Exception as e:
        logger.error(f"Cart item validation failed: {str(e)}")
        raise

# ======================
# INVENTORY MANAGEMENT
# ======================

@receiver(post_save, sender=Order)
def handle_inventory_updates(sender, instance, **kwargs):
    """
    Automate inventory operations based on order status
    Atomic stock reservation/release operations
    """
    def _execute_stock_operations():
        try:
            if instance.status == Order.Status.RESERVED:
                instance.reserve_stock()
                logger.info(f"Stock reserved for order {instance.id}")
                
            elif instance.status == Order.Status.CANCELLED:
                instance.release_stock()
                logger.info(f"Stock released for order {instance.id}")
                
        except InventoryShortageError as e:
            logger.critical(f"Inventory shortage: {str(e)}")
            instance.status = Order.Status.CANCELLED
            instance.save()
            raise
        except Exception as e:
            logger.error(f"Inventory operation failed: {str(e)}")
            raise

    transaction.on_commit(_execute_stock_operations)