# Testing Scraped Page Selection

## Overview
This document explains how to test the scraped page selection feature, especially for users who have already logged in or selected a page.

## Methods to Test

### 1. Management Command (Recommended)
Reset a user's selection using the management command:

```bash
# Reset selection for a specific user
python manage.py reset_scraped_selection <username>

# Reset selection for all users
python manage.py reset_scraped_selection --all
```

This will:
- Set `scraped_page_selected = False` for the user(s)
- Clear `selected_scraped_page` 
- Mark the scraped page as `is_imported = False` so it's available again

### 2. URL Parameter (Quick Test)
Add `?reset=1` to the selection URL to allow re-selection:

```
/select-scraped-page/?reset=1
```

This bypasses the check that prevents users who have already selected a page from accessing the form.

### 3. Django Admin
1. Go to `/admin/gift/scrapedwikipage/`
2. Select one or more scraped pages
3. Choose "Reset import status (for testing)" from the Actions dropdown
4. Click "Go"

This will:
- Reset `is_imported = False` for selected pages
- Clear `imported_by = None`
- Reset all users who had selected those pages

### 4. Direct Database/Admin Edit
1. Go to `/admin/gift/wikiuser/`
2. Find the user you want to test with
3. Edit the user and:
   - Uncheck "Scraped page selected"
   - Clear "Selected scraped page"
4. Save

## Workflow for Testing

1. **Import scraped data** (if not already done):
   ```bash
   python manage.py migrate
   python manage.py import_scraped_wiki scraped_wiki_data.json
   ```

2. **Reset a test user**:
   ```bash
   python manage.py reset_scraped_selection <test_username>
   ```

3. **Log in as that user** and navigate to:
   - `/select-scraped-page/` (should show the selection form)
   - Or `/` (home page should show a prompt if they haven't selected)

4. **Select a scraped page** and verify:
   - A new wishlist is created
   - Items are imported correctly
   - User is redirected to the wishlist detail page

5. **Test re-selection** (if needed):
   - Use `?reset=1` parameter or reset the user again
   - Verify the old page becomes available again

## Notes

- When a user selects a page, it's marked as `is_imported = True` and won't appear in the selection form for other users
- Resetting a user's selection makes the page available again
- Each import creates a NEW wishlist (doesn't merge with existing ones)
- The imported wishlist is named "{Page Title} (Imported)"

