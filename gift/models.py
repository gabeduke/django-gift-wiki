import logging

from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class WikiUser(AbstractUser):
    family_name = models.ForeignKey(
        'Family', on_delete=models.SET_NULL, null=True, blank=True, related_name='WikiUsers'
    )
    birthday = models.DateField(
        null=True, blank=True, help_text="User's birthday for organizing wishlists by season."
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
        help_text='Profile picture (will be automatically resized)',
    )
    profile_picture_thumbnail = models.ImageField(
        upload_to='profile_pictures/thumbnails/',
        blank=True,
        null=True,
        help_text='Thumbnail version (150x150)',
    )
    secret_santa_target = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='secret_santa_of',
        help_text="The person this user drew for the Christmas exchange."
    )
    profile_picture_web = models.ImageField(
        upload_to='profile_pictures/web/', blank=True, null=True, help_text='Web version (400x400)'
    )

    @property
    def is_kid(self):
        from datetime import date
        if not self.birthday:
            return False
        today = date.today()
        age = today.year - self.birthday.year - ((today.month, today.day) < (self.birthday.month, self.birthday.day))
        return age < 18

    scraped_page_selected = models.BooleanField(
        default=False, help_text='Whether user has selected a scraped wiki page to import'
    )
    selected_scraped_page = models.ForeignKey(
        'ScrapedWikiPage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='selected_by_users',
        help_text='The scraped wiki page this user selected to import',
    )
    COLOR_PALETTE_CHOICES = [
        ('default', 'Default (Indigo/Purple)'),
        ('ocean', 'Ocean (Blue/Teal)'),
        ('forest', 'Forest (Green/Emerald)'),
        ('sunset', 'Sunset (Orange/Pink)'),
        ('midnight', 'Midnight (Dark Blue/Navy)'),
        ('rose', 'Rose (Pink/Rose)'),
    ]
    color_palette = models.CharField(
        max_length=20,
        choices=COLOR_PALETTE_CHOICES,
        default='default',
        help_text='Color palette theme for the interface',
    )

    def __str__(self):
        return self.username

    def get_profile_picture_url(self):
        """Safely get profile picture URL, returning None if file doesn't exist."""
        if not self.profile_picture:
            return None
        try:
            # Check if file exists
            import os

            from django.conf import settings

            if hasattr(self.profile_picture, 'name'):
                file_path = os.path.join(settings.MEDIA_ROOT, self.profile_picture.name)
                if os.path.exists(file_path):
                    return self.profile_picture.url
            # If it's a new upload (has read method), return the URL
            elif hasattr(self.profile_picture, 'read'):
                return self.profile_picture.url
        except Exception:
            pass
        return None

    def get_profile_picture_web_url(self):
        """Safely get web-sized profile picture URL, returning None if file doesn't exist."""
        if not self.profile_picture_web:
            return None
        try:
            import os

            from django.conf import settings

            if hasattr(self.profile_picture_web, 'name'):
                file_path = os.path.join(settings.MEDIA_ROOT, self.profile_picture_web.name)
                if os.path.exists(file_path):
                    return self.profile_picture_web.url
        except Exception:
            pass
        return None

    def save(self, *args, **kwargs):
        # Process profile picture if feature is enabled and a new one is being uploaded
        try:
            from giftwiki.feature_flags import get_profile_picture_enabled

            PROFILE_PICTURE_ENABLED = get_profile_picture_enabled()
        except Exception:
            # If feature flags aren't available (e.g., during migrations), default to disabled
            PROFILE_PICTURE_ENABLED = False

        if PROFILE_PICTURE_ENABLED:
            # Process profile picture if a new one is being uploaded
            # Check if profile_picture has a file (new upload) and the file exists
            if self.profile_picture:
                # Check if it's a new upload (has read method) or existing file
                if hasattr(self.profile_picture, 'read'):
                    # New upload - process it
                    from .utils import process_profile_picture

                    try:
                        thumbnail, web_size = process_profile_picture(self.profile_picture)
                        if thumbnail:
                            self.profile_picture_thumbnail = thumbnail
                        if web_size:
                            self.profile_picture_web = web_size
                    except Exception as e:
                        # Log error but don't fail the save
                        logger.error(f'Error processing profile picture: {e}')
                elif hasattr(self.profile_picture, 'name'):
                    # Existing file path - check if file actually exists
                    import os

                    from django.conf import settings

                    file_path = os.path.join(settings.MEDIA_ROOT, self.profile_picture.name)
                    if not os.path.exists(file_path):
                        # File doesn't exist - clear the reference
                        logger.warning(
                            f'Profile picture file not found: {file_path}, clearing reference'
                        )
                        self.profile_picture = None
                        self.profile_picture_thumbnail = None
                        self.profile_picture_web = None
        else:
            # Feature disabled - clear any profile picture references if they exist but files are missing
            if self.profile_picture and hasattr(self.profile_picture, 'name'):
                import os

                from django.conf import settings

                try:
                    file_path = os.path.join(settings.MEDIA_ROOT, self.profile_picture.name)
                    if not os.path.exists(file_path):
                        # File doesn't exist - clear the reference
                        self.profile_picture = None
                        self.profile_picture_thumbnail = None
                        self.profile_picture_web = None
                except Exception:
                    # If we can't check, just continue - don't fail the save
                    pass

        super().save(*args, **kwargs)


