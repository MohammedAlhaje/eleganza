# Generated by Django 5.0.12 on 2025-03-24 22:45

import django.db.models.deletion
import django.utils.timezone
import django_countries.fields
import eleganza.users.models
import eleganza.users.validators
import imagekit.models.fields
import phonenumber_field.modelfields
import timezone_field.fields
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, help_text='Timestamp when object was soft-deleted', null=True, verbose_name='Deleted At')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='Timestamp of creation', verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='Timestamp of last update', verbose_name='Updated At')),
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, help_text='Public user identifier for API interactions', unique=True)),
                ('username', models.CharField(blank=True, default=None, help_text='Optional. 150 characters or fewer. Letters, digits, spaces, and @/./+/-/_ only.', max_length=150, null=True, unique=True, validators=[eleganza.users.models.SpaceAllowedUsernameValidator()], verbose_name='username')),
                ('email', models.EmailField(help_text='Verified contact email address', max_length=254, unique=True, verbose_name='email address')),
                ('display_name', models.CharField(blank=True, help_text='Public facing name (optional)', max_length=150, verbose_name='display name')),
                ('type', models.CharField(choices=[('CUSTOMER', 'Customer'), ('TEAM_MEMBER', 'Team Member')], db_index=True, default='CUSTOMER', max_length=20, verbose_name='User Type')),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
        ),
        migrations.CreateModel(
            name='Address',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('street', models.CharField(help_text='Building number and street name', max_length=255, verbose_name='Street Address')),
                ('city', models.CharField(db_index=True, max_length=100, verbose_name='City')),
                ('postal_code', models.CharField(blank=True, max_length=20, verbose_name='Postal Code')),
                ('country', django_countries.fields.CountryField(default='LY', max_length=2, verbose_name='Country')),
                ('is_primary', models.BooleanField(db_index=True, default=False, verbose_name='Primary Address')),
                ('user', models.ForeignKey(limit_choices_to={'type': 'CUSTOMER'}, on_delete=django.db.models.deletion.CASCADE, related_name='addresses', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Address',
                'verbose_name_plural': 'Addresses',
                'ordering': ['-is_primary', 'city'],
            },
        ),
        migrations.CreateModel(
            name='CustomerProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', phonenumber_field.modelfields.PhoneNumberField(blank=True, help_text='International format (+CountryCode...)', max_length=128, null=True, region=None, verbose_name='Phone Number')),
                ('timezone', timezone_field.fields.TimeZoneField(default='UTC', help_text="User's preferred timezone", verbose_name='Timezone')),
                ('language', models.CharField(choices=[('ar', 'Arabic'), ('en', 'English')], default='en-us', help_text='Interface language preference', max_length=10, verbose_name='Language')),
                ('avatar', imagekit.models.fields.ProcessedImageField(blank=True, help_text='User profile image (WEBP format)', null=True, upload_to=eleganza.users.validators.avatar_path, validators=[eleganza.users.validators.AvatarValidator()], verbose_name='Avatar')),
                ('loyalty_points', models.PositiveIntegerField(db_index=True, default=0, verbose_name='Loyalty Points')),
                ('newsletter_subscribed', models.BooleanField(default=True, verbose_name='Newsletter Subscribed')),
                ('preferred_contact_method', models.CharField(blank=True, max_length=50, null=True, verbose_name='Preferred Contact Method')),
                ('default_currency', models.CharField(choices=[('LYD', 'Libyan Dinar')], default='LYD', max_length=3, verbose_name='Default Currency')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_profile', to=settings.AUTH_USER_MODEL, verbose_name='System User')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='PasswordHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(help_text='Hashed password value', max_length=255, verbose_name='Password Hash')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='password_history', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Password History',
                'verbose_name_plural': 'Password Histories',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TeamMemberProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', phonenumber_field.modelfields.PhoneNumberField(blank=True, help_text='International format (+CountryCode...)', max_length=128, null=True, region=None, verbose_name='Phone Number')),
                ('timezone', timezone_field.fields.TimeZoneField(default='UTC', help_text="User's preferred timezone", verbose_name='Timezone')),
                ('language', models.CharField(choices=[('ar', 'Arabic'), ('en', 'English')], default='en-us', help_text='Interface language preference', max_length=10, verbose_name='Language')),
                ('avatar', imagekit.models.fields.ProcessedImageField(blank=True, help_text='User profile image (WEBP format)', null=True, upload_to=eleganza.users.validators.avatar_path, validators=[eleganza.users.validators.AvatarValidator()], verbose_name='Avatar')),
                ('department', models.CharField(choices=[('sales', 'Sales'), ('support', 'Support'), ('management', 'Management')], db_index=True, max_length=50, verbose_name='Department')),
                ('can_approve_orders', models.BooleanField(default=False, verbose_name='Can Approve Orders')),
                ('default_currency', models.CharField(choices=[('LYD', 'Libyan Dinar')], default='LYD', max_length=3, verbose_name='Default Currency')),
                ('profit_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='Profit Percentage')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_profile', to=settings.AUTH_USER_MODEL, verbose_name='System User')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(condition=models.Q(('username__isnull', False)), fields=('username',), name='unique_non_empty_username'),
        ),
        migrations.AddConstraint(
            model_name='address',
            constraint=models.UniqueConstraint(fields=('user', 'street', 'city', 'postal_code'), name='unique_user_address'),
        ),
    ]
