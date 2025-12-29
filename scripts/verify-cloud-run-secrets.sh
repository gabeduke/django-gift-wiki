#!/bin/bash
# Script to verify Cloud Secret Manager secrets are set up correctly for Cloud Run

PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No GCP project configured. Run 'gcloud config set project PROJECT_ID'"
    exit 1
fi

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Verifying Cloud Run secrets setup for project: $PROJECT_ID"
echo "Service Account: $SERVICE_ACCOUNT"
echo ""

REQUIRED_SECRETS=(
    "django-secret-key"
    "django-db-user"
    "django-db-password"
    "aws-access-key-id"
    "aws-secret-access-key"
)

ALL_GOOD=true

for secret in "${REQUIRED_SECRETS[@]}"; do
    echo -n "Checking $secret... "
    
    # Check if secret exists
    if ! gcloud secrets describe "$secret" &>/dev/null; then
        echo "❌ Secret does not exist"
        echo "   Create it with: make cloud-run-setup-secrets"
        ALL_GOOD=false
        continue
    fi
    
    # Check if service account has access
    if gcloud secrets get-iam-policy "$secret" 2>/dev/null | grep -q "$SERVICE_ACCOUNT"; then
        echo "✅ Secret exists and service account has access"
    else
        echo "⚠️  Secret exists but service account does NOT have access"
        echo "   Grant access with: make cloud-run-grant-secrets-access"
        ALL_GOOD=false
    fi
done

echo ""
if [ "$ALL_GOOD" = true ]; then
    echo "✅ All secrets are properly configured!"
    exit 0
else
    echo "❌ Some secrets need attention. See above for details."
    exit 1
fi
