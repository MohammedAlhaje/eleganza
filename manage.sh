#!/bin/bash

# Define the path to your scripts folder
SCRIPT_DIR="$(dirname "$0")/migration_scripts"

# Ensure the folder exists
if [ ! -d "$SCRIPT_DIR" ]; then
    echo "❌ Error: migration_scripts folder not found!"
    exit 1
fi

echo "============================"
echo " Django Migration Runner"
echo "============================"

# Ask to clear migrations
read -p "Do you want to clear migrations? (y/n): " clear_mig
clear_mig=${clear_mig:-y}  # Default to 'y' if no input
if [[ "$clear_mig" == "y" ]]; then
    bash "$SCRIPT_DIR/clear_migrations.sh"
fi

# Ask to flush the database
read -p "Do you want to flush the database? (y/n): " flush_db
flush_db=${flush_db:-y}  # Default to 'y' if no input
if [[ "$flush_db" == "y" ]]; then
    echo "⚠️ Flushing database..."
    python manage.py flush --no-input
fi

# Ask to make migrations
read -p "Do you want to make new migrations? (y/n): " make_mig
make_mig=${make_mig:-y}  # Default to 'y' if no input
if [[ "$make_mig" == "y" ]]; then
    echo "⚙️ Making new migrations..."
    python manage.py makemigrations
fi

# Ask to apply migrations
read -p "Do you want to migrate? (y/n): " migrate
migrate=${migrate:-y}  # Default to 'y' if no input
if [[ "$migrate" == "y" ]]; then
    echo "⚙️ Applying migrations..."
    python manage.py migrate
fi

# Ask to create a superuser
read -p "Do you want to create a superuser? (y/n): " create_super
create_super=${create_super:-y}  # Default to 'y' if no input
if [[ "$create_super" == "y" ]]; then
    bash "$SCRIPT_DIR/create_superuser.sh"
fi

echo "✅ All tasks completed!"
