# Generated by Django 5.0.12 on 2025-03-24 22:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Designates whether this product should be treated as active.', verbose_name='Active'),
        ),
    ]
