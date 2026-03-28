
file_path = '/Users/gabeduke/repos/django-gift-wiki/gift/templates/gift/wishlist_detail.html'

with open(file_path) as f:
    content = f.read()

# Fix the specific split tag issue
fixed_content = content.replace(
    'Mark as Purchased{%\n                        endif %}', 'Mark as Purchased{% endif %}'
)
fixed_content = fixed_content.replace(
    'Mark as Purchased{%\n                        endif %}', 'Mark as Purchased{% endif %}'
)

# Also generic fix for any other similar occurrences just in case of whitespace variations
import re

fixed_content = re.sub(
    r'Mark as Purchased\{%\s*\n\s*endif %\}', 'Mark as Purchased{% endif %}', fixed_content
)

if content == fixed_content:
    print('Content did not change! The pattern might not match.')
    # Debug print around the area
    idx = content.find('Mark as Purchased{%')
    if idx != -1:
        print('Found occurrence at:', idx)
        print('Surrounding text repr:', repr(content[idx : idx + 50]))
else:
    with open(file_path, 'w') as f:
        f.write(fixed_content)
    print('Successfully wrote fixed content.')
