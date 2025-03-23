# orders/signals.py
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from .models import Order, OrderItem, Payment, ShoppingCart

@receiver(post_save, sender=OrderItem)
@receiver(post_delete, sender=OrderItem)
def update_order_total(sender, instance, **kwargs):
    """Update order total when items change"""
    with transaction.atomic():
        order = instance.order
        total = order.order_items.aggregate(
            total=Sum(F('quantity') * F('price'))
        )['total'] or 0
        order.total_amount = total
        order.save(update_fields=['total_amount'])

@receiver(pre_save, sender=Order)
def handle_order_status_change(sender, instance, **kwargs):
    """Handle stock management on order status changes"""
    if instance.pk:
        original = Order.objects.get(pk=instance.pk)
        
        # Order cancelled - release reserved stock
        if original.status != instance.status and instance.status == Order.Status.CANCELLED:
            for item in instance.order_items.all():
                item.product.reserved_stock -= item.quantity
                item.product.save()
        
        # Order confirmed - convert reserved stock to actual sold stock
        if original.status != instance.status and instance.status == Order.Status.CONFIRMED:
            for item in instance.order_items.all():
                product = item.product
                product.stock_quantity -= item.quantity
                product.reserved_stock -= item.quantity
                product.save()

@receiver(post_save, sender=Payment)
def update_order_payment_status(sender, instance, **kwargs):
    """Update order status when payment is completed"""
    if instance.status == Payment.Status.COMPLETED:
        order = instance.order
        if order.paid_amount >= order.total_amount:
            order.status = Order.Status.COMPLETED
            order.save(update_fields=['status'])

@receiver(post_save, sender=ShoppingCart)
def create_cart_for_new_user(sender, instance, created, **kwargs):
    """Automatically create shopping cart for new users"""
    if created and instance.customer.is_authenticated:
        ShoppingCart.objects.get_or_create(customer=instance.customer)