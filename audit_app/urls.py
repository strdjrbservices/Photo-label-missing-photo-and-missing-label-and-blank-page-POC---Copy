from django.urls import path
from . import views

urlpatterns = [
    path('', views.index_view, name='audit_index'),
    path('audit/create/', views.audit_create_view, name='audit_create'),
    path('audit/<int:audit_id>/', views.audit_detail_view, name='audit_detail'),
    path('audit/<int:audit_id>/delete/', views.audit_delete_view, name='audit_delete'),
    path('audit/quick-sample/<path:sample_name>/', views.quick_sample_audit_view, name='quick_sample_audit'),
]
