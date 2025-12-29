#!/bin/bash
# Script to create Cloud Secret Manager secrets for Cloud Run deployment
# Run this once to set up secrets, then they'll be used by cloudbuild.yaml

PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No GCP project configured. Run 'gcloud config set project PROJECT_ID'"
    exit 1
fi

echo "Setting up secrets for project: $PROJECT_ID"
echo ""

# Read secrets from deploy/dev/secrets.env
SECRETS_FILE="deploy/dev/secrets.env"
if [ ! -f "$SECRETS_FILE" ]; then
    echo "Error: $SECRETS_FILE not found"
    exit 1
fi

# Source the secrets file
source "$SECRETS_FILE"

# Create secrets (will update if they already exist)
echo "Creating/updating secrets in Cloud Secret Manager..."

echo -n "$DJANGO_SECRET_KEY" | gcloud secrets create django-secret-key --data-file=- --replication-policy="automatic" 2>/dev/null || \
    echo -n "$DJANGO_SECRET_KEY" | gcloud secrets versions add django-secret-key --data-file=-

echo -n "$DJANGO_DB_USER" | gcloud secrets create django-db-user --data-file=- --replication-policy="automatic" 2>/dev/null || \
    echo -n "$DJANGO_DB_USER" | gcloud secrets versions add django-db-user --data-file=-

echo -n "$DJANGO_DB_PASSWORD" | gcloud secrets create django-db-password --data-file=- --replication-policy="automatic" 2>/dev/null || \
    echo -n "$DJANGO_DB_PASSWORD" | gcloud secrets versions add django-db-password --data-file=-

echo -n "$AWS_ACCESS_KEY_ID" | gcloud secrets create aws-access-key-id --data-file=- --replication-policy="automatic" 2>/dev/null || \
    echo -n "$AWS_ACCESS_KEY_ID" | gcloud secrets versions add aws-access-key-id --data-file=-

echo -n "$AWS_SECRET_ACCESS_KEY" | gcloud secrets create aws-secret-access-key --data-file=- --replication-policy="automatic" 2>/dev/null || \
    echo -n "$AWS_SECRET_ACCESS_KEY" | gcloud secrets versions add aws-secret-access-key --data-file=-

echo ""
echo "✅ Secrets created/updated in Cloud Secret Manager"
echo ""
echo "Grant Cloud Run service account access to secrets:"
echo "  gcloud secrets add-iam-policy-binding django-secret-key --member='serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com' --role='roles/secretmanager.secretAccessor'"
echo ""
echo "Or grant access to the default compute service account:"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
echo "  gcloud secrets add-iam-policy-binding django-secret-key --member='serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com' --role='roles/secretmanager.secretAccessor'"
echo "  (repeat for each secret)"




