# forms.py

import logging

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.forms import formset_factory, modelformset_factory

from .models import Category, Item, ScrapedWikiPage, Suggestion, WishList

User = get_user_model()

logger = logging.getLogger(__name__)


class ItemForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Category',
        help_text='Select an existing category or create a new one below',
    )
    new_category_name = forms.CharField(
        max_length=255,
        required=False,
        label='Or Create New Category',
        help_text='Enter a name to create a new category (optional)',
    )

    class Meta:
        model = Item
        fields = ['name', 'description', 'price', 'price_range', 'url']

    def __init__(self, *args, **kwargs):
        wishlist = kwargs.pop('wishlist', None)
        super().__init__(*args, **kwargs)

        # Make name required with a helpful placeholder
        self.fields['name'].required = True
        self.fields['name'].widget.attrs['placeholder'] = (
            'Enter item name (e.g., "Nintendo Switch", "Coffee Maker")'
        )
        self.fields['name'].help_text = 'Required: Give your item a descriptive name'

        # Make description optional
        self.fields['description'].required = False
        self.fields['description'].help_text = 'Optional description'

        # Make price_range optional and user-friendly
        self.fields['price_range'].required = False
        self.fields['price_range'].empty_label = 'Select Price Range (Optional)'
        self.fields['price_range'].help_text = 'Choose a price range category'

        # Make url optional with placeholder
        self.fields['url'].required = False
        self.fields['url'].widget.attrs['placeholder'] = 'https://example.com/product'
        self.fields['url'].help_text = 'Optional link to the item'

        # Set up category field based on wishlist's family
        from .models import Category

        if wishlist and wishlist.family_name:
            base_queryset = Category.objects.filter(family=wishlist.family_name)
            # If editing an existing item, include its current category in the queryset
            # so it can be displayed even if it doesn't belong to the family
            if self.instance and self.instance.pk:
                current_categories = self.instance.categories.all()
                if current_categories.exists():
                    current_category = current_categories.first()
                    # Add current category to queryset if it's not already there
                    if current_category.id not in base_queryset.values_list('id', flat=True):
                        base_queryset = Category.objects.filter(
                            Q(family=wishlist.family_name) | Q(id=current_category.id)
                        )
            self.fields['category'].queryset = base_queryset
            self.fields['category'].empty_label = 'Select Existing Category (Optional)'
            # Add "Create new..." option to the widget choices
            original_choices = list(self.fields['category'].widget.choices)
            original_choices.append(('__CREATE_NEW__', '+ Create New Category'))
            self.fields['category'].widget.choices = original_choices
        else:
            # If no family, only show categories that also have no family
            # or include current item's category if editing
            if self.instance and self.instance.pk:
                current_categories = self.instance.categories.all()
                if current_categories.exists():
                    current_category = current_categories.first()
                    # Show categories with no family, or the current category
                    self.fields['category'].queryset = Category.objects.filter(
                        Q(family__isnull=True) | Q(id=current_category.id)
                    )
                else:
                    self.fields['category'].queryset = Category.objects.filter(family__isnull=True)
            else:
                self.fields['category'].queryset = Category.objects.filter(family__isnull=True)
            self.fields['category'].empty_label = 'No family selected - select a family first'
            # Add "Create new..." option to the widget choices
            original_choices = list(self.fields['category'].widget.choices)
            original_choices.append(('__CREATE_NEW__', '+ Create New Category'))
            self.fields['category'].widget.choices = original_choices

        # Set initial category if editing an existing item
        if self.instance and self.instance.pk:
            categories = self.instance.categories.all()
            if categories.exists():
                category = categories.first()
                # Set initial value if the category is in the queryset
                if category.id in self.fields['category'].queryset.values_list('id', flat=True):
                    self.fields['category'].initial = category.id

    def full_clean(self):
        """Override to handle '__CREATE_NEW__' before ModelChoiceField validation fails."""
        super().full_clean()

        # Check if category field has a validation error and if the raw value is '__CREATE_NEW__'
        if 'category' in self.errors:
            field_name = self.add_prefix('category')
            raw_value = self.data.get(field_name) if hasattr(self, 'data') and self.data else None

            if raw_value == '__CREATE_NEW__':
                # Remove the validation error and set the cleaned value
                del self.errors['category']
                self.cleaned_data['category'] = '__CREATE_NEW__'

    def clean_category(self):
        """Allow '__CREATE_NEW__' as a valid choice."""
        category = self.cleaned_data.get('category')
        # If it's already '__CREATE_NEW__' (set in full_clean), return it
        if category == '__CREATE_NEW__':
            return '__CREATE_NEW__'
        # Otherwise return the normal category value
        return category

    def clean_description(self):
        description = self.cleaned_data.get('description', '')
        if description:
            try:
                import bleach
                allowed_tags = ['p', 'strong', 'em', 'u', 's', 'ol', 'ul', 'li', 'a', 'br']
                allowed_attrs = {
                    'a': ['href', 'target', 'rel'],
                    '*': ['class']
                }
                cleaned = bleach.clean(description, tags=allowed_tags, attributes=allowed_attrs, strip=True)
                return cleaned
            except ImportError:
                # Fallback if bleach is not installed
                return description
        return description

    def save(self, commit=True, *args, **kwargs):
        current_user = kwargs.pop('current_user', None)
        wishlist = kwargs.pop('wishlist', None)
        instance = super().save(commit=False)
        if current_user:
            instance.updated_by = current_user
        if wishlist:
            instance.wishlist = wishlist
        if commit:
            instance.save()
            # Handle category assignment (ManyToMany needs saved instance)
            category = self.cleaned_data.get('category')
            new_category_name = self.cleaned_data.get('new_category_name')

            # Clear existing categories
            instance.categories.clear()

            # Handle "Create new..." option
            if category == '__CREATE_NEW__':
                if new_category_name and wishlist and wishlist.family_name:
                    from .models import Category

                    category_obj, created = Category.objects.get_or_create(
                        name=new_category_name,
                        family=wishlist.family_name,
                        defaults={'description': f'Category for {new_category_name}'},
                    )
                    if created:
                        logger.info(
                            'Category created',
                            extra={
                                'category_id': category_obj.id,
                                'name': new_category_name,
                                'family_id': wishlist.family_name_id,
                            },
                        )
                    instance.categories.add(category_obj)
            elif new_category_name and wishlist and wishlist.family_name:
                # If new category name provided, create it (takes precedence)
                from .models import Category

                category_obj, created = Category.objects.get_or_create(
                    name=new_category_name,
                    family=wishlist.family_name,
                    defaults={'description': f'Category for {new_category_name}'},
                )
                if created:
                    logger.info(
                        'Category created',
                        extra={
                            'category_id': category_obj.id,
                            'name': new_category_name,
                            'family_id': wishlist.family_name_id,
                        },
                    )
                instance.categories.add(category_obj)
            elif category and category != '__CREATE_NEW__':
                instance.categories.add(category)
        return instance