class Family(models.Model):
    name = models.CharField(max_length=255, default='My Family')
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(
        upload_to='family_images/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])],
    )

    def __str__(self):
        return self.name


class WishList(models.Model):
    owner = models.ForeignKey(WikiUser, on_delete=models.CASCADE, related_name='owned_wishlist')
    dependent = models.ForeignKey(
        WikiUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stewarded_wishlists',
    )
    managers = models.ManyToManyField(
        WikiUser,
        related_name='managed_wishlists',
        blank=True,
        help_text='Additional users who can manage this list',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(
        upload_to='wishlist_images/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])],
    )
    family_category = models.CharField(max_length=255, default='General')  # Default value
    family_name = models.ForeignKey(
        Family, on_delete=models.SET_NULL, null=True, blank=True, related_name='wishlists'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class Item(models.Model):
    """
    Item model = an item represents an individual item on a WishList. An Item can have multiple Variations, Suggestions,


    Attributes:
        wishlist (ForeignKey): The WishList the Item belongs to
        name (CharField): The name of the Item
        description (TextField): The description of the Item
        purchased (BooleanField): The status of the Item
        is_priority (BooleanField): Whether the owner marked this as a most-wanted item
        is_sneaky (BooleanField): Whether this is a surprise item hidden from the list owner
        archived_at (DateTimeField): When the owner moved this received gift to the archive
        thank_you_sent (BooleanField): Whether the owner sent a thank-you for this gift
        price (DecimalField): The price of the Item
        price_range (CharField): A price range category for the item
        created_at (DateTimeField): The date and time the Item was created
        updated_at (DateTimeField): The date and time the Item was last updated
    """

    PRICE_RANGE_CHOICES = [
        ('under_50', 'Under $50'),
        ('under_100', 'Under $100'),
        ('under_200', 'Under $200'),
        ('under_500', 'Under $500'),
        ('over_expectations', 'Over Expectations 😄'),
    ]

    wishlist = models.ForeignKey(WishList, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=255)  # Required field - no default
    description = models.TextField(blank=True)
    purchased = models.BooleanField(default=False)
    is_priority = models.BooleanField(
        default=False, help_text='Mark as one of your most-wanted items'
    )
    is_sneaky = models.BooleanField(
        default=False,
        help_text='Surprise item added by someone else — hidden from the list owner',
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the owner moved this received gift to their archive',
    )
    thank_you_sent = models.BooleanField(
        default=False, help_text='Whether the owner sent a thank-you for this gift'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    price_range = models.CharField(
        max_length=20,
        choices=PRICE_RANGE_CHOICES,
        blank=True,
        null=True,
        help_text='Select a price range category',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    purchased_by = models.ForeignKey(
        WikiUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchased_items'
    )
    updated_by = models.ForeignKey(
        WikiUser, on_delete=models.CASCADE, related_name='updated_%(class)s_records', null=True
    )
    url = models.URLField(blank=True, null=True, help_text='Link to the product page')
    is_deleted = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if 'current_user' in kwargs:
            self.updated_by = kwargs['current_user']
            del kwargs['current_user']
        if self.pk:
            try:
                previous = Item.objects.get(pk=self.pk)
                if not previous.is_deleted and self.is_deleted:
                    logger.info(
                        'Item soft-deleted',
                        extra={'item_id': self.pk, 'wishlist_id': self.wishlist_id},
                    )
                if previous.purchased != self.purchased:
                    if self.purchased:
                        logger.info(
                            'Item purchased',
                            extra={
                                'item_id': self.pk,
                                'wishlist_id': self.wishlist_id,
                                'purchased_by': getattr(self.purchased_by, 'email', None),
                            },
                        )
                    else:
                        logger.info(
                            'Item unpurchased',
                            extra={'item_id': self.pk, 'wishlist_id': self.wishlist_id},
                        )
            except Item.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Suggestion(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='suggestions')
    name = models.CharField(max_length=255, default='My Suggestion')
    hyperlink = models.URLField(blank=True, null=True)  # Allow null and blank
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='suggestions/', blank=True, null=True)  # Image field
    suggested_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )  # Optional price field
    suggested_by = models.ForeignKey(
        WikiUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='suggested_items'
    )  # Track who suggested it
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)  # Soft deletion

    def __str__(self):
        return self.name


class ItemGroup(models.Model):
    wishlist = models.ForeignKey(WishList, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField(max_length=255, default='My Group')
    description = models.TextField(blank=True, null=True)
    items = models.ManyToManyField(Item, related_name='groups')

    def __str__(self):
        return self.name


class Category(models.Model):
    family = models.ForeignKey(
        Family, on_delete=models.CASCADE, related_name='categories', null=True, blank=True
    )
    name = models.CharField(max_length=255, default='My Category')
    description = models.TextField(blank=True, null=True)
    items = models.ManyToManyField(Item, related_name='categories')

    class Meta:
        verbose_name_plural = 'Categories'
        unique_together = ['family', 'name']  # Category names must be unique within a family

    def __str__(self):
        return self.name


class FeatureFlag(models.Model):
    """
    Manage feature flags from the admin interface.
    Changes take effect without server restart when cache is cleared.

    Admin can enable/disable features in real-time from /admin/.
    """

    name = models.CharField(
        max_length=100, unique=True, help_text='Flag name (e.g., STEWARD_PROXY_ENABLED)'
    )
    enabled = models.BooleanField(default=False, help_text='Whether this feature is enabled')
    description = models.TextField(blank=True, help_text='What this feature does')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'feature_flags'
        ordering = ['name']
        verbose_name = 'Feature Flag'
        verbose_name_plural = 'Feature Flags'

    def __str__(self):
        status = '✅ Enabled' if self.enabled else '❌ Disabled'
        return f'{self.name} - {status}'


class ScrapedWikiPage(models.Model):
    """
    Stores scraped gift list pages from the old PBworks wiki.
    Users can select a scraped page to import their items.
    """

    title = models.CharField(max_length=255)
    url = models.URLField(help_text='Original URL from the wiki')
    scraped_at = models.DateTimeField(help_text='When this page was scraped')
    item_count = models.IntegerField(default=0, help_text='Number of items on this page')
    is_imported = models.BooleanField(
        default=False, help_text='Whether items have been imported by a user'
    )
    imported_by = models.ForeignKey(
        WikiUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='imported_scraped_pages',
        help_text='User who imported this page',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        verbose_name = 'Scraped Wiki Page'
        verbose_name_plural = 'Scraped Wiki Pages'

    def __str__(self):
        return f'{self.title} ({self.item_count} items)'


class ScrapedWikiItem(models.Model):
    """
    Stores individual items from scraped wiki pages.
    """

    scraped_page = models.ForeignKey(
        ScrapedWikiPage, on_delete=models.CASCADE, related_name='items'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, help_text='Item description')
    purchased = models.BooleanField(
        default=False, help_text='Whether item was marked as purchased in original wiki'
    )
    original_text = models.TextField(blank=True, help_text='Original text as scraped from wiki')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Scraped Wiki Item'
        verbose_name_plural = 'Scraped Wiki Items'

    def __str__(self):
        return f'{self.name} ({self.scraped_page.title})'


class AllowedEmail(models.Model):
    """
    Emails allowed to log into the application.
    Replaces the environment variable allowlist.
    """

    email = models.EmailField(unique=True, help_text='Email address allowed to log in')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']
        verbose_name = 'Allowed Email'
        verbose_name_plural = 'Allowed Emails'

    def __str__(self):
        return self.email


class LinkedEmail(models.Model):
    """
    Additional emails linked to a specific user account.
    If a user logs in with this email, they will be authenticated as the linked user.
    """

    user = models.ForeignKey(WikiUser, on_delete=models.CASCADE, related_name='linked_emails')
    email = models.EmailField(unique=True, help_text='Secondary email address')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']
        verbose_name = 'Linked Email'
        verbose_name_plural = 'Linked Emails'

    def __str__(self):
        return f"{self.email} -> {self.user.username}"

class Season(models.Model):
    name = models.CharField(max_length=50, unique=True, help_text="e.g., 'Summer'")
    start_month = models.IntegerField(help_text="Numeric month (1-12)")
    end_month = models.IntegerField(help_text="Numeric month (1-12)")

    def __str__(self):
        return self.name
