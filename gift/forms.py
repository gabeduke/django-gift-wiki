# forms.py

import logging

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.forms import formset_factory, modelformset_factory

from .exchange_kinds import DEFAULT_KIND, KINDS
from .models import Category, Exchange, ExchangeLetter, Item, ScrapedWikiPage, Suggestion, WishList

User = get_user_model()

logger = logging.getLogger(__name__)


def validate_login_email_available(email, exclude_user=None):
    """Reject an email that already routes to some other account.

    Checks both WikiUser.email and LinkedEmail, since the Firebase middleware
    resolves a login against either one.
    """
    if not email:
        return email

    from .models import LinkedEmail

    users = User.objects.filter(email__iexact=email)
    if exclude_user is not None and exclude_user.pk:
        users = users.exclude(pk=exclude_user.pk)
    if users.exists():
        raise forms.ValidationError('This email address is already in use by another account.')

    linked = LinkedEmail.objects.filter(email__iexact=email)
    if exclude_user is not None and exclude_user.pk:
        linked = linked.exclude(user_id=exclude_user.pk)
    if linked.exists():
        raise forms.ValidationError('This email address is already linked to another account.')

    return email


class ItemForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Category',
        help_text='Select an existing category',
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

        # Set initial category if editing an existing item
        if self.instance and self.instance.pk:
            categories = self.instance.categories.all()
            if categories.exists():
                category = categories.first()
                # Set initial value if the category is in the queryset
                if category.id in self.fields['category'].queryset.values_list('id', flat=True):
                    self.fields['category'].initial = category.id

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

            # Clear existing categories
            instance.categories.clear()

            if category:
                instance.categories.add(category)
        return instance


ItemFormSet = formset_factory(ItemForm, extra=3)  # For adding new items


