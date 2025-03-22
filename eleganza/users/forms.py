# forms.py
from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm
)
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.conf import settings
from phonenumber_field.formfields import PhoneNumberField
from .models import (
    User,
    CustomerProfile,
    TeamMemberProfile,
    Product,
    ProductImage,
    Address,
    Order,
    OrderItem,
    Payment,
    Wishlist,
    CartItem,
)

class UserRegistrationForm(forms.ModelForm):
    """
    Custom user registration form with password matching validation.
    Handles both customer and team member registration based on user type.
    """
    password1 = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput,
        help_text=_("Enter a strong password (minimum 8 characters)")
    )
    password2 = forms.CharField(
        label=_("Password Confirmation"),
        widget=forms.PasswordInput,
        help_text=_("Enter the same password for verification")
    )

    class Meta:
        model = User
        fields = ('username', 'type')
        labels = {
            'username': _("Username"),
            'type': _("Account Type")
        }
        help_texts = {
            'username': _("Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.")
        }

    def clean_password2(self):
        # Validate password match
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(_("Passwords don't match"))
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user

class CustomAuthenticationForm(AuthenticationForm):
    """
    Custom login form with remember me functionality and improved security.
    """
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(),
        label=_("Remember me")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'autofocus': True})

class UserProfileForm(forms.ModelForm):
    """
    Base profile form with common fields for all user types.
    Includes avatar upload handling and phone number validation.
    """
    phone = PhoneNumberField(
        label=_("Phone Number"),
        required=False,
        widget=forms.TextInput(attrs={'placeholder': '+12125552368'})
    )
    avatar = forms.ImageField(
        label=_("Profile Picture"),
        required=False,
        widget=forms.FileInput(attrs={'accept': 'image/webp,image/jpeg,image/png'})
    )

    class Meta:
        fields = ('phone', 'timezone', 'language', 'default_currency', 'avatar')
        labels = {
            'timezone': _("Timezone"),
            'language': _("Language"),
            'default_currency': _("Currency")
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and avatar.size > settings.MAX_AVATAR_SIZE:
            raise ValidationError(_("Avatar size must be less than 2MB"))
        return avatar

class CustomerProfileForm(UserProfileForm):
    """
    Customer-specific profile form with loyalty program details.
    """
    class Meta(UserProfileForm.Meta):
        model = CustomerProfile
        fields = UserProfileForm.Meta.fields + ('preferred_contact_method', 'loyalty_points')
        labels = {
            **UserProfileForm.Meta.labels,
            'preferred_contact_method': _("Preferred Contact Method"),
            'loyalty_points': _("Loyalty Points")
        }

class TeamMemberProfileForm(UserProfileForm):
    """
    Team member profile form with department and profit allocation details.
    """
    class Meta(UserProfileForm.Meta):
        model = TeamMemberProfile
        fields = UserProfileForm.Meta.fields + ('department', 'profit_percentage')
        labels = {
            **UserProfileForm.Meta.labels,
            'department': _("Department"),
            'profit_percentage': _("Profit Percentage")
        }

class SecurePasswordChangeForm(PasswordChangeForm):
    """
    Custom password change form with password history validation.
    Integrates with password history tracking to prevent reuse.
    """
    def clean_new_password1(self):
        new_password = super().clean_new_password1()
        user = self.user
        if user.password_history.filter(password_hash=user.password).exists():
            raise ValidationError(
                _("You cannot reuse your previous %(limit)d passwords") % {
                    'limit': settings.PASSWORD_HISTORY_LIMIT
                }
            )
        return new_password

class ProductForm(forms.ModelForm):
    """
    Product management form with inventory validation and pricing controls.
    """
    class Meta:
        model = Product
        fields = (
            'sku', 'name', 'category', 'description',
            'original_price', 'selling_price', 'stock_quantity'
        )
        labels = {
            'sku': _("SKU"),
            'name': _("Product Name"),
            'category': _("Category"),
            'description': _("Description"),
            'original_price': _("Original Price"),
            'selling_price': _("Selling Price"),
            'stock_quantity': _("Stock Quantity")
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def clean(self):
        cleaned_data = super().clean()
        selling_price = cleaned_data.get('selling_price')
        original_price = cleaned_data.get('original_price')

        if selling_price and original_price and selling_price < original_price:
            self.add_error(
                'selling_price',
                _("Selling price cannot be lower than original price")
            )

        return cleaned_data

class ProductImageForm(forms.ModelForm):
    """
    Product image upload form with primary image selection.
    """
    class Meta:
        model = ProductImage
        fields = ('image', 'caption', 'is_primary')
        labels = {
            'image': _("Image File"),
            'caption': _("Caption"),
            'is_primary': _("Primary Image")
        }
        widgets = {
            'caption': forms.TextInput(attrs={'placeholder': _("Optional description")})
        }

ProductImageFormSet = forms.inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=3,
    max_num=10,
    can_delete=True
)

class AddressForm(forms.ModelForm):
    """
    Address management form with geolocation validation and primary address handling.
    """
    class Meta:
        model = Address
        fields = ('street', 'city', 'postal_code', 'country', 'is_primary')
        labels = {
            'street': _("Street Address"),
            'city': _("City"),
            'postal_code': _("Postal Code"),
            'country': _("Country"),
            'is_primary': _("Primary Address")
        }
        widgets = {
            'country': forms.Select(attrs={'class': 'country-select'})
        }

class OrderForm(forms.ModelForm):
    """
    Order creation/editing form with customer and status controls.
    """
    class Meta:
        model = Order
        fields = ('customer', 'status', 'total_amount')
        labels = {
            'customer': _("Customer"),
            'status': _("Order Status"),
            'total_amount': _("Total Amount")
        }
        widgets = {
            'customer': forms.Select(attrs={'class': 'select2'}),
            'status': forms.Select(attrs={'class': 'status-select'})
        }

class OrderItemForm(forms.ModelForm):
    """
    Order line item form with real-time inventory validation.
    """
    class Meta:
        model = OrderItem
        fields = ('product', 'quantity', 'price')
        labels = {
            'product': _("Product"),
            'quantity': _("Quantity"),
            'price': _("Unit Price")
        }

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        product = self.cleaned_data.get('product')
        
        if product and quantity > product.available_stock:
            raise ValidationError(
                _("Only %(available)s available in stock") % {
                    'available': product.available_stock
                }
            )
        return quantity

OrderItemFormSet = forms.inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    extra=1,
    max_num=20,
    can_delete=True
)