ItemFormSet = formset_factory(ItemForm, extra=3)  # For adding new items


# ModelFormSet for editing existing items
def get_item_modelformset(wishlist):
    """Create a ModelFormSet for editing existing items in a wishlist."""

    class ItemEditForm(ItemForm):
        """Form for editing existing items with category support."""

        pass

    # Include all editable fields from Item model
    # Note: category and new_category_name are not model fields, they're form fields
    # so we need to handle them in the form itself
    ItemModelFormSet = modelformset_factory(
        Item,
        form=ItemEditForm,
        fields=['name', 'description', 'price', 'price_range', 'url', 'purchased'],
        extra=0,  # Don't show empty forms
        can_delete=True,  # Allow deleting items
    )
    return ItemModelFormSet


class SuggestionForm(forms.ModelForm):
    class Meta:
        model = Suggestion
        fields = ['name', 'hyperlink', 'description', 'image', 'suggested_price']


class UserProfileForm(forms.ModelForm):
    """Form for updating user profile details like name and birthday."""
    
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    birthday = forms.DateField(
        required=False,
        label="Birthday",
        help_text="Used to organize wishlists by season.",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'birthday']


class ManagedUserForm(forms.ModelForm):
    """Form for updating managed user details like username, email, and birthday."""
    
    username = forms.CharField(required=True, label="Username")
    email = forms.EmailField(required=False, label="Email Address", help_text="Optional. If provided, they could use this to log in later.")
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    birthday = forms.DateField(
        required=False,
        label="Birthday",
        help_text="Used to organize wishlists by season.",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'birthday']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            qs = User.objects.filter(email__iexact=email)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This email address is already in use by another account.")
        return email


