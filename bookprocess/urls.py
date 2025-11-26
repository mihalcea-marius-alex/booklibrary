"""URL configuration for the :mod:`bookprocess` app.

This module exposes the app's public URL patterns. The patterns are
simple function-based view endpoints used by the frontend/admin to
list books and view book details.
"""

from django.urls import path
from . import views


urlpatterns = [
        path('books/', views.books_list_view, name='books-list'),
        path('books/<int:book_id>/', views.book_detail_view, name='book-detail'),
]