# ModelFormSet for editing existing items
def get_item_modelformset(wishlist):
    """Create a ModelFormSet for editing existing items in a wishlist."""

    class ItemEditForm(ItemForm):
        """Form for editing existing items with category support."""

        pass

    # Note: category is not a model field, it's a form field handled in ItemForm.
    # `purchased` is deliberately absent: only owners and managers reach this
    # form, and they must never see — or reset — what's been bought.
    ItemModelFormSet = modelformset_factory(
        Item,
        form=ItemEditForm,
        fields=['name', 'description', 'price', 'price_range', 'url', 'is_priority'],
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
    """Form for updating managed user details like name and birthday.
    
    Note: username and email are intentionally excluded as they are
    authentication-related fields that should not be editable by
    wishlist managers.
    """
    
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    birthday = forms.DateField(
        required=False,
        label="Birthday",
        help_text="Used to organize wishlists by season.",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    link_to_wishlist = forms.ModelChoiceField(
        queryset=WishList.objects.none(),
        required=False,
        label="Link to Existing Wishlist",
        help_text="Optional. Select a wishlist to link this user to."
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'birthday']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # The requester's list this person is kept on, if any
        self.current_wishlist = None
        if user:
            from django.db.models import Q

            self.fields['link_to_wishlist'].queryset = WishList.objects.filter(
                Q(owner=user) | Q(managers=user)
            ).distinct()

            # Pre-populate from the requester's own lists only: one outside the
            # choices renders the select blank, and saving a blank select unlinks.
            if self.instance and self.instance.pk:
                self.current_wishlist = (
                    self.fields['link_to_wishlist']
                    .queryset.filter(dependent=self.instance)
                    .first()
                )
                if self.current_wishlist:
                    self.initial['link_to_wishlist'] = self.current_wishlist.pk

    def clean_link_to_wishlist(self):
        """Never take a list away from somebody else it's already kept for."""
        wishlist = self.cleaned_data.get('link_to_wishlist')
        if wishlist and wishlist.dependent_id not in (None, self.instance.pk):
            raise forms.ValidationError(
                f'"{wishlist.title}" is already kept for '
                f'{wishlist.dependent.first_name or wishlist.dependent.username}.'
            )
        return wishlist


class CreateManagedUserForm(ManagedUserForm):
    """Form for creating a new managed user. Includes username and email
    which are needed at creation time but not editable later via ManagedUserForm."""
    
    username = forms.CharField(required=True, label="Username")
    email = forms.EmailField(
        required=False,
        label="Email Address",
        help_text="Optional. If provided, they could use this to log in later."
    )

    class Meta(ManagedUserForm.Meta):
        fields = ['username', 'email', 'first_name', 'last_name', 'birthday']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['link_to_wishlist'].help_text = "Optional. Select a wishlist to link this user to. If left blank, a new one will be created."

    def clean_email(self):
        return validate_login_email_available(
            self.cleaned_data.get('email'),
            exclude_user=self.instance,
        )


class AssignLoginEmailForm(forms.Form):
    """Grants an existing managed user an email address they can sign in with.

    Kept separate from ManagedUserForm on purpose: that form edits harmless
    profile details, while this one hands somebody the keys to the account.
    """

    email = forms.EmailField(
        required=True,
        label='Email Address',
        help_text='They sign in with "Sign in with Google" using this address.',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'}),
    )

    def __init__(self, *args, **kwargs):
        self.managed_user = kwargs.pop('managed_user', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        return validate_login_email_available(
            self.cleaned_data.get('email'),
            exclude_user=self.managed_user,
        )


def clean_photo_upload(upload, process=None):
    """Reject an upload that is too big or isn't a photo, with a message a
    child can act on. With `process`, return its cleaned result instead."""
    from .utils import PHOTO_MAX_BYTES, PHOTO_TOO_BIG, open_photo

    if upload.size > PHOTO_MAX_BYTES:
        raise forms.ValidationError(PHOTO_TOO_BIG)
    try:
        if process:
            return process(upload)
        open_photo(upload)
    except ValueError as error:
        raise forms.ValidationError(str(error)) from error
    upload.seek(0)
    return upload


class ProfilePictureForm(forms.ModelForm):
    """A new profile picture. WikiUser.save() crops and cleans it."""

    # A plain FileField, not ImageField: the extension check would turn away
    # photos phones hand over as .webp or .heic-converted; open_photo decides.
    profile_picture = forms.FileField(
        required=True,
        label='Choose a photo',
        help_text='We crop it to a square and remove where it was taken.',
        widget=forms.FileInput(attrs={'accept': 'image/*', 'class': 'form-control'}),
    )

    class Meta:
        model = User
        fields = ['profile_picture']

    def clean_profile_picture(self):
        return clean_photo_upload(self.cleaned_data['profile_picture'])


class DecorateListForm(forms.ModelForm):
    """🎨 Decorate: an emoji, a colour and a cover photo for one list."""

    image = forms.FileField(
        required=False,
        label='Cover photo',
        widget=forms.FileInput(attrs={'accept': 'image/*', 'class': 'wl-file-input'}),
    )
    remove_image = forms.BooleanField(required=False)

    class Meta:
        model = WishList
        fields = ['emoji', 'accent', 'image']
        widgets = {'emoji': forms.RadioSelect, 'accent': forms.RadioSelect}

    def clean_image(self):
        from .utils import process_cover_image

        upload = self.cleaned_data.get('image')
        # Unchanged (the stored file) or nothing chosen: nothing to process
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        return clean_photo_upload(upload, process=process_cover_image)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('remove_image') and not self.files.get('image'):
            # False, not None: None means "unchanged" to a model FileField
            cleaned['image'] = False
        return cleaned


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
        # Leave out the list's owner (for a new list, its creator) — not whoever
        # is editing: a manager saving the list must stay a manager.
        owner = instance.owner if instance and instance.pk else user
        if owner:
            self.fields['managers'].queryset = User.objects.all().exclude(id=owner.id)
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
            # Only yourself and people you already manage: naming somebody as a
            # dependent makes them your "managed user", so it can't be anyone.
            dependent_choices = User.objects.none()
            if user:
                from django.db.models import Q

                dependent_choices = User.objects.filter(
                    Q(pk=user.pk)
                    | Q(stewarded_wishlists__owner=user)
                    | Q(stewarded_wishlists__managers=user)
                )
            if instance and instance.pk and instance.dependent_id:
                # Keep whoever the list is already for, or saving would drop them
                dependent_choices = dependent_choices | User.objects.filter(
                    pk=instance.dependent_id
                )
            self.fields['dependent'] = forms.ModelChoiceField(
                queryset=dependent_choices.distinct(),
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


class ExchangeForm(forms.ModelForm):
    """Name and details of an exchange — call it whatever the family likes."""

    class Meta:
        model = Exchange
        fields = ['name', 'kind', 'icon', 'budget', 'exchange_date', 'notes', 'board_enabled']
        labels = {
            'name': 'What should we call it?',
            'kind': 'What are we exchanging?',
            'icon': 'Icon',
            'budget': 'Spending limit (optional)',
            'exchange_date': 'When it happens',
            'notes': 'Anything else people should know',
            'board_enabled': 'After letters are delivered, show everyone a board of them',
        }
        help_texts = {
            'budget': '',
            'board_enabled': 'Only letters both the writer and the reader choose to share. '
            'Lovely for a letters or kindness exchange.',
        }
        widgets = {
            'name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'e.g. Thankful Letters 2026'}
            ),
            'kind': forms.Select(attrs={'class': 'form-control'}),
            'icon': forms.RadioSelect(attrs={'class': 'wl-icon-choice'}),
            'budget': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. $50'}),
            'exchange_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Leaving it out keeps what it was (a gift exchange, for a new one)
        self.fields['kind'].required = False
        # Each kind's one-line description, shown as a list under the select
        self.kind_blurbs = [(kind.icon, kind.label, kind.blurb) for kind in KINDS.values()]
        if not self.instance.pk:
            # Start blank so the placeholder shows, not the model's default
            self.initial['name'] = ''

    def clean_kind(self):
        return self.cleaned_data.get('kind') or self.instance.kind or DEFAULT_KIND


class ExchangeLetterForm(forms.ModelForm):
    """A letter to the person you drew: words, a photo of something handmade, or both."""

    remove_image = forms.BooleanField(required=False, label='Remove the photo')

    class Meta:
        model = ExchangeLetter
        fields = ['body', 'image', 'shareable']
        labels = {
            'body': '',
            'image': 'Add a photo or scan',
            'shareable': 'Okay to show on the exchange’s board once it’s delivered',
        }
        widgets = {
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 6}),
            'image': forms.FileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A blank letter with no photo is how you take yours back
        self.fields['body'].required = False
        # Length is checked in clean_body, after line endings are normalised:
        # browsers count a line break as one character but send two.
        self.fields['body'].max_length = None
        self.fields['body'].validators = []

    def clean_body(self):
        body = (self.cleaned_data.get('body') or '').replace('\r\n', '\n')
        if len(body) > ExchangeLetter.MAX_LENGTH:
            raise forms.ValidationError(
                f'Letters can be up to {ExchangeLetter.MAX_LENGTH:,} characters — '
                f'this one is {len(body):,}.'
            )
        return body

    def clean_image(self):
        from .utils import LETTER_IMAGE_MAX_BYTES, process_letter_image

        upload = self.cleaned_data.get('image')
        # Unchanged (the stored file) or cleared: nothing to process
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        if upload.size > LETTER_IMAGE_MAX_BYTES:
            raise forms.ValidationError('That photo is too big — 15 MB at most.')
        try:
            return process_letter_image(upload)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('remove_image') and not self.files.get('image'):
            # False, not None: None means "unchanged" to a model FileField
            cleaned['image'] = False
        return cleaned

    @property
    def is_empty(self):
        """Nothing written and no photo: the letter should be taken back."""
        body = (self.cleaned_data.get('body') or '').strip()
        return not body and not self.cleaned_data.get('image')
