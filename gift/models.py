from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class WishList(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_wishlist')
    steward = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stewarded_wishlists')
    title = models.CharField(max_length=255, default='My WishList')
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='wishlist_images/', blank=True, null=True)
    family_category = models.CharField(max_length=255, default='General')  # Default value
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
        price (DecimalField): The price of the Item
        created_at (DateTimeField): The date and time the Item was created
        updated_at (DateTimeField): The date and time the Item was last updated
    """
    wishlist = models.ForeignKey(WishList, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=255, default='My Item')
    description = models.TextField()
    purchased = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    purchased_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchased_items')
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Variation(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='variations')
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.description


class Suggestion(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='suggestions')
    name = models.CharField(max_length=255, default='My Suggestion')
    hyperlink = models.URLField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.hyperlink


class ItemGroup(models.Model):
    wishlist = models.ForeignKey(WishList, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField(max_length=255, default='My Group')
    description = models.TextField(blank=True, null=True)
    items = models.ManyToManyField(Item, related_name='groups')

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=255, default='My Category')
    description = models.TextField(blank=True, null=True)
    items = models.ManyToManyField(Item, related_name='categories')

    def __str__(self):
        return self.name
