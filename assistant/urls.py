from django.urls import path

from assistant import views

app_name = 'assistant'
urlpatterns = [
    path('message/', views.message, name='message'),
]
