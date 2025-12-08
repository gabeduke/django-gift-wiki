# Django Gift Wiki - Project Review

## ⚠️ UPDATE: Crest Generator Shelved Behind Feature Flag

The crest generator feature has been disabled by default and can be enabled by setting `CREST_GENERATOR_ENABLED=TRUE` environment variable.

## Overview

This is a Django-based gift wish list management application with family/organizational features. The project appears to be in active development with significant recent changes, particularly around a new `crest_generator` feature.

## Current State Summary

### ✅ What's Working

1. **Core Gift Management System**: Complete with users, wishlists, items, and suggestions
2. **Family Grouping**: Users belong to families and can share wishlists
3. **User Features**: 
   - User registration and authentication
   - Profile management
   - Wishlist creation and editing
   - Item purchase tracking
4. **Recent Additions**: New `crest_generator` app for generating family crests via OpenAI
5. **Deployment Ready**: Docker, Kubernetes manifests (StatefulSet), health checks

### ⚠️ Current Issues & Concerns

#### 1. **Critical: Missing Dependencies**
   - Django not installed locally (virtual environment not set up)
   - Python dependencies need to be installed from `requirements.txt`

#### 2. **Database Configuration**
   - Currently using SQLite (lines 138-140 in settings.py)
   - PostgreSQL configuration is commented out (lines 130-137)
   - Should configure proper database for deployment

#### 3. **Security Issues**
   - **DEBUG = True** in production settings (line 27)
   - Hardcoded secret key fallback (line 24)
   - No SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE flags

#### 4. **Incomplete Features**
   - `crest_generator` admin not registered
   - `wishlist_delete` view returns None (line 221 in gift/views.py)
   - TODO comment in `wishlist_edit.html` about dynamic population

#### 5. **Code Quality Issues**
   - Duplicate import in `crest_generator/utils.py` (lines 1-7 repeat)
   - Missing error handling in `crest_generator` views
   - Views lack documentation

#### 6. **Git Status**
   - Many files in staging area
   - Many modified but uncommitted files
   - Untracked files (new models.py, views.py, admin.py for crest_generator)
   - Migration `0002_alter_crest_generated_image.py` is untracked

#### 7. **Configuration Issues**
   - Entrypoint.sh references `/code/` directory but Dockerfile uses `/app/`
   - No .env file or example
   - Missing documentation (no README.md)

### 📁 Project Structure

```
django-gift-wiki/
├── crest_generator/     # NEW: Family crest generator (OpenAI integration)
│   ├── models.py        # Crest model
│   ├── views.py         # Views for create/detail
│   ├── forms.py         # Form for crest creation
│   ├── utils.py         # OpenAI integration
│   └── templates/       # HTML templates
├── gift/                # Core gift management app
│   ├── models.py        # WikiUser, Family, WishList, Item, Suggestion
│   ├── views.py         # Main application views
│   ├── forms.py         # Form classes
│   ├── management/      # Custom commands
│   ├── middleware/      # Health check middleware
│   └── templates/       # HTML templates
├── giftwiki/            # Project settings
│   ├── settings.py      # Django configuration
│   └── urls.py          # URL routing
├── deploy/              # Kubernetes deployment configs
│   └── base/            # Base manifests
├── Dockerfile
├── entrypoint.sh
├── Makefile
└── requirements.txt     # Python dependencies
```

### 🎯 Models

**Gift App:**
- `WikiUser` (extends AbstractUser) - Family name association
- `Family` - Group organization
- `WishList` - Owner, dependent (steward), family category
- `Item` - Wishlist items with purchase tracking
- `Suggestion` - Item suggestions with links/prices
- `ItemGroup`, `Category` - Organization features

**Crest Generator App:**
- `Crest` - User heraldic crest with shield color, symbol, motto, generated image

### 🔧 Dependencies

From `requirements.txt`:
- Django 5.1 (upgraded from 4.2.7 mentioned in comments)
- OpenAI SDK (for image generation)
- django-cors-headers
- django-debug-toolbar
- django-storages (S3 support)
- django-widget-tweaks
- gunicorn
- boto3/botocore (AWS)
- psycopg2 (PostgreSQL)
- Pillow (images)

### 🚀 Deployment Configuration

- **Docker**: Python 3.10-slim, production-ready
- **Kubernetes**: StatefulSet with health check endpoint
- **Storage**: S3 support configured
- **Entrypoint**: Auto-migrates, collects static files, creates superusers

### 📝 Recent Changes (Git)

From `git log`:
- Latest: "add dev deployment" (61ded05)
- Previous: "revert social auth" (583f3f2)
- Working on crest generator and user management features

**Current Modifications:**
- 18 files changed, 559 additions, 147 deletions
- Most changes in `crest_generator/` app
- Settings updates for app registration
- Deployment configuration updates

## Immediate Action Items

### Priority 1: Setup & Configuration
1. ✅ Install Python dependencies: `pip install -r requirements.txt` (or use Pipenv)
2. ✅ Create virtual environment
3. ✅ Run migrations: `python manage.py migrate`
4. ✅ Create .env file with required environment variables
5. ✅ Test locally: `python manage.py runserver`

### Priority 2: Security & Production Readiness
1. 🔴 Set DEBUG = False for production
2. 🔴 Use environment variables for SECRET_KEY
3. 🔴 Add security middleware settings (HTTPS, cookies)
4. 🔴 Register Crest model in admin
5. 🔴 Complete wishlist_delete implementation

### Priority 3: Code Quality
1. 🟡 Fix duplicate imports in utils.py
2. 🟡 Add error handling to crest generation
3. 🟡 Fix entrypoint.sh directory reference
4. 🟡 Add docstrings to views
5. 🟡 Create proper README.md

### Priority 4: Git Management
1. 🟢 Review and commit staged changes
2. 🟢 Decide on untracked files (migrations, models)
3. 🟢 Clean up if needed

## Recommendations

### Short Term
1. **Set up development environment** with virtual environment
2. **Test the crest_generator** functionality end-to-end
3. **Secure the application** for production use
4. **Complete the missing features** (wishlist_delete, etc.)
5. **Document the API and setup** in README.md

### Medium Term
1. **Add automated tests** for both apps
2. **Improve error handling** throughout the application
3. **Add logging** for crest generation and image uploads
4. **Enhance UI/UX** for crest generator
5. **Add admin interface** for better data management

### Long Term
1. **Consider adding API endpoints** (REST framework)
2. **Add image upload** for custom crests
3. **Implement caching** for frequently accessed data
4. **Add export features** (PDF wishlists, etc.)
5. **Mobile-responsive design** improvements

## Environment Variables Needed

Based on code inspection, these environment variables are required:
- `DJANGO_SECRET_KEY` - Django secret key
- `DJANGO_ALLOWED_ORIGINS` - CORS allowed origins
- `DJANGO_ALLOWED_HOSTS` - Allowed hosts
- `DATABASE_PATH` - Database location
- `USE_S3` - Boolean for S3 storage
- `AWS_ACCESS_KEY_ID` - If using S3
- `AWS_SECRET_ACCESS_KEY` - If using S3
- `AWS_STORAGE_BUCKET_NAME` - If using S3
- `OPENAI_API_KEY` - For crest generation
- `DJANGO_SUPERUSER_*` - Superuser creation (see createsuperusers.py)

## Next Steps

1. Review this document
2. Set up local development environment
3. Test current features
4. Decide on immediate priorities
5. Begin implementing fixes/improvements

