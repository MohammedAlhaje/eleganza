# payments/signals.py
import logging
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Wallet, PaymentMethod, Payment, Transaction,PaymentMethodType,TransactionType
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)
User = get_user_model()

@receiver(post_save, sender=User)
def create_user_payment_profile(sender, instance, created, **kwargs):
    """
    Creates payment profile for new users:
    - Wallet for all users
    - Default wallet payment method for customers
    """
    if created:
        try:
            with transaction.atomic():
                # Create wallet for every user
                wallet, w_created = Wallet.objects.get_or_create(user=instance)
                
                # Create default wallet payment method for customers
                if instance.type == User.Types.CUSTOMER:
                    PaymentMethod.objects.get_or_create(
                        user=instance,
                        method_type=PaymentMethodType.WALLET,
                        defaults={'wallet': wallet}
                    )
                    logger.info(f"Created wallet payment method for {instance.email}")
                    
        except Exception as e:
            logger.error(f"Failed creating payment profile for {instance.email}: {str(e)}")
            raise

@receiver(pre_save, sender=Payment)
def create_refund_transaction(sender, instance, **kwargs):
    """
    Creates refund transaction when payment status changes to refunded
    """
    if not instance.pk:
        return  # New payment being created

    try:
        original = Payment.objects.get(pk=instance.pk)
        if original.status != 'refunded' and instance.status == 'refunded':
            with transaction.atomic():
                # Find original payment transaction
                original_tx = instance.transactions.filter(
                    transaction_type=TransactionType.PAYMENT
                ).first()
                
                if original_tx:
                    # Create refund transaction
                    Transaction.objects.create(
                        payment_method=instance.method,
                        transaction_type=TransactionType.REFUND,
                        amount=abs(original_tx.amount),  # Make positive
                        order=instance.order,
                        related_transaction=original_tx
                    )
                    logger.info(f"Created refund transaction for payment {instance.id}")
                
                # Update wallet balance if wallet payment
                if instance.method.method_type == PaymentMethodType.WALLET:
                    wallet = instance.method.wallet
                    wallet.balance += abs(instance.amount.amount)
                    wallet.save()
                    
    except Payment.DoesNotExist:
        logger.warning("Payment instance missing during refund processing")
    except Exception as e:
        logger.error(f"Failed processing refund for payment {instance.id}: {str(e)}")
        raise

@receiver(post_save, sender=PaymentMethod)
def validate_payment_method(sender, instance, **kwargs):
    """
    Post-save validation for payment method consistency
    """
    try:
        instance.full_clean()
    except ValidationError as e:
        logger.error(f"Invalid payment method {instance.id}: {str(e)}")
        raise

@receiver(pre_save, sender=Wallet)
def track_balance_changes(sender, instance, **kwargs):
    """
    Logs significant balance changes and prevents invalid updates
    """
    if not instance.pk:
        return

    try:
        original = Wallet.objects.get(pk=instance.pk)
        if original.balance != instance.balance:
            logger.info(
                f"Wallet {instance.id} balance changed from "
                f"{original.balance} to {instance.balance}"
            )
            
            # Prevent direct balance manipulation outside transactions
            if not Transaction.objects.filter(wallet=instance).exists():
                logger.warning("Direct wallet balance modification detected!")
                raise ValidationError(
                    _("Wallet balance must be modified through transactions")
                )
                
    except Wallet.DoesNotExist:
        logger.warning("Wallet instance missing during balance change tracking")