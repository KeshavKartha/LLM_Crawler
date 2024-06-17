from django.urls import path
from . import views

urlpatterns = [
    path('scrape/', views.ScrapeView.as_view(), name='scrape'),
]
