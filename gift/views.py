import logging
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import generic
from django.contrib import messages  # Import messages
from .models import WishList, Item
from .forms import ItemForm, ItemFormSet, WishListForm
from .utility_functions import is_owner_or_steward

logger = logging.getLogger(__name__)


# def health_check(request):
#     return HttpResponse("ok")


class WishListView(generic.ListView):
    model = WishList
    template_name = 'gift/wishlist.html'
    context_object_name = 'wishlists'


class SignUpView(generic.CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy('login')
    template_name = 'gift/signup.html'


@login_required
def add_item(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)

    # Check if the user is the owner or the steward
    if not is_owner_or_steward(request.user, wishlist):
        messages.error(request, "You don't have permission to add items to this wishlist.")
        return redirect('gift:wishlist')

    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.wishlist = wishlist
            item.save()
            messages.success(request, 'Item added successfully.')  # Add success message
            return redirect('wishlist_detail', wishlist_id=wishlist.id)
    else:
        form = ItemForm()

    return render(request, 'gift/add_item.html', {'form': form})


@login_required
def add_items_batch(request, wishlist_id):
    wishlist = get_object_or_404(WishList, id=wishlist_id)
    formset = ItemFormSet(request.POST or None)

    if not is_owner_or_steward(request.user, wishlist):
        messages.error(request, "You don't have permission to add items to this wishlist.")
        return redirect('gift:wishlist')

    if request.method == 'POST':
        if formset.is_valid():
            for form in formset:
                item = form.save(commit=False)
                item.wishlist = wishlist
                item.save()
            messages.success(request, 'Items added in batch successfully.')  # Add success message
            return redirect('wishlist_detail', wishlist_id=wishlist.id)

    return render(request, 'gift/add_items_batch.html', {'formset': formset})


@login_required
def edit_item(request, item_id):
    item = get_object_or_404(Item, id=item_id)

    if not is_owner_or_steward(request.user, item):
        messages.error(request, "You don't have permission to add items to this wishlist.")
        return redirect('gift:wishlist')

    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Item updated successfully.')  # Add success message
            return redirect('wishlist_detail', wishlist_id=item.wishlist.id)
    else:
        form = ItemForm(instance=item)

    return render(request, 'gift/edit_item.html', {'form': form, 'item': item})


@login_required
def delete_item(request, item_id):
    item = get_object_or_404(Item, id=item_id)

    if not is_owner_or_steward(request.user, item):
        messages.error(request, "You don't have permission to add items to this wishlist.")
        return redirect('gift:wishlist')

    wishlist_id = item.wishlist.id
    item.is_deleted = True
    item.save()
    messages.success(request, 'Item deleted successfully.')  # Add success message
    return redirect('wishlist_detail', wishlist_id)


@login_required
def purchase_item(request, item_id):
    item = get_object_or_404(Item, id=item_id)
    if request.user != item.wishlist.owner:
        item.purchased_by = request.user
        item.save()
        messages.success(request, 'Item marked as purchased.')  # Add success message
    else:
        messages.error(request, 'You cannot purchase items from your own wishlist.')  # Add error message
    return redirect('gift/wishlist_detail', item.wishlist.id)


@login_required
def create_wishlist(request):
    if WishList.objects.filter(owner=request.user).exists():
        messages.error(request, 'You already own a wishlist.')
        return redirect('gift:landing_page')

    if request.method == 'POST':
        form = WishListForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            wishlist = form.save(commit=False)
            wishlist.owner = request.user
            steward = form.cleaned_data.get('steward')
            if steward:
                wishlist.steward = steward
            wishlist.save()
            messages.success(request, 'Wishlist created successfully.')
            return redirect('gift:add_items_batch', wishlist_id=wishlist.id)
        else:
            logger.error(form.errors)
    else:
        form = WishListForm(user=request.user)
    return render(request, 'gift/create_wishlist.html', {'form': form})


@login_required
def account_settings(request):
    # Get all lists where the user is the owner or the steward
    wishlists = WishList.objects.filter(owner=request.user) | WishList.objects.filter(steward=request.user)

    context = {
        'wishlists': wishlists
    }

    return render(request, 'gift/account_settings.html', context)


def landing_page(request):
    wishlists = WishList.objects.all()
    wishlists_by_family = defaultdict(list)

    for wishlist in wishlists:
        wishlists_by_family[wishlist.family_category].append(wishlist)

    context = {
        'wishlists_by_family': dict(wishlists_by_family)
    }
    return render(request, 'gift/landing_page.html', context)


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
