# forms.py

from django import forms
from django.contrib.auth.models import User
from django.forms import formset_factory
from .models import Item, WishList, Suggestion


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'description', 'price']

    def save(self, commit=True, *args, **kwargs):
        current_user = kwargs.pop('current_user', None)
        instance = super(ItemForm, self).save(commit=False)
        if current_user:
            instance.updated_by = current_user
        if commit:
            instance.save()
        return instance


ItemFormSet = formset_factory(ItemForm, extra=3)  # Adjust 'extra' for default number of forms


class SuggestionForm(forms.ModelForm):
    class Meta:
        model = Suggestion
        fields = ['name', 'hyperlink', 'description', 'image', 'suggested_price']


class WishListForm(forms.ModelForm):
    steward = forms.ModelChoiceField(
        queryset=User.objects.all(),  # Include all users
        required=False,
        label="Proxy"
    )

    class Meta:
        model = WishList
        fields = ['title', 'description', 'image', 'family_category', 'dependent']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(WishListForm, self).__init__(*args, **kwargs)
        if user:
            # Set the default steward to the current user
            self.fields['dependent'].initial = user.id
            self.fields['dependent'].queryset = User.objects.all()
