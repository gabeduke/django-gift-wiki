# Feature Flags Guide

## Overview

The Gift Wiki application uses a feature flag system to enable/disable functionality without code changes.

**NEW: Manage flags from the admin interface at `/admin/` - No server restart required!**

## Architecture

### Feature Flag Module
Location: `giftwiki/feature_flags.py`

This module provides:
- Centralized flag management
- Template context processor for frontend access
- Environment variable integration

### Current Feature Flags

1. **STEWARD_PROXY_ENABLED** - Enables dependent/proxy functionality
   - Controls: steward/proxy fields in wishlist creation
   - Default: `FALSE` (disabled)
   - Purpose: Simplify the UI by hiding confusing dependent/proxy fields

2. **CREST_GENERATOR_ENABLED** - Enables family crest generation
   - Controls: Crest generator app registration and URLs
   - Default: `FALSE` (disabled)
   - Purpose: Optional AI-generated family crests

## Usage

### Enable a Feature Flag

Add to your `.env` file:
```bash
STEWARD_PROXY_ENABLED=TRUE
CREST_GENERATOR_ENABLED=TRUE
```

### In Python Code

```python
from giftwiki.feature_flags import STEWARD_PROXY_ENABLED

if STEWARD_PROXY_ENABLED:
    # Show steward fields
    pass
```

### In Templates

Feature flags are available via context processor:

```html
{% if feature_flags.STEWARD_PROXY_ENABLED %}
    <!-- Show steward-specific UI -->
{% endif %}
```

## Adding New Feature Flags

1. Add flag definition to `giftwiki/feature_flags.py`:
   ```python
   MY_NEW_FEATURE = get_flag('MY_NEW_FEATURE', default=False)
   ```

2. Add to `FEATURE_FLAGS` dict for template access

3. Document in this file

4. Use in code/templates as needed

## Benefits

- ✅ Progressive rollout of features
- ✅ Easy A/B testing
- ✅ Configuration-driven functionality
- ✅ Safe rollback on issues
- ✅ Environment-specific features

