#!/bin/bash
cd "$(dirname "$0")/.." || exit  # Move to project root

APPS=(
    "eleganza/core"
    "eleganza/users"
    "eleganza/products"
    "eleganza/orders"
    "eleganza/payments"
)

for app in "${APPS[@]}"; do
    echo "➡️ Processing: $app"

    # Show what's being deleted
    echo "Migration files to delete:"
    find "$app/migrations" -name "*.py" -not -name "__init__.py" -print
    find "$app/migrations" -name "*.pyc" -print

    # Actual deletion
    find "$app/migrations" -name "*.py" -not -name "__init__.py" -delete
    find "$app/migrations" -name "*.pyc" -delete

    echo "🗑️ Pycache cleanup:"
    find "$app" -type d -name "__pycache__" -print -exec rm -rf {} +
    echo "----------------------------------------"
done
