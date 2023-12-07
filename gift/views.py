import json
import logging
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import generic
from django.contrib import messages  # Import messages
from .models import WishList, Item
from .forms import ItemForm, ItemFormSet, WishListForm
from django.core.exceptions import ValidationError

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Item

logger = logging.getLogger(__name__)


class SignUpView(generic.CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy('gift:login')
    template_name = 'gift/auth_signup.html'


@require_POST
@login_required
def item_add_ajax(request, wishlist_id):
    try:
        data = json.loads(request.body)
        wishlist = get_object_or_404(WishList, id=wishlist_id)

        # Create a new item
        item = Item(name=data['name'], wishlist=wishlist)
        # Set other fields as necessary
        item.save()

        # Return the new item details
        return JsonResponse({'id': item.id, 'name': item.name})
    except Exception as e:
        # Log the exception for debugging
        print(e)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def item_add(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.wishlist = wishlist
            item.save(current_user=request.user)
            messages.success(request, 'Item added successfully.')  # Add success message
            return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
    else:
        form = ItemForm()

    return render(request, 'gift/item_add.html', {'form': form})




@login_required
def item_edit(request, item_id):
    item = get_object_or_404(Item, id=item_id)

    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save(current_user=request.user)
            messages.success(request, 'Item updated successfully.')  # Add success message
            return redirect('wishlist_detail', wishlist_id=item.wishlist.id)
    else:
        form = ItemForm(instance=item)

    return render(request, 'gift/item_edit.html', {'form': form, 'item': item})


@login_required
def item_delete(request, item_id):
    item = get_object_or_404(Item, id=item_id)

    wishlist_id = item.wishlist.id
    item.is_deleted = True
    item.save(current_user=request.user)
    messages.success(request, 'Item deleted successfully.')  # Add success message
    return redirect('wishlist_detail', wishlist_id)


@login_required
def item_purchase(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    if request.user != item.wishlist.owner:
        if item.purchased_by is None:
            item.purchased_by = request.user
        item.save(current_user=request.user)
        messages.success(request, 'Item marked as purchased.')  # Add success message
    else:
        messages.error(request, 'You cannot purchase items from your own wishlist.')  # Add error message
    return redirect('gift/wishlist_detail', item.wishlist.id)


@login_required
def wishlist_create(request):
    if request.method == 'POST':
        form = WishListForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            try:
                wishlist = form.save(commit=False)

                is_for_external_user = form.cleaned_data.get('is_for_external_user')
                if is_for_external_user:
                    wishlist.family_category = form.cleaned_data.get('family_category')
                    external_user = create_or_select_external_user(form.cleaned_data)
                    wishlist.owner = external_user
                    if wishlist.steward is None:
                        wishlist.steward = request.user
                else:
                    wishlist.owner = request.user

                wishlist.save()
            except ValidationError as e:
                logger.error(e)
                messages.error(request, e.message)
                return redirect('home')
            messages.success(request, 'Wishlist created successfully.')
            return redirect('gift:add_items_batch', wishlist_id=wishlist.id)
        else:
            logger.error(form.errors)
    else:
        form = WishListForm(user=request.user)
    return render(request, 'gift/wishlist_create.html', {'form': form})


def create_or_select_external_user(user_name, family_category):
    if not user_name or not family_category:
        raise ValidationError('Both user name and family category are required.')

    # Create the external user identifier
    external_user_identifier = f"{user_name}_{family_category}"

    # Check if an external user with this identifier already exists
    existing_user = User.objects.filter(username=external_user_identifier).first()
    if existing_user:
        return existing_user

    # If not, create a new external user
    new_user = User.objects.create_user(
        username=external_user_identifier,
        # Set other necessary fields, like a default password, email, etc.
        # Since it's a proxy user, you might want to handle authentication and permissions accordingly
    )
    return new_user


@login_required
def profile(request):
    # Get all lists where the user is the owner or the steward
    wishlists = WishList.objects.filter(owner=request.user) | WishList.objects.filter(steward=request.user)

    context = {
        'wishlists': wishlists
    }

    return render(request, 'gift/auth_profile.html', context)


def home(request):
    wishlists = WishList.objects.all()
    wishlists_by_family = defaultdict(list)

    for wishlist in wishlists:
        wishlists_by_family[wishlist.family_category].append(wishlist)

    context = {
        'wishlists_by_family': dict(wishlists_by_family)
    }
    return render(request, 'gift/home.html', context)


@login_required
def wishlist_detail(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)
    items = wishlist.items.filter(is_deleted=False)

    # Check if the user is the owner or the steward
    if request.user == wishlist.owner or request.user == wishlist.steward:
        can_view_purchased = True
    else:
        can_view_purchased = False
        for item in items:
            item.purchased_by = None

    return render(request, 'gift/wishlist_detail.html',
                  {'wishlist': wishlist, 'items': items, 'can_view_purchased': can_view_purchased})


@login_required
def wishlist_edit(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)
    formset = ItemFormSet(request.POST or None)

    if request.method == 'POST':
        if formset.is_valid():
            for form in formset:
                item = form.save(commit=False)
                item.wishlist = wishlist
                item.save(current_user=request.user)
            messages.success(request, 'Items added in batch successfully.')  # Add success message
            return redirect('wishlist_detail', wishlist_id=wishlist.id)

    return render(request, 'gift/wishlist_edit.html', {'formset': formset})


def wishlist_delete(request):
    return None
