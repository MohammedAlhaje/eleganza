# Generated by Django 5.0.12 on 2025-03-24 23:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_initial'),
        ('products', '0003_product_is_active'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cartitem',
            name='product',
            field=models.ForeignKey(limit_choices_to=models.Q(('is_active', True), ('inventory__stock_quantity__gt', 0)), on_delete=django.db.models.deletion.CASCADE, to='products.product', verbose_name='Product'),
        ),
    ]
