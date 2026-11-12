"""The tools the MCP server offers.

Plain functions: no HTTP, no language-model awareness. Each takes the acting
`user` first, and that user always comes from the credential the request was
made with — never from an argument the model could fill in. There is therefore no
request a model can express, however it has been manipulated, that means "act as
someone else" or "show me what is hidden from me". Those requests aren't refused;
they can't be said.

What a person may see is decided by `gift.services`, the same functions the web
pages use. Nothing in this file re-implements a visibility rule.

Deliberately missing: anything that edits, deletes or marks an item purchased.
The worst a successful prompt injection can do through these tools is add a junk
item that someone removes with one tap.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import Q
from django.urls import reverse

from gift.models import WishList
from gift.services import (
    ItemProblem,
    active_items_visible_to,
    added_message,
    can_add_openly,
    create_item_for,
    person_display_name,
    shows_purchases_to,
)

LIST_ITEM_LIMIT = 200
SEARCH_LIMIT = 50


class ToolError(Exception):
    """Something the caller got wrong and can fix. The message goes back to the model."""


@dataclass(frozen=True)
class Context:
    """What a tool needs to know about the request besides who is asking."""

    origin: str  # https://giftwiki.leetserve.com — for links back into the app


READ = {
    'readOnlyHint': True,
    'destructiveHint': False,
    'idempotentHint': True,
    'openWorldHint': False,
}
ADD = {
    'readOnlyHint': False,
    'destructiveHint': False,
    'idempotentHint': False,
    'openWorldHint': False,
}


def _lists():
    return WishList.objects.select_related('owner', 'dependent').prefetch_related('managers')


def _list_or_error(wishlist_id):
    try:
        return _lists().get(pk=wishlist_id)
    except WishList.DoesNotExist:
        raise ToolError('No list has that id. Call list_wishlists to see the ids.') from None


def _person(wishlist):
    return wishlist.dependent or wishlist.owner


def _role(wishlist, user):
    # Owner-side people (the owner, the person the list is kept for, and managers) add
    # ordinary items and never see which items are bought; everyone else is shopping.
    # Surprises are a separate rule, applied by active_items_visible_to: hidden from the
    # owner and the dependent, but visible to a manager (as on the wishlist page).
    return 'owner-side' if can_add_openly(wishlist, user) else 'gift-giver'


def _list_url(ctx, wishlist):
    return ctx.origin + reverse('gift:wishlist_detail', args=[wishlist.id])


def _item_out(item, shows_purchases):
    entry = {
        'id': item.id,
        'name': item.name,
        'description': item.description,
        'link': item.url or None,
        'price': str(item.price) if item.price is not None else None,
        'price_range': item.price_range,
        'most_wanted': item.is_priority,
    }
    if shows_purchases:
        entry['purchased'] = item.purchased
    if item.is_sneaky:
        entry['surprise'] = True
        entry['added_by'] = person_display_name(item.added_by)
    return entry


# --- tools --------------------------------------------------------------------


def list_wishlists(user, args, ctx):
    rows = []
    for wishlist in _lists():
        person = _person(wishlist)
        rows.append(
            {
                'id': wishlist.id,
                'title': wishlist.title,
                'person': person_display_name(person),
                'for_me': person == user,
                'you_are': _role(wishlist, user),
                'item_count': active_items_visible_to(wishlist, user).count(),
                'url': _list_url(ctx, wishlist),
            }
        )
    rows.sort(key=lambda row: (row['person'].lower(), row['title'].lower()))
    return {'wishlists': rows}


def get_wishlist(user, args, ctx):
    wishlist = _list_or_error(args['wishlist_id'])
    shows = shows_purchases_to(wishlist, user)
    items = (
        active_items_visible_to(wishlist, user)
        .select_related('added_by')
        .order_by('-is_priority', 'id')[:LIST_ITEM_LIMIT]
    )
    return {
        'id': wishlist.id,
        'title': wishlist.title,
        'person': person_display_name(_person(wishlist)),
        'you_are': _role(wishlist, user),
        'url': _list_url(ctx, wishlist),
        'items': [_item_out(item, shows) for item in items],
    }


def search_items(user, args, ctx):
    query = args['query'].strip()
    if not query:
        raise ToolError('Give something to search for.')
    only_unbought = args.get('unpurchased_only', False)

    if args.get('wishlist_id') is not None:
        lists = [_list_or_error(args['wishlist_id'])]
    else:
        lists = list(_lists())

    results = []
    ignored_filter = False
    truncated = False
    for wishlist in lists:
        shows = shows_purchases_to(wishlist, user)
        items = active_items_visible_to(wishlist, user).filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
        if only_unbought:
            if shows:
                items = items.exclude(purchased=True)
            else:
                # Filtering by purchase status on a list the person owns would reveal
                # which items were bought just by what disappears. So don't.
                ignored_filter = True
        for item in items.select_related('added_by').order_by('-is_priority', 'id'):
            if len(results) >= SEARCH_LIMIT:
                truncated = True
                break
            entry = _item_out(item, shows)
            entry['list'] = {
                'id': wishlist.id,
                'title': wishlist.title,
                'person': person_display_name(_person(wishlist)),
            }
            results.append(entry)
        if truncated:
            break

    out = {'items': results, 'truncated': truncated}
    if ignored_filter:
        out['note'] = (
            'unpurchased_only was ignored for lists that are yours: whether an item has '
            'been bought is hidden from you there.'
        )
    return out


def add_item(user, args, ctx):
    wishlist = _list_or_error(args['wishlist_id'])
    name = (args['name'] or '').strip()

    if not args.get('allow_duplicate', False):
        existing = active_items_visible_to(wishlist, user).filter(name__iexact=name).first()
        if existing:
            return {
                'added': False,
                'reason': 'already_on_the_list',
                'existing': {'id': existing.id, 'name': existing.name},
                'message': (
                    f'“{existing.name}” is already on {wishlist.title}, so nothing was added. '
                    'Pass allow_duplicate=true only if they really want a second one.'
                ),
            }

    try:
        item = create_item_for(user, wishlist, name, args.get('url'), args.get('description'))
    except ItemProblem as problem:
        raise ToolError(str(problem)) from None

    return {
        'added': True,
        'id': item.id,
        'name': item.name,
        'surprise': item.is_sneaky,
        'list': {
            'id': wishlist.id,
            'title': wishlist.title,
            'person': person_display_name(_person(wishlist)),
            'url': _list_url(ctx, wishlist),
        },
        'message': added_message(wishlist, item),
    }


# --- registry -----------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict
    annotations: dict
    run: Callable


def _schema(properties, required=()):
    return {
        'type': 'object',
        'properties': properties,
        'required': list(required),
        'additionalProperties': False,
    }


WISHLIST_ID = {'type': 'integer', 'description': 'A list id from list_wishlists.'}

TOOLS = [
    Tool(
        name='list_wishlists',
        title='List wishlists',
        description=(
            'Every list in the family, with whose it is, how many items you can see on it, and '
            "whether you are 'owner-side' (the owner, the person it is kept for, or a manager) or "
            "a 'gift-giver'. Start here to find a list id."
        ),
        input_schema=_schema({}),
        annotations=READ,
        run=list_wishlists,
    ),
    Tool(
        name='get_wishlist',
        title='Get a wishlist',
        description=(
            "The items on one list, as you are allowed to see them. On other people's lists "
            'that includes surprise gifts and which items are already bought. On your own lists '
            'it never shows surprises or purchases.'
        ),
        input_schema=_schema({'wishlist_id': WISHLIST_ID}, required=['wishlist_id']),
        annotations=READ,
        run=get_wishlist,
    ),
    Tool(
        name='search_items',
        title='Search items',
        description=(
            'Find items by words in their name or note, across every list or just one. '
            'Set unpurchased_only to skip things already bought (only works on other '
            "people's lists)."
        ),
        input_schema=_schema(
            {
                'query': {'type': 'string', 'maxLength': 100},
                'wishlist_id': WISHLIST_ID,
                'unpurchased_only': {'type': 'boolean'},
            },
            required=['query'],
        ),
        annotations=READ,
        run=search_items,
    ),
    Tool(
        name='add_item',
        title='Add an item',
        description=(
            'Add an item to a list. On your own list (or one you manage) it is an ordinary '
            "item. On anyone else's list it is automatically a surprise the list's owner can't "
            'see; the result says which. Refuses an item already on the list unless '
            'allow_duplicate is true.'
        ),
        input_schema=_schema(
            {
                'wishlist_id': WISHLIST_ID,
                'name': {'type': 'string', 'maxLength': 255},
                'url': {'type': 'string', 'description': 'A link to the product page.'},
                'description': {'type': 'string', 'maxLength': 2000, 'description': 'A note.'},
                'allow_duplicate': {'type': 'boolean'},
            },
            required=['wishlist_id', 'name'],
        ),
        annotations=ADD,
        run=add_item,
    ),
]

BY_NAME = {tool.name: tool for tool in TOOLS}

_TYPES = {'string': str, 'integer': int, 'boolean': bool}


def check_arguments(schema, args):
    """Reject arguments that don't fit the tool's schema, with a message the model can act on."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError('Arguments must be an object.')
    props = schema['properties']
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ToolError(f'Unknown argument: {", ".join(unknown)}.')
    for key in schema['required']:
        if key not in args or args[key] is None:
            raise ToolError(f'Missing required argument: {key}.')
    for key, value in args.items():
        spec = props[key]
        expected = _TYPES[spec['type']]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ToolError(f'Argument {key} must be a {spec["type"]}.')
        if spec['type'] == 'string' and len(value) > spec.get('maxLength', 10_000):
            raise ToolError(f'Argument {key} is too long (max {spec.get("maxLength", 10_000)}).')
    return args


def call_tool(name, args, user, ctx):
    """Run a tool for `user`. Raises KeyError for an unknown name, ToolError for bad input."""
    tool = BY_NAME[name]
    return tool.run(user, check_arguments(tool.input_schema, args), ctx)
