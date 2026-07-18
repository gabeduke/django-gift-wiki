import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'giftwiki.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
import traceback

c = Client(SERVER_NAME='localhost')
User = get_user_model()

for user in User.objects.all():
    c.force_login(user)
    try:
        r = c.get('/profile/')
        if r.status_code != 200:
            print(f"User {user.username} got {r.status_code}")
            if r.status_code == 500:
                print(r.content.decode())
    except Exception as e:
        print(f"User {user.username} raised Exception:")
        traceback.print_exc()
