from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import InternalAuthenticationForm


app_name = 'dashboard'

urlpatterns = [
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='dashboard/login.html',
            authentication_form=InternalAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', views.home, name='home'),
    path('tickets/', views.ticket_list, name='ticket-list'),
    path('tickets/new/', views.ticket_create, name='ticket-create'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket-detail'),
    path(
        'tickets/<int:pk>/assign-provider/',
        views.ticket_assign_provider,
        name='ticket-assign-provider',
    ),
    path(
        'tickets/<int:pk>/assign-employee/',
        views.ticket_assign_employee,
        name='ticket-assign-employee',
    ),
    path(
        'tickets/<int:pk>/change-status/',
        views.ticket_change_status,
        name='ticket-change-status',
    ),
    path('directories/', views.directories, name='directories'),
]
