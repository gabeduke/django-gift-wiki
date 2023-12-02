# forms.py

from django import forms
from django.contrib.auth.models import User
from django.forms import formset_factory
from .models import Item, WishList


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'description', 'price']


ItemFormSet = formset_factory(ItemForm, extra=3)  # Adjust 'extra' for default number of forms


class WishListForm(forms.ModelForm):
    steward = forms.ModelChoiceField(
        queryset=User.objects.all(),  # Include all users
        required=False,
        label="Steward"
    )

    class Meta:
        model = WishList
        fields = ['title', 'description', 'image', 'family_category', 'steward']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(WishListForm, self).__init__(*args, **kwargs)
        if user:
            # Set the default steward to the current user
            self.fields['steward'].initial = user.id
            self.fields['steward'].queryset = User.objects.all()
