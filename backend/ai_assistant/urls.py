from django.urls import path

from . import views


app_name = 'ai_assistant'

urlpatterns = [
    path('', views.chat, name='chat'),
    path('analyze/', views.analyze, name='analyze'),
    path('create-ticket/', views.create_ticket, name='create-ticket'),
]

