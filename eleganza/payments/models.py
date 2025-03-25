# payments/models.py
import uuid
import logging
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from eleganza.core.models import BaseModel
from djmoney.models.fields import MoneyField

logger = logging.getLogger(__name__)

class PaymentMethodType(models.TextChoices):
    """Defines HOW payments are made"""
    WALLET = 'wallet', _('Digital Wallet')
    CASH = 'cash', _('Cash Payment')

class TransactionType(models.TextChoices):
    """Defines WHAT financial action occurred"""
    DEPOSIT = 'deposit', _('Deposit')
    PAYMENT = 'payment', _('Payment')
    REFUND = 'refund', _('Refund')
    COMMISSION = 'commission', _('Commission')
    ADJUSTMENT = 'adjustment', _('Adjustment')

def generate_cash_id():
    """Generate unique cash transaction identifier"""
    return f"CASH-{uuid.uuid4().hex[:8].upper()}"

class Wallet(models.Model):
    """Stores user's financial balance and currency"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    
    balance = models.DecimalField(
        _("Balance"),
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    currency = models.CharField(
        _("Currency"),
        max_length=3,
        choices=settings.CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=0),
                name="non_negative_balance"
            )
        ]
        indexes = [
            models.Index(fields=['currency', 'balance']),
        ]

    def __str__(self):
        return f"{self.user}'s Wallet: {self.balance} {self.currency}"

class PaymentMethod(BaseModel):
    """Represents payment options available to users"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )
    
    method_type = models.CharField(
        _("Type"),
        max_length=20,
        choices=PaymentMethodType.choices
    )
    
    wallet = models.OneToOneField(
        Wallet,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    cash_identifier = models.CharField(
        _("Cash Transaction ID"),
        max_length=50,
        unique=True,
        editable=False,
        default=generate_cash_id,
        help_text=_("Automatically generated cash transaction reference"),
        db_index=True
    )
    
    cash_handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='handled_cash_payments',
        limit_choices_to={
            'type': 'TEAM_MEMBER',
            'is_active': True
        },
        help_text=_("Staff member who processed the cash payment"),
        db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'method_type'],
                name='unique_method_type_per_user'
            )
        ]
        indexes = [
            models.Index(fields=['method_type', 'user']),
            models.Index(fields=['cash_identifier']),
            models.Index(fields=['cash_handled_by', 'created_at']),
        ]

    def clean(self):
        """Enhanced validation"""
        super().clean()
        
        if self.method_type == PaymentMethodType.WALLET:
            if not self.wallet:
                raise ValidationError(_("Wallet method requires a linked wallet"))
            if self.wallet.user != self.user:
                raise ValidationError(_("Wallet does not belong to this user"))

    def __str__(self):
        return f"{self.get_method_type_display()} - {self.user}"

class Transaction(BaseModel):
    """Universal record for all financial activities"""
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    
    transaction_type = models.CharField(
        _("Type"),
        max_length=20,
        choices=TransactionType.choices
    )
    
    amount = MoneyField(
        _("Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    
    reference = models.UUIDField(
            _("Transaction ID"),
            default=uuid.uuid4,
            unique=True,
            editable=False
        )
    
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    
    related_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Linked transaction for refunds/reversals")
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_type', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['-created_at', 'payment_method']),
        ]

    def save(self, *args, **kwargs):
        """Validate amount sign based on transaction type"""
        if self.transaction_type == TransactionType.PAYMENT and self.amount.amount > 0:
            raise ValidationError(_("Payment amounts should be negative"))
        elif self.transaction_type in [TransactionType.DEPOSIT, TransactionType.COMMISSION] and self.amount.amount < 0:
            raise ValidationError(_("Deposit/commission amounts must be positive"))
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount}"

class Payment(BaseModel):
    """Core payment processing entity"""
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.PROTECT,
        related_name='payments'
    )
    
    method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    
    amount = MoneyField(
        _("Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=(
            ('pending', _('Pending')),
            ('completed', _('Completed')),
            ('failed', _('Failed')),
            ('refunded', _('Refunded')),
        ),
        default='pending'
    )

    class Meta:
        indexes = [
            models.Index(fields=['-created_at', 'status']),
        ]

    def clean(self):
        """Validate currency consistency"""
        super().clean()
        
        if self.method.method_type == PaymentMethodType.WALLET:
            if self.amount.currency != self.method.wallet.currency:
                raise ValidationError(
                    _("Payment currency must match wallet currency")
                )
            
        if self.amount.currency != self.order.total_price.currency:
            raise ValidationError(
                _("Payment currency must match order currency")
            )

    def process(self):
        """Execute payment with enhanced error handling"""
        try:
            if self.method.method_type == PaymentMethodType.WALLET:
                self._process_wallet_payment()
            else:
                self._process_cash_payment()
        except (ValidationError, IntegrityError) as e:
            logger.error(f"Payment {self.id} failed: {str(e)}")
            self.status = 'failed'
            self.save()
            raise e

    def _process_wallet_payment(self):
        """Atomic wallet transaction with row locking"""
        with transaction.atomic():
            # Lock the wallet row for update
            wallet = Wallet.objects.select_for_update().get(pk=self.method.wallet.pk)
            
            if wallet.balance >= self.amount.amount:
                wallet.balance -= Decimal(self.amount.amount)
                wallet.save()
                
                Transaction.objects.create(
                    payment_method=self.method,
                    transaction_type=TransactionType.PAYMENT,
                    amount=-self.amount,
                    order=self.order
                )
                
                self.status = 'completed'
                self.save()
                return
            
            self.status = 'failed'
            self.save()

    def _process_cash_payment(self):
        """Cash payment processing with audit tracking"""
        with transaction.atomic():
            Transaction.objects.create(
                payment_method=self.method,
                transaction_type=TransactionType.PAYMENT,
                amount=self.amount,
                order=self.order
            )
            self.status = 'completed'
            self.save()

    def __str__(self):
        return f"Payment {self.id} - {self.amount} ({self.status})"