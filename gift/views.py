import json
import logging
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import generic

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

from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from .forms import (
    CategoryForm,
    CustomUserCreationForm,
    ItemForm,
    ScrapedPageSelectionForm,
    WishListForm,
)
from .models import Category, Item, ScrapedWikiItem, ScrapedWikiPage, WishList, Season

logger = logging.getLogger(__name__)

User = get_user_model()


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
        is_owner = request.user == wishlist.owner
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
    is_owner = request.user == wishlist.owner
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


@login_required
def item_edit(request, item_id):
    item = get_object_or_404(Item, id=item_id)

    # Business Rule: Only owner or managers can edit items
    is_owner = request.user == item.wishlist.owner
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
    item = get_object_or_404(Item, id=item_id)

    # Business Rule: Only owner or managers can delete items
    is_owner = request.user == item.wishlist.owner
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
    item = get_object_or_404(Item, id=item_id)
    wishlist = item.wishlist

    # Check if user is owner, steward, or manager
    is_owner = request.user == wishlist.owner
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
            if wishlist.owner != user:
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
    # Get all lists where the user is the owner - optimize with select_related
    wishlists = WishList.objects.filter(owner=request.user).select_related(
        'family_name', 'owner', 'dependent'
    )

    # Optionally include wishlists where user is the steward (if feature enabled)
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    if STEWARD_PROXY_ENABLED:
        stewarded = WishList.objects.filter(dependent=request.user).select_related(
            'family_name', 'owner', 'dependent'
        )
        wishlists = wishlists | stewarded

    # Handle profile picture upload (only if feature enabled)
    from giftwiki.feature_flags import get_profile_picture_enabled

    PROFILE_PICTURE_ENABLED = get_profile_picture_enabled()
    profile_form = None

    if PROFILE_PICTURE_ENABLED:
        from .forms import ProfilePictureForm

        if request.method == 'POST' and 'update_profile_picture' in request.POST:
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

    # Check if user needs to select a scraped page
    show_scraped_page_prompt = False
    if not request.user.scraped_page_selected:
        available_pages = ScrapedWikiPage.objects.filter(is_imported=False).count()
        if available_pages > 0:
            show_scraped_page_prompt = True

    context = {
        'wishlists': wishlists,
        'profile_form': profile_form,
        'show_scraped_page_prompt': show_scraped_page_prompt,
        'PROFILE_PICTURE_ENABLED': PROFILE_PICTURE_ENABLED,
    }

    return render(request, 'gift/auth_profile.html', context)


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

    return {
        'house': lambda wl: wl.family_name.name if wl.family_name else 'Unassigned',
        'alpha': lambda wl: wl.title[0].upper() if wl.title else '?',
        'birthday_season': lambda wl: get_season(wl.owner.birthday, seasons) if wl.owner else 'Unknown',
        'christmas_exchange': christmas_exchange_group,
    }

def home(request):
    # Only show wishlists if user is authenticated
    wishlists_grouped = {}
    current_grouping = 'house'

    if request.user.is_authenticated:
        # Fetch seasons once
        seasons = list(Season.objects.all())
        strategies = get_grouping_strategies(seasons, request.user)

        group_by = request.GET.get('group_by')
        if group_by in strategies:
            request.session['wishlist_grouping'] = group_by
            current_grouping = group_by
        else:
            current_grouping = request.session.get('wishlist_grouping')
            if not current_grouping or current_grouping not in strategies:
                from datetime import date
                if date.today().month in (11, 12):
                    current_grouping = 'christmas_exchange'
                else:
                    current_grouping = 'house'

        # Optimize query with select_related
        wishlists = WishList.objects.select_related('family_name', 'owner').all()
        wishlists_grouped = defaultdict(list)
        strategy = strategies[current_grouping]

        for wishlist in wishlists:
            wishlists_grouped[strategy(wishlist)].append(wishlist)
            
        # Sort the dictionary keys to have a predictable display order
        wishlists_grouped = dict(sorted(wishlists_grouped.items(), key=lambda item: str(item[0])))

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
        'show_scraped_page_prompt': show_scraped_page_prompt,
    }
    return render(request, 'gift/home.html', context)


@login_required
def wishlist_detail(request, wishlist_id):
    # Optimize query with select_related for owner and prefetch_related for items and categories
    wishlist = get_object_or_404(
        WishList.objects.select_related('owner', 'family_name', 'dependent'), id=wishlist_id
    )
    items = (
        wishlist.items.filter(is_deleted=False)
        .select_related('purchased_by', 'updated_by')
        .prefetch_related('categories')
    )

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

    # Check if user is owner, steward, or manager
    is_owner = request.user == wishlist.owner
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()
    is_list_manager = is_owner or is_steward or is_manager

    # List owners/managers should NOT see purchase information or be able to mark items as purchased
    # Only other users can see and mark items as purchased

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
                'total_count': total_count,
                'purchased_count': purchased_count,
            },
        )
    except Exception as e:
        import traceback

        logger.error(f'Error rendering wishlist_detail: {e}\n{traceback.format_exc()}')
        raise


@login_required
def wishlist_edit(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if user is the owner, steward, or manager
    is_owner = request.user == wishlist.owner
    from giftwiki.feature_flags import get_steward_proxy_enabled

    STEWARD_PROXY_ENABLED = get_steward_proxy_enabled()
    is_steward = STEWARD_PROXY_ENABLED and request.user == wishlist.dependent
    is_manager = request.user in wishlist.managers.all()

    if not (is_owner or is_steward or is_manager):
        messages.error(request, 'You can only edit wishlists you own or manage.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    # Get existing items
    items = wishlist.items.filter(is_deleted=False)

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
                    new_category_name = form.cleaned_data.get('new_category_name')
                    instance.categories.clear()

                    # Handle "Create new..." option
                    if category == '__CREATE_NEW__':
                        if new_category_name and wishlist.family_name:
                            from .models import Category

                            category_obj, created = Category.objects.get_or_create(
                                name=new_category_name,
                                family=wishlist.family_name,
                                defaults={'description': f'Category for {new_category_name}'},
                            )
                            instance.categories.add(category_obj)
                    elif new_category_name and wishlist.family_name:
                        # If new category name provided, create it (takes precedence over selected category)
                        from .models import Category

                        category_obj, created = Category.objects.get_or_create(
                            name=new_category_name,
                            family=wishlist.family_name,
                            defaults={'description': f'Category for {new_category_name}'},
                        )
                        instance.categories.add(category_obj)
                    elif category and category != '__CREATE_NEW__':
                        # Use the selected existing category
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
            if not formset_valid:
                messages.error(request, 'Please correct the item form errors.')
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
    is_owner = request.user == wishlist.owner
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
def wishlist_delete(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if user is the owner
    if request.user != wishlist.owner:
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