class CreateManagedUserForm(ManagedUserForm):
    from .models import WishList
    
    link_to_wishlist = forms.ModelChoiceField(
        queryset=WishList.objects.none(),
        required=False,
        label="Link to Existing Wishlist",
        help_text="Optional. Select a wishlist to link this user to. If left blank, a new one will be created."
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            from django.db.models import Q
            self.fields['link_to_wishlist'].queryset = self.link_to_wishlist.field.queryset.model.objects.filter(
                Q(owner=user) | Q(managers=user)
            ).distinct()


class ProfilePictureForm(forms.ModelForm):
    """Form for uploading profile pictures with camera support."""

    profile_picture = forms.ImageField(
        required=False,
        label='Profile Picture',
        help_text='Upload a photo or take a selfie (will be automatically resized)',
        widget=forms.FileInput(
            attrs={
                'accept': 'image/*',
                'capture': 'user',  # Enable camera on mobile devices
                'class': 'form-control',
            }
        ),
    )

    class Meta:
        model = User
        fields = ['profile_picture']


class WishListForm(forms.ModelForm):
    new_family_name = forms.CharField(
        max_length=255,
        required=False,
        label='Or Create New Family',
        help_text='Enter a name to create a new family (optional)',
    )
    new_family_poem = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='A Poem',
        help_text="Share a poem, story, or memory that captures your family's spirit (optional)",
        max_length=500,
    )
    scraped_page = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Import from Gift List',
        help_text='Optionally import items from an existing gift list',
    )
    
    # Virtual fields for creating a managed WikiUser
    is_managed = forms.BooleanField(
        required=False,
        label='This wishlist is for a managed user (e.g., child, grandparent)',
        help_text='Check this to create a profile for someone without a separate login.',
    )
    managed_username = forms.CharField(
        max_length=150,
        required=False,
        label="User's Username",
        help_text='A unique username for the user (e.g. "timmy_2015").',
    )
    managed_birthday = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        label="User's Birthday",
        help_text="So we can sort their wishlist into the correct birthday season.",
    )
    managed_email = forms.EmailField(
        required=False,
        label="User's Email (Optional)",
        help_text="If provided, they can eventually use this email to log in and take over their account.",
    )

    managers = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='Additional Managers',
        help_text='Select other users who can manage this list (optional)',
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = WishList
        fields = [
            'title',
            'description',
            'family_name',
        ]  # Removed 'image' - not needed for wishlists

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        instance = kwargs.get('instance', None)
        super().__init__(*args, **kwargs)

        # Add placeholder to title field (no default value)
        self.fields['title'].widget.attrs['placeholder'] = '<Your name>'
        self.fields['title'].required = True
        if not instance:
            # For new lists, ensure no default value
            self.fields['title'].initial = ''

        # Make description more creative and inspiring
        self.fields['description'].label = 'A Note'
        self.fields[
            'description'
        ].help_text = 'Share a note, story, or memory about this wishlist (optional)'
        self.fields['description'].widget.attrs['placeholder'] = (
            'Write a note, story, or memory about this wishlist...'
        )
        self.fields['description'].widget.attrs['rows'] = 3

        # Set up managers field
        from django.contrib.auth import get_user_model

        User = get_user_model()
        # Exclude the current user from the managers queryset
        if user:
            self.fields['managers'].queryset = User.objects.all().exclude(id=user.id)
        else:
            self.fields['managers'].queryset = User.objects.all()

        # Only set initial managers when editing an existing list
        # ModelMultipleChoiceField needs initial as a list of IDs, not queryset objects
        if instance and instance.pk:
            self.fields['managers'].initial = list(instance.managers.values_list('id', flat=True))
        else:
            # For new lists, ensure no managers are pre-selected
            self.fields['managers'].initial = []

        # Make family_name required (but keep required=False so "__CREATE_NEW__" can be selected)
        # We'll validate in clean() that a family is selected or created
        from gift.models import Family

        self.fields['family_name'].required = False  # Keep False to allow "__CREATE_NEW__"
        families = Family.objects.all()
        self.fields['family_name'].queryset = families
        self.fields['family_name'].empty_label = 'Select or Create Family'
        self.fields['family_name'].label = 'Family Group'
        self.fields['family_name'].help_text = 'Select an existing family or create a new one'

        # Add "Create new..." option to the widget choices after form initialization
        # We'll do this by modifying the widget's choices
        original_choices = list(self.fields['family_name'].widget.choices)
        original_choices.append(('__CREATE_NEW__', '+ Create New Family'))
        self.fields['family_name'].widget.choices = original_choices

        # Set up scraped page field
        from .models import ScrapedWikiPage

        scraped_pages = ScrapedWikiPage.objects.all().order_by('title')
        self.fields['scraped_page'].queryset = scraped_pages

        # Add item count to labels
        if scraped_pages.exists():
            choices = [('', 'None - Create Empty Wishlist')]
            for page in scraped_pages:
                label = f'{page.title} ({page.item_count} items)'
                choices.append((page.id, label))
            self.fields['scraped_page'].choices = choices
        else:
            # No scraped pages available - hide the field
            self.fields['scraped_page'].widget = forms.HiddenInput()
            self.fields['scraped_page'].required = False

        # Conditionally add dependent field based on feature flag
        from giftwiki.feature_flags import get_steward_proxy_enabled

        STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()

        if STEWARD_PROXY_ENABLED:
            self.fields['dependent'] = forms.ModelChoiceField(
                queryset=User.objects.all(),
                required=False,
                label='Dependent (Proxy User - who manages this list)',
            )
            if user:
                # Set the default steward to the current user
                self.fields['dependent'].initial = user.id

        for name, field in self.fields.items():
            if not field.required and name not in [
                'new_family_name',
                'new_family_poem',
                'scraped_page',
                'is_managed',
                'managed_username',
                'managed_birthday',
                'managed_email',
            ]:
                if self.fields[name].label:
                    self.fields[name].label += ' (Optional)'
                else:
                    self.fields[name].label = name.capitalize() + ' (Optional)'

    def full_clean(self):
        """Allow '__CREATE_NEW__' to survive ModelChoiceField validation."""
        super().full_clean()

        if 'family_name' in self.errors:
            field_name = self.add_prefix('family_name')
            raw_value = self.data.get(field_name) if hasattr(self, 'data') and self.data else None
            if raw_value == '__CREATE_NEW__':
                del self.errors['family_name']
                self.cleaned_data['family_name'] = '__CREATE_NEW__'

    def clean(self):
        cleaned_data = super().clean()
        family_name = cleaned_data.get('family_name')
        new_family_name = cleaned_data.get('new_family_name')
        
        is_managed = cleaned_data.get('is_managed')
        managed_username = cleaned_data.get('managed_username')
        managed_birthday = cleaned_data.get('managed_birthday')

        if is_managed:
            if not managed_username:
                self.add_error('managed_username', 'Username is required for managed accounts.')
            elif User.objects.filter(username=managed_username).exists():
                self.add_error('managed_username', 'This username is already taken.')
                
            if not managed_birthday:
                self.add_error('managed_birthday', 'Birthday is required for managed accounts.')

        # Handle "Create new..." option
        if family_name == '__CREATE_NEW__':
            if not new_family_name or not new_family_name.strip():
                raise forms.ValidationError(
                    {
                        'new_family_name': 'Please enter a name for the new family.',
                        'family_name': 'You must select a family or create a new one.',
                    }
                )
            # Clear the special value - we'll create the family in the view
            cleaned_data['family_name'] = None
        elif new_family_name and family_name and family_name != '__CREATE_NEW__':
            # If both are provided, prefer the new family name
            cleaned_data['family_name'] = None

        # Ensure a family is selected or being created
        if not cleaned_data.get('family_name') and not new_family_name:
            raise forms.ValidationError(
                {'family_name': 'You must select a family or create a new one.'}
            )

        return cleaned_data


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        labels = {'name': 'Category Name', 'description': 'Description (Optional)'}
        help_texts = {
            'name': 'Enter the category name',
            'description': 'Optional description for this category',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            'username',
            'email',
        )


