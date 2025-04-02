#!/bin/bash

# Default to 'y' if no input is provided
read -p "Do you want to create a superuser with default values? (y/n): " default_superuser
default_superuser=${default_superuser:-y}  # Default to 'y' if no input

if [[ "$default_superuser" == "y" ]]; then
    echo "Creating superuser with default credentials..."
    DJANGO_SUPERUSER_USERNAME=admin \
    DJANGO_SUPERUSER_EMAIL=admin@example.com \
    DJANGO_SUPERUSER_PASSWORD=Admin123 \
    python manage.py createsuperuser --no-input
else
    echo "Creating superuser interactively..."
    python manage.py createsuperuser
fi
