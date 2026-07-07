from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('organizations/', views.organizations_view, name='organizations'),
    path('organizations/add/', views.organization_add, name='organization_add'),
    path('organizations/edit/', views.organization_edit, name='organization_edit'),
    path('machines/', views.machines_view, name='machines'),
    path('machines/add/', views.machine_add, name='machine_add'),
    path('machines/edit/', views.machine_edit, name='machine_edit'),
    path('users/', views.users_view, name='users'),
    path('users/action/', views.user_action, name='user_action'),
    path('issues/', views.issues_view, name='issues'),
    path('issues/next-status/', views.issue_next_status, name='issue_next_status'),
    path('issues/topic/add/', views.topic_add, name='topic_add'),
    path('issues/topic/delete/', views.topic_delete, name='topic_delete'),
    path('statistics/', views.statistics_view, name='statistics'),
    path('statistics/export/', views.statistics_export, name='statistics_export'),
]