class ScrapedPageSelectionForm(forms.Form):
    """Form for selecting a scraped wiki page to import."""

    scraped_page = forms.ModelChoiceField(
        queryset=ScrapedWikiPage.objects.all().order_by('title'),
        required=True,
        label='Select Your Gift List',
        help_text='Choose the gift list from the old wiki that belongs to you',
        widget=forms.RadioSelect(attrs={'class': 'scraped-page-radio'}),
    )
    target_wishlist = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Add to Existing Wishlist (Optional)',
        help_text='Select an existing wishlist to add items to, or leave blank to create a new one',
        empty_label='Create New Wishlist',
    )

    def __init__(self, *args, **kwargs):
        allow_reset = kwargs.pop('allow_reset', False)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Show all pages - seed data is recreated on server restart, so we don't need to restrict
        # When resetting, we still show all pages but mark user's current selection
        queryset = ScrapedWikiPage.objects.all().order_by('title')

        self.fields['scraped_page'].queryset = queryset

        # Add item count to labels
        choices = []
        for page in queryset:
            label = f'{page.title} ({page.item_count} items)'
            if page.is_imported and page.imported_by == user:
                label += ' [Your current selection]'
            choices.append((page.id, label))
        self.fields['scraped_page'].choices = choices

        # Set up wishlist field if user is provided
        if user:
            from .models import WishList

            # Get user's existing wishlists, prioritizing family wishlists
            user_wishlists = WishList.objects.filter(owner=user)

            # If user is in a family, prioritize wishlists in that family
            if user.family_name:
                family_wishlists = user_wishlists.filter(family_name=user.family_name)
                other_wishlists = user_wishlists.exclude(family_name=user.family_name)
                # Order: family wishlists first, then others
                wishlist_queryset = (family_wishlists | other_wishlists).distinct()
            else:
                wishlist_queryset = user_wishlists

            self.fields['target_wishlist'].queryset = wishlist_queryset

            # Add helpful labels showing family info
            if wishlist_queryset.exists():
                choices = []
                for wl in wishlist_queryset:
                    label = wl.title
                    if wl.family_name:
                        label += f' ({wl.family_name.name})'
                    if wl.items.exists():
                        label += f' - {wl.items.count()} existing items'
                    choices.append((wl.id, label))
                self.fields['target_wishlist'].choices = [('', 'Create New Wishlist')] + choices
            else:
                # No existing wishlists - hide the field
                self.fields['target_wishlist'].widget = forms.HiddenInput()
                self.fields['target_wishlist'].required = False
        else:
            self.fields['target_wishlist'].widget = forms.HiddenInput()
            self.fields['target_wishlist'].required = False
