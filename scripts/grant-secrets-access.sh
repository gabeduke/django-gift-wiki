#!/bin/bash
# Script to grant Cloud Run service account access to all secrets

PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No GCP project configured. Run 'gcloud config set project PROJECT_ID'"
    exit 1
fi

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Granting Cloud Run service account access to secrets..."
echo "Project: $PROJECT_ID"
echo "Service Account: $SERVICE_ACCOUNT"
echo ""

SECRETS=(
    "django-secret-key"
    "django-db-user"
    "django-db-password"
    "aws-access-key-id"
    "aws-secret-access-key"
)

for secret in "${SECRETS[@]}"; do
    echo "Granting access to $secret..."
    if gcloud secrets add-iam-policy-binding "$secret" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor" 2>/dev/null; then
        echo "  ✅ Access granted"
    else
        echo "  ⚠️  May already have access (or secret doesn't exist)"
    fi
done

echo ""
echo "✅ Done! Verify with: make cloud-run-verify-secrets"


