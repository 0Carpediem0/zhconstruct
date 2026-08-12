from django.urls import path

from . import views


app_name = 'resident_portal'

urlpatterns = [
    path('login/', views.resident_login, name='login'),
    path('logout/', views.resident_logout, name='logout'),
    path('', views.home, name='home'),
    path('payments/', views.payments, name='payments'),
    path('services/', views.services, name='services'),
    path('services/<int:offering_pk>/', views.service_detail, name='service-detail'),
    path('news/', views.news, name='news'),
    path('tickets/', views.ticket_list, name='tickets'),
    path('tickets/new/', views.ticket_create, name='ticket-create'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket-detail'),
    path(
        'tickets/<int:pk>/confirm/',
        views.confirm_service_order,
        name='confirm-service-order',
    ),
    path('profile/', views.profile, name='profile'),
]
