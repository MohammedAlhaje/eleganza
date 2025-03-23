# payment/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
from .models import Payment, Refund, Subscription
from django.db.models import Sum
from djmoney.money import Money

@receiver(pre_save, sender=Payment)
def payment_pre_save(sender, instance, **kwargs):
    """Payment validation and status handling"""
    if instance.pk:
        original = Payment.objects.get(pk=instance.pk)
        
        # Handle status transitions
        if original.status != instance.status:
            # Handle completed payments
            if instance.status == Payment.Status.COMPLETED:
                instance.order.status = 'confirmed'
                instance.order.save()
                
            # Handle refunds
            if instance.status in [Payment.Status.REFUNDED, Payment.Status.PARTIALLY_REFUNDED]:
                instance.order.status = 'refunded'
                instance.order.save()

@receiver(post_save, sender=Refund)
def handle_refund(sender, instance, created, **kwargs):
    """Update payment status on refund creation"""
    if created:
        with transaction.atomic():
            payment = instance.payment
            total_refunds = payment.refunds.aggregate(
                total=Sum('amount')
            )['total'] or Money(0, payment.amount.currency)
            
            if total_refunds >= payment.amount:
                payment.status = Payment.Status.REFUNDED
            else:
                payment.status = Payment.Status.PARTIALLY_REFUNDED
            payment.save()

@receiver(post_save, sender=Subscription)
def schedule_next_payment(sender, instance, created, **kwargs):
    """Schedule next billing date for subscriptions"""
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta
    
    if not created and instance.is_active:
        intervals = {
            'daily': relativedelta(days=1),
            'weekly': relativedelta(weeks=1),
            'monthly': relativedelta(months=1),
            'yearly': relativedelta(years=1)
        }
        instance.next_billing_date = timezone.now() + intervals[instance.interval]
        instance.save()