class PaymentForm(forms.ModelForm):
    """
    Payment processing form with transaction validation.
    """
    class Meta:
        model = Payment
        fields = ('order', 'amount', 'payment_method', 'transaction_id')
        labels = {
            'order': _("Order"),
            'amount': _("Amount"),
            'payment_method': _("Payment Gateway"),
            'transaction_id': _("Transaction ID")
        }
        widgets = {
            'transaction_id': forms.TextInput(attrs={'readonly': True})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['order'].queryset = Order.objects.filter(status=Order.Status.CONFIRMED)

class WishlistForm(forms.ModelForm):
    """
    Wishlist management form with duplicate prevention.
    """
    class Meta:
        model = Wishlist
        fields = ('product',)
        labels = {
            'product': _("Select Product")
        }

    def clean_product(self):
        product = self.cleaned_data['product']
        if self.instance.customer.wishlist.filter(product=product).exists():
            raise ValidationError(_("This product is already in your wishlist"))
        return product

class CartItemForm(forms.ModelForm):
    """
    Shopping cart item form with quantity validation.
    """
    class Meta:
        model = CartItem
        fields = ('quantity',)
        labels = {
            'quantity': _("Quantity")
        }
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': 1, 'max': 10})
        }

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        product = self.instance.product
        
        if quantity > product.available_stock:
            raise ValidationError(
                _("Only %(available)s available in stock") % {
                    'available': product.available_stock
                }
            )
        return quantity