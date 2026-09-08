import json
import logging
import secrets
import string
from collections import defaultdict
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from .forms import (
    CategoryForm,
    CreateManagedUserForm,
    CustomUserCreationForm,
    ItemForm,
    ManagedUserForm,
    ProfilePictureForm,
    ScrapedPageSelectionForm,
    UserProfileForm,
    WishListForm,
)
from .models import (
    Category,
    ChangelogEntry,
    Item,
    ScrapedWikiItem,
    ScrapedWikiPage,
    Season,
    WishList,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def custom_admin_login(request, **kwargs):
    """
    Redirect unauthenticated admin users to the Firebase auth page.
    If they are authenticated but lack staff permissions, show the default Django 'not authorized' page.
    """
    if request.user.is_authenticated:
        from django.contrib.admin.sites import site
        return site.login(request, **kwargs)
    
    url = '/auth.html'
    if 'next' in request.GET:
        url += f"?next={request.GET['next']}"
    return redirect(url)


@csrf_exempt
@never_cache
def metrics_view(request):
    """
    Expose Prometheus metrics endpoint.
    Only accessible from within the cluster (no external access needed).
    Exempt from CSRF protection since Prometheus doesn't send CSRF tokens.
    """
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return HttpResponse('Prometheus client not installed', status=503)


def auth_view(request):
    """
    Render the authentication page with Firebase configuration injected from settings.
    This replaces the static auth.html file to avoid hardcoding API keys.
    """
    from django.conf import settings

    context = {'firebase_config': json.dumps(settings.FIREBASE_CLIENT_CONFIG)}
    return render(request, 'gift/auth.html', context)


def privacy_view(request):
    return render(request, 'gift/privacy.html')


def data_deletion_view(request):
    return render(request, 'gift/data_deletion.html')


@csrf_exempt
@require_POST
def session_login_view(request):
    """
    Create a Firebase session cookie from an ID token.

    This replaces the Firebase Cloud Function /sessionLogin endpoint,
    allowing Firebase Auth to work when the app is served directly from
    k3s/Kubernetes instead of Firebase Hosting.

    Flow: Browser gets ID token from Firebase Auth popup → POSTs to /sessionLogin
    → This view verifies the token and sets __session cookie → Browser is authenticated.
    """
    import math
    import time

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    id_token = body.get('idToken')
    if not id_token:
        return JsonResponse({'error': 'ID token is required'}, status=400)

    # Get Firebase Admin auth module
    from gift.middleware.firebase_auth import _get_firebase_auth

    firebase_auth = _get_firebase_auth()
    if not firebase_auth:
        logger.error('Firebase Admin SDK not available for session login')
        return JsonResponse({'error': 'Firebase Admin SDK not configured'}, status=500)

    # Verify the ID token
    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
    except Exception as e:
        logger.warning(f'ID token verification failed: {e}')
        return JsonResponse({'error': 'Invalid ID token'}, status=401)

    # Check token freshness (same logic as the Cloud Function)
    auth_time = decoded_token.get('auth_time', 0)
    token_issued_at = decoded_token.get('iat', 0)
    current_time = math.floor(time.time())
    five_minutes = 5 * 60

    is_auth_recent = (current_time - auth_time) < five_minutes
    is_token_fresh = (current_time - token_issued_at) < five_minutes

    if not is_auth_recent and not is_token_fresh:
        logger.warning(
            f'Token too old: auth_time={current_time - auth_time}s ago, '
            f'iat={current_time - token_issued_at}s ago'
        )
        return JsonResponse(
            {
                'error': 'Recent sign-in required',
                'details': 'Token is too old. Please sign in again.',
            },
            status=401,
        )

    # Create session cookie (expires in 5 days)
    expires_in_seconds = 60 * 60 * 24 * 5  # 5 days
    try:
        session_cookie = firebase_auth.create_session_cookie(
            id_token,
            expires_in=expires_in_seconds,  # Python SDK expects seconds (not ms like JS SDK)
        )
    except Exception as e:
        logger.error(f'Failed to create session cookie: {e}')
        return JsonResponse({'error': 'Failed to create session cookie'}, status=500)

    # Build response with cookie
    response = JsonResponse(
        {
            'status': 'success',
            'expiresIn': expires_in_seconds,
            'message': 'Session cookie created successfully',
        }
    )

    is_secure = request.is_secure() or request.META.get('HTTP_X_FORWARDED_PROTO') == 'https'
    response.set_cookie(
        '__session',
        session_cookie,
        max_age=expires_in_seconds,
        httponly=True,
        secure=is_secure,
        samesite='Lax',
        path='/',
    )

    logger.info(f'Session cookie created for user: {decoded_token.get("email", "unknown")}')
    return response


class SignUpView(generic.CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy('gift:login')
    template_name = 'gift/auth_signup.html'


@csrf_protect
def logout_view(request):
    """Custom logout view that clears Django session and redirects to Firebase logout."""
    logger.info(
        'User logged out', extra={'user': getattr(request.user, 'email', str(request.user))}
    )
    auth_logout(request)
    messages.success(request, 'You have been logged out successfully.')

    # Redirect to Firebase auth page which will handle Firebase logout
    # Pass a query parameter to indicate logout
    response = redirect('/auth.html?logout=true')
    # The __session cookie is HttpOnly and cannot be deleted by JS, so backend must delete it
    response.delete_cookie('__session')
    return response


@require_POST
@login_required
def item_add_ajax(request, wishlist_id):
    try:
        data = json.loads(request.body)
        wishlist = get_object_or_404(WishList, id=wishlist_id)

        # Business Rule: Only owner or managers can add items
        is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
        is_manager = request.user in wishlist.managers.all()
        from giftwiki.feature_flags import get_steward_proxy_enabled

        is_steward = get_steward_proxy_enabled() and request.user == wishlist.dependent

        if not (is_owner or is_manager or is_steward):
            logger.warning(
                'Unauthorized item add attempt',
                extra={'wishlist_id': wishlist_id, 'user': request.user.email},
            )
            return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)

        # Create a new item
        item = Item(name=data['name'], wishlist=wishlist)
        # Set other fields as necessary
        item.save(current_user=request.user)
        logger.info(
            'Item added',
            extra={'item_id': item.id, 'wishlist_id': wishlist_id, 'user': request.user.email},
        )

        # Return the new item details
        return JsonResponse({'id': item.id, 'name': item.name})
    except Exception as e:
        # Log the exception for debugging
        logger.error(f'Error in item_add_ajax: {e}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def item_add(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Business Rule: Only owner or managers can add items
    is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
    is_manager = request.user in wishlist.managers.all()
    if not (is_owner or is_manager):
        logger.warning(
            'Unauthorized item add attempt',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        messages.error(request, 'You can only add items to wishlists you own or manage.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    if request.method == 'POST':
        form = ItemForm(request.POST, wishlist=wishlist)
        if form.is_valid():
            try:
                item = form.save(commit=True, wishlist=wishlist, current_user=request.user)
                logger.info(
                    'Item added',
                    extra={
                        'item_id': item.id if item else None,
                        'wishlist_id': wishlist_id,
                        'user': request.user.email,
                    },
                )
                messages.success(request, 'Item added successfully.')
                return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
            except Exception as e:
                logger.error(f'Error saving item: {e}')
                messages.error(request, f'Error saving item: {str(e)}')
        else:
            # Log form errors for debugging
            logger.error(f'Form validation errors: {form.errors}')
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ItemForm(wishlist=wishlist)

    return render(request, 'gift/item_add.html', {'form': form, 'wishlist': wishlist})


def get_item_visible_to_user(request, item_id):
    """Fetch an item by id, 404ing on surprise items when the requester is the
    list's owner/recipient — they must not learn the item exists."""
    return get_object_or_404(
        Item.objects.exclude(is_sneaky=True, wishlist__owner=request.user).exclude(
            is_sneaky=True, wishlist__dependent=request.user
        ),
        id=item_id,
    )


@login_required
def sneaky_item_add(request, wishlist_id):
    """Add a surprise gift to someone else's list — hidden from the list owner."""
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # The list owner/recipient can never add surprise items to their own list
    if request.user == wishlist.owner or request.user == wishlist.dependent:
        logger.warning(
            'Owner attempted to add a surprise item to their own list',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        messages.error(request, 'You cannot add surprise gifts to your own list.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    if request.method == 'POST':
        form = ItemForm(request.POST, wishlist=wishlist)
        if form.is_valid():
            item = form.save(commit=False, wishlist=wishlist, current_user=request.user)
            item.is_sneaky = True
            item.save()
            logger.info(
                'Surprise item added',
                extra={
                    'item_id': item.id,
                    'wishlist_id': wishlist_id,
                    'user': request.user.email,
                },
            )
            messages.success(request, "Surprise gift added — the list owner can't see it. 🤫")
            return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
        logger.error(f'Form validation errors: {form.errors}')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ItemForm(wishlist=wishlist)

    return render(request, 'gift/sneaky_item_add.html', {'form': form, 'wishlist': wishlist})


@login_required
def item_edit(request, item_id):
    item = get_item_visible_to_user(request, item_id)

    # Business Rule: Only owner or managers can edit items
    is_owner = (request.user == item.wishlist.owner or request.user == item.wishlist.dependent)
    is_manager = request.user in item.wishlist.managers.all()
    if not (is_owner or is_manager):
        logger.warning(
            'Unauthorized item edit attempt',
            extra={'item_id': item_id, 'user': request.user.email},
        )
        messages.error(
            request, 'You can only edit items in your own wishlists or wishlists you manage.'
        )
        return redirect('gift:wishlist_detail', wishlist_id=item.wishlist.id)

    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item, wishlist=item.wishlist)
        if form.is_valid():
            try:
                form.save(commit=True, wishlist=item.wishlist, current_user=request.user)
                messages.success(request, 'Item updated successfully.')
                return redirect('gift:wishlist_detail', wishlist_id=item.wishlist.id)
            except Exception as e:
                logger.error(f'Error updating item: {e}')
                messages.error(request, f'Error updating item: {str(e)}')
        else:
            # Log form errors for debugging
            logger.error(f'Form validation errors: {form.errors}')
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ItemForm(instance=item, wishlist=item.wishlist)

    return render(
        request, 'gift/item_edit.html', {'form': form, 'item': item, 'wishlist': item.wishlist}
    )


@require_POST
@login_required
def item_delete(request, item_id):
    item = get_item_visible_to_user(request, item_id)

    # Business Rule: Only owner or managers can delete items
    is_owner = (request.user == item.wishlist.owner or request.user == item.wishlist.dependent)
    is_manager = request.user in item.wishlist.managers.all()
    if not (is_owner or is_manager):
        logger.warning(
            'Unauthorized item delete attempt',
            extra={'item_id': item_id, 'user': request.user.email},
        )
        messages.error(request, 'You can only delete items in wishlists you own or manage.')
        return redirect('gift:wishlist_detail', wishlist_id=item.wishlist.id)

    wishlist_id = item.wishlist.id
    item.is_deleted = True  # Soft delete
    item.save(current_user=request.user)
    logger.info(
        'Item deleted',
        extra={'item_id': item_id, 'wishlist_id': wishlist_id, 'user': request.user.email},
    )
    messages.success(request, 'Item deleted successfully.')
    return redirect('gift:wishlist_detail', wishlist_id=wishlist_id)


@login_required
def item_purchase(request, item_id):
    item = get_item_visible_to_user(request, item_id)
    wishlist = item.wishlist

    # Check if user is owner, steward, or manager
    is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()
    is_list_manager = is_owner or is_steward or is_manager

    # List owners/managers cannot mark items on their own list as purchased
    if is_list_manager:
        logger.warning(
            'Owner/manager attempted to purchase own list item',
            extra={'item_id': item_id, 'wishlist_id': wishlist.id, 'user': request.user.email},
        )
        messages.warning(request, 'You cannot mark items as purchased on your own list.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    # Can only purchase if not already purchased by someone else
    if item.purchased_by is not None and item.purchased_by != request.user:
        messages.warning(request, 'This item has already been purchased by someone else.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    # Mark as purchased by current user (or toggle if already purchased by this user)
    if item.purchased_by == request.user and item.purchased:
        # Toggle off if already purchased by this user
        item.purchased_by = None
        item.purchased = False
        messages.success(request, 'Item marked as not purchased.')
    else:
        # Mark as purchased
        item.purchased_by = request.user
        item.purchased = True
        messages.success(request, 'Item marked as purchased.')

    item.save(current_user=request.user)
    return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)


@login_required
def wishlist_create(request):
    if request.method == 'POST':
        form = WishListForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            try:
                wishlist = form.save(commit=False)

                # For now, always set owner to current user
                # External user functionality can be added later
                wishlist.owner = request.user

                # Handle dependent field if steward proxy is enabled
                from giftwiki.feature_flags import get_steward_proxy_enabled

                STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
                if STEWARD_PROXY_ENABLED and 'dependent' in form.cleaned_data:
                    dependent = form.cleaned_data.get('dependent')
                    if dependent:
                        wishlist.dependent = dependent

                # Auto-create managed account if requested
                if form.cleaned_data.get('is_managed'):
                    managed_username = form.cleaned_data.get('managed_username')
                    managed_birthday = form.cleaned_data.get('managed_birthday')
                    managed_email = form.cleaned_data.get('managed_email')
                    
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    
                    new_managed_user = User.objects.create(
                        username=managed_username,
                        birthday=managed_birthday,
                        email=managed_email,
                    )
                    wishlist.dependent = new_managed_user
                    messages.success(request, f'Created managed account for {managed_username}.')

                # Handle new family creation
                new_family_name = form.cleaned_data.get('new_family_name')
                new_family_poem = form.cleaned_data.get('new_family_poem', '').strip()
                if new_family_name:
                    from .models import Family

                    # Create new family if it doesn't exist
                    family_description = (
                        new_family_poem
                        if new_family_poem
                        else f'Family group for {new_family_name}'
                    )
                    family, created = Family.objects.get_or_create(
                        name=new_family_name, defaults={'description': family_description}
                    )
                    # Update description if family exists but poem was provided
                    if not created and new_family_poem:
                        family.description = new_family_poem
                        family.save()
                    wishlist.family_name = family
                    if created:
                        messages.success(request, f'Created new family: {new_family_name}')

                wishlist.save()
                logger.info(
                    'Wishlist created',
                    extra={
                        'wishlist_id': wishlist.id,
                        'family_id': wishlist.family_name_id,
                        'user': request.user.email,
                    },
                )

                # Save managers (ManyToMany field needs to be saved after the instance)
                if 'managers' in form.cleaned_data:
                    wishlist.managers.set(form.cleaned_data['managers'])

                # Handle scraped page import if selected
                scraped_page = form.cleaned_data.get('scraped_page')
                if scraped_page:
                    wishlist = import_scraped_page_to_user(
                        request.user, scraped_page, target_wishlist=wishlist
                    )
                    if wishlist:
                        messages.success(
                            request,
                            f'Wishlist created and {scraped_page.item_count} items imported from "{scraped_page.title}"!',
                        )
                    else:
                        messages.warning(
                            request, 'Wishlist created, but there was an error importing items.'
                        )

            except ValidationError as e:
                logger.error(e)
                messages.error(request, e.message)
                return redirect('home')

            if not scraped_page:
                messages.success(request, 'Wishlist created successfully.')
            return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
        else:
            logger.error(form.errors)
    else:
        form = WishListForm(user=request.user)
    return render(request, 'gift/wishlist_create.html', {'form': form})


# TODO: Implement external user functionality if needed
# def create_or_select_external_user(user_name, family_category):
#     """Helper function to create or select external users for wishlist management."""
#     pass


@login_required
def select_scraped_page(request):
    """
    View for users to select their scraped wiki page on first login.
    This will import their items into a new wishlist.
    """
    # Allow re-selection if ?reset=1 is in the URL (for testing)
    allow_reset = request.GET.get('reset') == '1'

    # Check if user has already selected a page
    if request.user.scraped_page_selected and not allow_reset:
        messages.info(request, 'You have already imported your gift list.')
        return redirect('gift:account')

    if request.method == 'POST':
        form = ScrapedPageSelectionForm(request.POST, user=request.user)
        if form.is_valid():
            scraped_page = form.cleaned_data['scraped_page']
            target_wishlist = form.cleaned_data.get('target_wishlist')

            # If user already has a selected page and we're resetting, unmark the old one
            if request.user.scraped_page_selected and request.user.selected_scraped_page:
                old_page = request.user.selected_scraped_page
                old_page.is_imported = False
                old_page.imported_by = None
                old_page.save()

            # Import items to user's wishlist (existing or new)
            wishlist = import_scraped_page_to_user(
                request.user, scraped_page, target_wishlist=target_wishlist
            )

            if wishlist:
                # Mark user as having selected a page (for reference, but allow re-importing)
                request.user.scraped_page_selected = True
                request.user.selected_scraped_page = scraped_page
                request.user.save()

                # Mark page as imported (for reference only - seed data is recreated on restart)
                # This is just for tracking, not for preventing reuse
                scraped_page.is_imported = True
                scraped_page.imported_by = request.user
                scraped_page.save()

                if target_wishlist:
                    messages.success(
                        request,
                        f'Successfully added {scraped_page.item_count} items from "{scraped_page.title}" to "{wishlist.title}"!',
                    )
                else:
                    messages.success(
                        request,
                        f'Successfully imported {scraped_page.item_count} items from "{scraped_page.title}" into new wishlist!',
                    )
                return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
            else:
                # Import failed - don't mark as imported
                messages.error(request, 'Error importing items. Please try again.')
    else:
        # Pass allow_reset to form so it can show all pages when resetting
        form = ScrapedPageSelectionForm(allow_reset=allow_reset, user=request.user)

    # Check if there are any available pages (all pages are available since seed data is recreated)
    available_pages = ScrapedWikiPage.objects.count()

    # Debug: Log total pages in database
    total_pages = ScrapedWikiPage.objects.count()
    if total_pages == 0:
        logger.warning('No scraped pages found in database. Data may not have been imported.')
        messages.error(
            request,
            'No gift lists found in database. Please contact an administrator to import the scraped data.',
        )
        return redirect('gift:account')

    if available_pages == 0:
        logger.warning('No scraped pages found in database.')
        messages.error(
            request,
            'No gift lists found in database. Please contact an administrator to import the scraped data.',
        )
        return redirect('gift:account')

    context = {
        'form': form,
        'available_pages_count': available_pages,
    }
    return render(request, 'gift/select_scraped_page.html', context)


def import_scraped_page_to_user(user, scraped_page, target_wishlist=None):
    """
    Import items from a scraped wiki page into a wishlist for the user.
    If target_wishlist is provided, adds items to that wishlist.
    Otherwise, creates a new wishlist.

    Returns the wishlist (existing or created) or None on error.
    """
    try:
        # Use existing wishlist or create new one
        if target_wishlist:
            wishlist = target_wishlist
            # Verify user owns this wishlist
            if wishlist.owner != user and wishlist.dependent != user:
                logger.error(f'User {user.username} does not own wishlist {wishlist.id}')
                return None
        else:
            # Create a new wishlist for the user
            # If user is in a family, associate the wishlist with that family
            wishlist = WishList.objects.create(
                owner=user,
                title=f'{scraped_page.title} (Imported)',
                description=f'Imported from old wiki: {scraped_page.url}',
                family_name=user.family_name,  # Associate with user's family if they have one
            )

        # Import all items from the scraped page
        scraped_items = ScrapedWikiItem.objects.filter(scraped_page=scraped_page)
        items_created = 0

        for scraped_item in scraped_items:
            Item.objects.create(
                wishlist=wishlist,
                name=scraped_item.name,
                description=scraped_item.description or scraped_item.name,
                purchased=scraped_item.purchased,
                updated_by=user,
            )
            items_created += 1

        action = 'Added' if target_wishlist else 'Imported'
        logger.info(
            f"{action} {items_created} items from scraped page '{scraped_page.title}' "
            f'to wishlist {wishlist.id} ({wishlist.title}) for user {user.username}'
        )

        return wishlist

    except Exception as e:
        logger.error(f'Error importing scraped page to user: {e}', exc_info=True)
        return None


@login_required
def profile(request):
    # Profile lists are the viewer's own lists, so items shown there must exclude
    # surprise items (and archived/deleted ones) to avoid spoiling them.
    visible_items = models.Prefetch(
        'items',
        queryset=Item.objects.filter(
            is_deleted=False, archived_at__isnull=True, is_sneaky=False
        ),
        to_attr='visible_items',
    )
    # Get all lists where the user is the owner - optimize with select_related
    wishlists = (
        WishList.objects.filter(owner=request.user)
        .select_related('family_name', 'owner', 'dependent')
        .prefetch_related(visible_items)
    )

    # Optionally include wishlists where user is the steward (if feature enabled)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    if STEWARD_PROXY_ENABLED:
        stewarded = (
            WishList.objects.filter(dependent=request.user)
            .select_related('family_name', 'owner', 'dependent')
            .prefetch_related(visible_items)
        )
        wishlists = wishlists | stewarded

    # Handle profile picture upload (only if feature enabled)
    from giftwiki.feature_flags import get_profile_picture_enabled

    PROFILE_PICTURE_ENABLED = get_profile_picture_enabled()
    profile_form = None
    user_profile_form = None
    


    if request.method == 'POST':
        if 'update_profile' in request.POST:
            user_profile_form = UserProfileForm(request.POST, instance=request.user)
            if user_profile_form.is_valid():
                user_profile_form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('gift:account')
            else:
                messages.error(request, 'Error updating profile. Please check the form.')
        else:
            user_profile_form = UserProfileForm(instance=request.user)
            
        if PROFILE_PICTURE_ENABLED:

            if 'update_profile_picture' in request.POST:
                profile_form = ProfilePictureForm(request.POST, request.FILES, instance=request.user)
                if profile_form.is_valid():
                    profile_form.save()
                    logger.info('Profile picture updated', extra={'user': request.user.email})
                    messages.success(request, 'Profile picture updated successfully!')
                    return redirect('gift:account')
                else:
                    logger.warning(
                        'Profile picture update failed',
                        extra={'user': request.user.email, 'errors': str(profile_form.errors)},
                    )
                    messages.error(request, 'Error updating profile picture. Please try again.')
            else:
                profile_form = ProfilePictureForm(instance=request.user)
    else:
        user_profile_form = UserProfileForm(instance=request.user)
        if PROFILE_PICTURE_ENABLED:

            profile_form = ProfilePictureForm(instance=request.user)

    # Check if user needs to select a scraped page
    show_scraped_page_prompt = False
    if not request.user.scraped_page_selected:
        available_pages = ScrapedWikiPage.objects.filter(is_imported=False).count()
        if available_pages > 0:
            show_scraped_page_prompt = True

    # Get Managed Users
    User = get_user_model()
    managed_wishlists = WishList.objects.filter(
        models.Q(owner=request.user) | models.Q(managers=request.user)
    )
    # The dependents of these wishlists, excluding the current user
    managed_users = User.objects.filter(
        stewarded_wishlists__in=managed_wishlists
    ).distinct().exclude(id=request.user.id)
    
    # Pre-initialize forms for each managed user to use in modals
    managed_users_data = [
        {'user': user, 'form': ManagedUserForm(instance=user, user=request.user)} 
        for user in managed_users
    ]
    
    new_managed_user_form = CreateManagedUserForm(user=request.user)

    context = {
        'wishlists': wishlists,
        'profile_form': profile_form,
        'user_profile_form': user_profile_form,
        'show_scraped_page_prompt': show_scraped_page_prompt,
        'PROFILE_PICTURE_ENABLED': PROFILE_PICTURE_ENABLED,
        'managed_users_data': managed_users_data,
        'new_managed_user_form': new_managed_user_form,
    }

    return render(request, 'gift/auth_profile.html', context)

@require_POST
@login_required
def create_managed_user(request):
    from .models import AllowedEmail
    User = get_user_model()
    
    form = CreateManagedUserForm(request.POST, user=request.user)
    if form.is_valid():
        user = form.save(commit=False)
        # Generate a random unusable password
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for i in range(20))
        user.set_password(password)
        user.save()
        
        # If email was provided, automatically allowlist it
        if user.email:
            AllowedEmail.objects.get_or_create(email=user.email)
        
        # Check if linking to an existing wishlist
        link_to_wishlist = form.cleaned_data.get('link_to_wishlist')
        if link_to_wishlist:
            # Check permission: user must be owner or manager
            if request.user == link_to_wishlist.owner or request.user in link_to_wishlist.managers.all():
                link_to_wishlist.dependent = user
                link_to_wishlist.save()
                messages.success(request, f"Successfully created managed user {user.username} and linked them to {link_to_wishlist.title}.")
            else:
                messages.error(request, "You do not have permission to modify the selected wishlist.")
        else:
            # Create a default wishlist for the new user so they are immediately managed
            first_name = user.first_name if user.first_name else user.username
            title = f"{first_name}'s Wishlist"
            wishlist = WishList.objects.create(
                title=title,
                owner=request.user,
                dependent=user,
                description=f"Auto-generated wishlist for {first_name}."
            )
            messages.success(request, f"Successfully created managed user {user.username} and their wishlist.")
    else:
        messages.error(request, "Error creating managed user. Please check the form.")
        
    return redirect('gift:account')

@require_POST
@login_required
def edit_managed_user(request, user_id):
    User = get_user_model()
    
    # Security check: User must manage at least one wishlist where this user_id is the dependent
    managed_wishlists = WishList.objects.filter(
        models.Q(owner=request.user) | models.Q(managers=request.user)
    )
    
    try:
        managed_user = User.objects.filter(
            id=user_id, 
            stewarded_wishlists__in=managed_wishlists
        ).distinct().exclude(id=request.user.id).get()
    except User.DoesNotExist:
        messages.error(request, "You do not have permission to edit this user.")
        return redirect('gift:account')

    form = ManagedUserForm(request.POST, instance=managed_user, user=request.user)
    if form.is_valid():
        form.save()
        
        # Handle wishlist linking/unlinking
        if 'link_to_wishlist' in form.cleaned_data:
            wishlist = form.cleaned_data['link_to_wishlist']
            if wishlist:
                # Link to new wishlist
                wishlist.dependent = managed_user
                wishlist.save()
            else:
                # Unlink from current wishlist if any
                current_wishlists = WishList.objects.filter(dependent=managed_user)
                for cw in current_wishlists:
                    cw.dependent = None
                    cw.save()
                    
        messages.success(request, f"Successfully updated details for {managed_user.username}.")
    else:
        messages.error(request, f"Error updating details for {managed_user.username}. Please check the form.")
        
    return redirect('gift:account')

@require_POST
@login_required
def password_reset_request(request):
    try:
        from gift.middleware.firebase_auth import _get_firebase_auth
        firebase_auth = _get_firebase_auth()
        
        if not firebase_auth:
            messages.error(request, "Firebase Auth is not configured. Cannot send password reset.")
            return redirect('gift:account')

        # Generate password reset link
        link = firebase_auth.generate_password_reset_link(request.user.email)
        
        # Send the reset link via Django's email system since Firebase Admin SDK
        # only generates the link but does not send an email itself.
        
        send_mail(
            "Password Reset for Gift Wiki",
            f"Hello,\n\nPlease click the following link to reset your password for Gift Wiki:\n\n{link}\n\nIf you did not request a password reset, please ignore this email.",
            getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@giftwiki.com"),
            [request.user.email],
            fail_silently=False,
        )
        
        messages.success(request, f"Password reset email sent to {request.user.email}.")
    except Exception as e:
        logger.error(f"Error sending password reset: {e}")
        messages.error(request, "There was an error sending the password reset email. Please try again later.")
        
    return redirect('gift:account')


def get_season(date, seasons):
    if not date:
        return 'Unknown'
    m = date.month
    for s in seasons:
        if s.start_month <= s.end_month:
            if s.start_month <= m <= s.end_month:
                return s.name
        else:
            if m >= s.start_month or m <= s.end_month:
                return s.name
    return 'Unknown'

# We pass seasons and request_user into the strategy to avoid N+1 queries.
def get_grouping_strategies(seasons, request_user):
    def christmas_exchange_group(wl):
        person = wl.dependent or wl.owner
        if request_user.secret_santa_target == person:
            return '🎯 Your Secret Santa Target'
        if person.is_kid:
            return '🧒 Kids'
        return '👤 Other Adults'

    strategies = {
        'house': lambda wl: wl.family_name.name if wl.family_name else 'Unassigned',
        'alpha': lambda wl: wl.title[0].upper() if wl.title else '?',
        'christmas_exchange': christmas_exchange_group,
    }

    def make_season_strategy(season_name):
        def season_strategy(wl):
            person = wl.dependent or wl.owner
            if person and get_season(person.birthday, seasons) == season_name:
                return f"{season_name} Birthdays"
            return None
        return season_strategy

    for season in seasons:
        strategies[f'season_{season.id}'] = make_season_strategy(season.name)

    return strategies


def get_upcoming_birthdays(limit=5):
    """
    Return the next `limit` upcoming birthdays across all users with a birthday set
    (managed/kid accounts are WikiUser rows, so they're included automatically),
    ordered by days until the next occurrence. Today's birthday counts as upcoming
    (days_until=0). Each entry is a dict with 'user', 'days_until', 'turning_age'
    and 'wishlist_id' (None when the person has no wishlist to link to).
    """
    today = date.today()

    def next_occurrence(birthday):
        try:
            next_birthday = birthday.replace(year=today.year)
        except ValueError:
            # Feb 29 birthdays are observed on Feb 28 in non-leap years
            next_birthday = birthday.replace(year=today.year, day=28)
        if next_birthday < today:
            try:
                next_birthday = birthday.replace(year=today.year + 1)
            except ValueError:
                next_birthday = birthday.replace(year=today.year + 1, day=28)
        return next_birthday

    upcoming = []
    for user in User.objects.filter(birthday__isnull=False):
        next_birthday = next_occurrence(user.birthday)
        upcoming.append(
            {
                'user': user,
                'days_until': (next_birthday - today).days,
                'turning_age': next_birthday.year - user.birthday.year,
                'wishlist_id': None,
            }
        )

    upcoming.sort(key=lambda entry: (entry['days_until'], entry['user'].username))
    upcoming = upcoming[:limit]

    # Link each person to their most recently updated wishlist, using the same
    # "person of the list" convention as the directory (dependent, else owner).
    person_ids = {entry['user'].id for entry in upcoming}
    if person_ids:
        candidate_lists = (
            WishList.objects.filter(
                models.Q(owner_id__in=person_ids) | models.Q(dependent_id__in=person_ids)
            )
            .select_related('owner', 'dependent')
            .order_by('-updated_at')
        )
        wishlist_by_person = {}
        for wishlist in candidate_lists:
            person = wishlist.dependent or wishlist.owner
            if person.id in person_ids and person.id not in wishlist_by_person:
                wishlist_by_person[person.id] = wishlist.id
        for entry in upcoming:
            entry['wishlist_id'] = wishlist_by_person.get(entry['user'].id)

    return upcoming


def home(request):
    # Only show wishlists if user is authenticated
    wishlists_grouped = {}
    current_grouping = 'house'
    grouping_options = []
    upcoming_birthdays = []
    unseen_changelog_entries = []

    if request.user.is_authenticated:
        # Prompt user to add birthday if missing
        if not request.user.birthday:
            messages.info(request, "Please add your birthday to your profile so others can organize gifts for you! 🎁")

        # "What's new" card: active entries this user hasn't dismissed yet
        unseen_changelog_entries = list(
            ChangelogEntry.objects.filter(is_active=True).exclude(seen_by=request.user)
        )

        # Fetch seasons once
        seasons = list(Season.objects.all())
        strategies = get_grouping_strategies(seasons, request.user)

        grouping_options = [
            {'value': 'house', 'label': 'Household'},
            {'value': 'alpha', 'label': 'Alphabetical'},
            {'value': 'christmas_exchange', 'label': 'Christmas Exchange'},
        ]
        for season in seasons:
            grouping_options.append({
                'value': f'season_{season.id}',
                'label': f'Birthday: {season.name}'
            })

        group_by = request.GET.get('group_by')
        if group_by in strategies:
            request.session['wishlist_grouping'] = group_by
            current_grouping = group_by
        else:
            current_grouping = request.session.get('wishlist_grouping')
            if not current_grouping or current_grouping not in strategies:
                if date.today().month in (11, 12):
                    current_grouping = 'christmas_exchange'
                else:
                    current_grouping = 'house'

        # Optimize query with select_related; prefetch active (non-archived, non-deleted)
        # items once so card counts don't leak surprise items to the list owner
        wishlists = (
            WishList.objects.select_related('family_name', 'owner', 'dependent')
            .prefetch_related(
                models.Prefetch(
                    'items',
                    queryset=Item.objects.filter(is_deleted=False, archived_at__isnull=True),
                    to_attr='active_items',
                )
            )
            .all()
        )
        wishlists_grouped = defaultdict(list)
        strategy = strategies[current_grouping]

        for wishlist in wishlists:
            if request.user == wishlist.owner or request.user == wishlist.dependent:
                wishlist.card_item_count = sum(
                    1 for item in wishlist.active_items if not item.is_sneaky
                )
            else:
                wishlist.card_item_count = len(wishlist.active_items)
            group_key = strategy(wishlist)
            if group_key is not None:
                wishlists_grouped[group_key].append(wishlist)
            
        # Sort the dictionary keys to have a predictable display order
        wishlists_grouped = dict(sorted(wishlists_grouped.items(), key=lambda item: str(item[0])))

        # "What's coming up": next birthdays across all users (incl. managed accounts)
        upcoming_birthdays = get_upcoming_birthdays(limit=5)

        # Check if logged in user needs to select a scraped page
        show_scraped_page_prompt = False
        if not request.user.scraped_page_selected:
            available_pages = ScrapedWikiPage.objects.filter(is_imported=False).count()
            if available_pages > 0:
                show_scraped_page_prompt = True
    else:
        show_scraped_page_prompt = False

    context = {
        'wishlists_grouped': wishlists_grouped,
        'current_grouping': current_grouping,
        'grouping_options': grouping_options,
        'show_scraped_page_prompt': show_scraped_page_prompt,
        'upcoming_birthdays': upcoming_birthdays,
        'unseen_changelog_entries': unseen_changelog_entries,
    }
    return render(request, 'gift/home.html', context)


@login_required
def changelog(request):
    """Full "What's new" history — every active entry, newest first."""
    entries = ChangelogEntry.objects.filter(is_active=True)
    return render(request, 'gift/changelog.html', {'entries': entries})


@require_POST
@login_required
def changelog_dismiss(request):
    """Mark every currently-unseen active entry as seen by the current user."""
    unseen = ChangelogEntry.objects.filter(is_active=True).exclude(seen_by=request.user)
    for entry in unseen:
        entry.seen_by.add(request.user)
    return redirect('gift:home')


@login_required
def wishlist_detail(request, wishlist_id):
    # Optimize query with select_related for owner and prefetch_related for items and categories
    wishlist = get_object_or_404(
        WishList.objects.select_related('owner', 'family_name', 'dependent'), id=wishlist_id
    )
    # Check if user is owner, steward, or manager
    is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()
    is_list_manager = is_owner or is_steward or is_manager
    # Only the true owner archives purchased gifts — the reveal is their moment
    can_archive = request.user == wishlist.owner

    # List owners/managers should NOT see purchase information or be able to mark items as purchased
    # Only other users can see and mark items as purchased

    # Priority items first; id keeps a stable order within each group.
    # Archived gifts live on the received-gifts page instead of the active list.
    items = (
        wishlist.items.filter(is_deleted=False, archived_at__isnull=True)
        .select_related('purchased_by', 'updated_by')
        .prefetch_related('categories')
        .order_by('-is_priority', 'id')
    )
    # Surprise items never reach the owner/recipient's queryset at all
    if is_owner:
        items = items.exclude(is_sneaky=True)

    # Group items by category
    items_by_category = defaultdict(list)
    uncategorized_items = []

    for item in items:
        categories = item.categories.all()
        if categories.exists():
            # Use the first category for grouping
            category = categories.first()
            items_by_category[category].append(item)
        else:
            uncategorized_items.append(item)

    # Sort categories by name alphabetically and create list of (category, items) tuples
    sorted_category_items = sorted(items_by_category.items(), key=lambda x: x[0].name.lower())

    total_count = len(items)
    purchased_count = sum(1 for item in items if item.purchased)

    try:
        return render(
            request,
            'gift/wishlist_detail.html',
            {
                'wishlist': wishlist,
                'sorted_category_items': sorted_category_items,
                'uncategorized_items': uncategorized_items,
                'is_owner': is_owner,
                'is_steward': is_steward,
                'is_manager': is_manager,
                'is_list_manager': is_list_manager,
                'can_archive': can_archive,
                'total_count': total_count,
                'purchased_count': purchased_count,
            },
        )
    except Exception as e:
        import traceback

        logger.error(f'Error rendering wishlist_detail: {e}\n{traceback.format_exc()}')
        raise


@login_required
def my_purchases(request):
    """Show every item the current user has marked as purchased, grouped by wishlist."""
    from decimal import Decimal

    items = (
        Item.objects.filter(purchased_by=request.user, is_deleted=False)
        .select_related('wishlist', 'wishlist__owner', 'wishlist__dependent')
        .order_by('-updated_at')
    )

    # Group by wishlist. Items are ordered most-recently-updated first, so groups
    # are headed by the wishlist with the most recent purchase and items within
    # each group are most recent first as well.
    purchases_by_wishlist = defaultdict(list)
    total_spend = Decimal('0.00')
    for item in items:
        purchases_by_wishlist[item.wishlist].append(item)
        if item.price is not None:
            total_spend += item.price

    context = {
        'purchases_by_wishlist': purchases_by_wishlist.items(),
        'total_spend': total_spend,
        'total_count': len(items),
    }
    return render(request, 'gift/my_purchases.html', context)


@login_required
def received_gifts(request):
    """The owner's archive of received gifts, grouped by year (newest first)."""
    items = (
        Item.objects.filter(wishlist__owner=request.user, archived_at__isnull=False)
        .select_related('wishlist', 'purchased_by')
        .order_by('-archived_at', '-id')
    )

    gifts_by_year = defaultdict(list)
    for item in items:
        gifts_by_year[item.archived_at.year].append(item)
    # Newest year first; items within each year are already newest-first
    gifts_by_year = sorted(gifts_by_year.items(), key=lambda pair: pair[0], reverse=True)

    context = {
        'gifts_by_year': gifts_by_year,
        'total_count': len(items),
    }
    return render(request, 'gift/received_gifts.html', context)


@require_POST
@login_required
def item_thank_you_toggle(request, item_id):
    """Flip the thank-you-sent flag on an archived gift (owner only, 404 otherwise)."""
    item = get_object_or_404(
        Item, id=item_id, wishlist__owner=request.user, archived_at__isnull=False
    )
    item.thank_you_sent = not item.thank_you_sent
    item.save(current_user=request.user)
    return redirect('gift:received_gifts')


@login_required
def wishlist_edit(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if user is the owner, steward, or manager
    is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()

    if not (is_owner or is_steward or is_manager):
        messages.error(request, 'You can only edit wishlists you own or manage.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    # Get existing items — archived gifts live on the received-gifts page instead
    items = wishlist.items.filter(is_deleted=False, archived_at__isnull=True)
    # Surprise items stay hidden from the owner/recipient; managers may see them
    if is_owner:
        items = items.exclude(is_sneaky=True)

    # Create wishlist form for editing title and other wishlist fields
    from .forms import WishListForm

    wishlist_form = WishListForm(request.POST or None, instance=wishlist, user=request.user)

    # Create ModelFormSet for editing existing items
    from .forms import get_item_modelformset

    ItemModelFormSet = get_item_modelformset(wishlist)

    if request.method == 'POST':
        formset = ItemModelFormSet(request.POST, queryset=items, form_kwargs={'wishlist': wishlist})

        # Validate both forms
        wishlist_form_valid = wishlist_form.is_valid()
        formset_valid = formset.is_valid()

        if wishlist_form_valid and formset_valid:
            # Save wishlist changes
            wishlist = wishlist_form.save(commit=False)

            # Handle new family creation
            new_family_name = wishlist_form.cleaned_data.get('new_family_name')
            new_family_poem = wishlist_form.cleaned_data.get('new_family_poem', '').strip()
            if new_family_name:
                from .models import Family

                # Create new family if it doesn't exist
                family_description = (
                    new_family_poem if new_family_poem else f'Family group for {new_family_name}'
                )
                family, created = Family.objects.get_or_create(
                    name=new_family_name, defaults={'description': family_description}
                )
                # Update description if family exists but poem was provided
                if not created and new_family_poem:
                    family.description = new_family_poem
                    family.save()
                wishlist.family_name = family
                if created:
                    messages.success(request, f'Created new family: {new_family_name}')

            wishlist.save()

            # Save managers (ManyToMany field needs to be saved after the instance)
            if 'managers' in wishlist_form.cleaned_data:
                wishlist.managers.set(wishlist_form.cleaned_data['managers'])

            # Handle scraped page import if selected (only on edit, not during item updates)
            scraped_page = wishlist_form.cleaned_data.get('scraped_page')
            if scraped_page:
                wishlist = import_scraped_page_to_user(
                    request.user, scraped_page, target_wishlist=wishlist
                )
                if wishlist:
                    messages.success(
                        request,
                        f'Added {scraped_page.item_count} items from "{scraped_page.title}" to wishlist!',
                    )

            # Save item changes
            for form in formset.forms:
                if form.cleaned_data.get('DELETE', False):
                    # Handle deletion (soft delete)
                    if form.instance.pk:
                        form.instance.is_deleted = True
                        form.instance.save(current_user=request.user)
                else:
                    # Save the item
                    instance = form.save(commit=False)
                    instance.wishlist = wishlist
                    instance.save(current_user=request.user)

                    # Handle category assignment
                    category = form.cleaned_data.get('category')
                    instance.categories.clear()
                    if category:
                        instance.categories.add(category)

            messages.success(request, 'Wishlist and items updated successfully.')

            # Check if "Save & Continue Editing" was clicked
            if 'save_and_continue' in request.POST:
                return redirect('gift:edit_wishlist', wishlist_id=wishlist.id)
            else:
                return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
        else:
            # Show errors if forms are invalid
            if not wishlist_form_valid:
                messages.error(request, 'Please correct the wishlist form errors.')
                logger.warning(
                    f'Wishlist form invalid for wishlist_id={wishlist_id}, '
                    f'user={request.user.email}, errors={dict(wishlist_form.errors)}'
                )
            if not formset_valid:
                messages.error(request, 'Please correct the item form errors.')
                formset_errors = [dict(form.errors) for form in formset.forms]
                non_form_errors = list(formset.non_form_errors())
                post_keys = sorted(request.POST.keys())
                logger.warning(
                    f'Item formset invalid for wishlist_id={wishlist_id}, '
                    f'user={request.user.email}, post_keys={post_keys}, '
                    f'errors={formset_errors}, non_form_errors={non_form_errors}'
                )
    else:
        formset = ItemModelFormSet(queryset=items, form_kwargs={'wishlist': wishlist})

    try:
        return render(
            request,
            'gift/wishlist_edit.html',
            {'formset': formset, 'wishlist': wishlist, 'wishlist_form': wishlist_form},
        )
    except Exception as e:
        import traceback

        logger.error(f'Error rendering wishlist_edit: {e}\n{traceback.format_exc()}')
        raise


@require_POST
@login_required
def wishlist_clear_purchased(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if user is the owner, steward, or manager
    is_owner = (request.user == wishlist.owner or request.user == wishlist.dependent)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()

    if not (is_owner or is_steward or is_manager):
        logger.warning(
            'Unauthorized wishlist clear purchased attempt',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        messages.error(request, 'You can only clear items from wishlists you own or manage.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    # Perform soft delete on purchased items
    purchased_items = wishlist.items.filter(is_deleted=False, purchased=True)
    count = purchased_items.count()
    if count > 0:
        for item in purchased_items:
            item.is_deleted = True
            item.save(current_user=request.user)
        logger.info(
            'Wishlist purchased items cleared',
            extra={'wishlist_id': wishlist_id, 'count': count, 'user': request.user.email},
        )
        messages.success(request, f'Successfully cleared {count} purchased item(s).')
    else:
        messages.info(request, 'No purchased items to clear.')

    return redirect('gift:edit_wishlist', wishlist_id=wishlist.id)


@require_POST
@login_required
def wishlist_archive_purchased(request, wishlist_id):
    """Move purchased gifts to the owner's received-gifts archive, revealing surprises."""
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Owner only — the reveal is the owner's moment; managers don't get this button
    if request.user != wishlist.owner:
        logger.warning(
            'Unauthorized wishlist archive attempt',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        messages.error(request, 'Only the list owner can archive received gifts.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    purchased_items = wishlist.items.filter(
        purchased=True, is_deleted=False, archived_at__isnull=True
    )
    count = purchased_items.count()
    if count:
        now = timezone.now()
        for item in purchased_items:
            item.archived_at = now
            item.is_sneaky = False  # Reveal surprises once the gift is received
            item.save(current_user=request.user)
        logger.info(
            'Wishlist purchased gifts archived',
            extra={'wishlist_id': wishlist_id, 'count': count, 'user': request.user.email},
        )
        messages.success(
            request,
            f'{count} gift{"s" if count != 1 else ""} moved to your received gifts.',
        )
    else:
        messages.info(request, 'No purchased gifts to archive yet.')

    return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)


@require_POST
@login_required
def wishlist_delete(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if user is the owner
    if request.user != wishlist.owner and request.user != wishlist.dependent:
        logger.warning(
            'Unauthorized wishlist delete attempt',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        messages.error(request, 'You can only delete your own wishlists.')
        return redirect('gift:home')

    logger.info('Wishlist deleted', extra={'wishlist_id': wishlist_id, 'user': request.user.email})
    # Delete the wishlist
    wishlist.delete()
    messages.success(request, 'Wishlist deleted successfully.')
    return redirect('gift:account')


@login_required
def category_edit(request, category_id):
    category = get_object_or_404(Category, id=category_id)

    # Check if user has permission to edit this category
    # User must be a member of the family that owns this category
    if category.family:
        # Check if user is in the family (either as owner of a wishlist in that family, or as a family member)
        user_wishlists = WishList.objects.filter(owner=request.user, family_name=category.family)
        if not user_wishlists.exists():
            messages.error(request, 'You can only edit categories for families you belong to.')
            # Redirect back to a relevant wishlist or home
            if request.GET.get('wishlist_id'):
                return redirect('gift:wishlist_detail', wishlist_id=request.GET.get('wishlist_id'))
            return redirect('gift:home')

    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Category updated successfully.')
                # Redirect back to wishlist if provided, otherwise home
                wishlist_id = request.GET.get('wishlist_id') or request.POST.get('wishlist_id')
                if wishlist_id:
                    return redirect('gift:wishlist_detail', wishlist_id=wishlist_id)
                return redirect('gift:home')
            except Exception as e:
                logger.error(f'Error updating category: {e}')
                messages.error(request, f'Error updating category: {str(e)}')
    else:
        form = CategoryForm(instance=category)

    # Get wishlist for back link
    wishlist = None
    if request.GET.get('wishlist_id'):
        try:
            wishlist = WishList.objects.get(id=request.GET.get('wishlist_id'))
        except WishList.DoesNotExist:
            pass

    return render(
        request,
        'gift/category_edit.html',
        {'form': form, 'category': category, 'wishlist': wishlist},
    )


@require_POST
@login_required
def category_create_ajax(request, wishlist_id):
    """Create a new category for a wishlist's family via AJAX.

    Returns JSON with the created category's id and name so the caller
    can update its dropdown without reloading the page.
    """
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Permission check: owner, dependent (steward), or manager
    is_owner = request.user == wishlist.owner or request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent

    if not (is_owner or is_manager or is_steward):
        logger.warning(
            'Unauthorized category creation attempt',
            extra={'wishlist_id': wishlist_id, 'user': request.user.email},
        )
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)

    if not wishlist.family_name:
        return JsonResponse(
            {'status': 'error', 'message': 'This wishlist does not have a family assigned.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)

    name = data.get('name', '').strip()
    if not name:
        return JsonResponse(
            {'status': 'error', 'message': 'Category name is required.'}, status=400
        )

    category, created = Category.objects.get_or_create(
        family=wishlist.family_name,
        name=name,
        defaults={'description': f'Category for {name}'},
    )

    if created:
        logger.info(
            'Category created via AJAX',
            extra={
                'category_id': category.id,
                'category_name': category.name,
                'family_id': wishlist.family_name_id,
                'wishlist_id': wishlist.id,
                'user': request.user.email,
            },
        )

    return JsonResponse(
        {
            'status': 'success',
            'category_id': category.id,
            'category_name': category.name,
            'created': created,
        }
    )
