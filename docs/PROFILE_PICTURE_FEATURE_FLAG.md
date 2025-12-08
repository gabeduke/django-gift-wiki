# Profile Picture Feature Flag

## Overview
Profile picture functionality has been moved behind a feature flag (`PROFILE_PICTURE_ENABLED`) and is **disabled by default**.

## Changes Made

1. **Added Feature Flag**: `PROFILE_PICTURE_ENABLED`
   - Can be enabled via environment variable: `PROFILE_PICTURE_ENABLED=TRUE`
   - Can be enabled via Django admin: Create a `FeatureFlag` with name `PROFILE_PICTURE_ENABLED` and set `enabled=True`

2. **Updated Profile View**: 
   - Only loads `ProfilePictureForm` if feature is enabled
   - Passes `PROFILE_PICTURE_ENABLED` to template context

3. **Updated Profile Template**:
   - Profile picture section only renders if `PROFILE_PICTURE_ENABLED` is True
   - Form is conditionally rendered

## Enabling Profile Pictures

### Option 1: Environment Variable
Add to your `.env` or deployment config:
```
PROFILE_PICTURE_ENABLED=TRUE
```

### Option 2: Django Admin
1. Go to `/admin/gift/featureflag/`
2. Click "Add Feature Flag"
3. Name: `PROFILE_PICTURE_ENABLED`
4. Enabled: ✓ (checked)
5. Save

## Troubleshooting Scraped Data

If you see "No gift lists available to import", check:

1. **Data Import Status**:
   ```bash
   # In Django shell or management command
   python manage.py shell
   >>> from gift.models import ScrapedWikiPage
   >>> ScrapedWikiPage.objects.count()
   ```
   Should return > 0 if data was imported.

2. **Check Migration Job Logs**:
   ```bash
   kubectl logs job/django-migrate
   ```
   Look for "Import complete!" message and check for errors.

3. **Manually Run Import** (if needed):
   ```bash
   kubectl exec -it <pod-name> -- python manage.py import_scraped_wiki /app/scraped_wiki_data.json
   ```

4. **Verify File Exists in Container**:
   ```bash
   kubectl exec -it <pod-name> -- ls -la /app/scraped_wiki_data.json
   ```

5. **Check Database**:
   - Go to `/admin/gift/scrapedwikipage/`
   - Should see list of scraped pages
   - Check `is_imported` status

## Next Steps

- Fix profile picture upload issues (media storage, permissions, etc.)
- Re-enable feature flag when ready
- Consider using S3 or other storage for profile pictures in production

