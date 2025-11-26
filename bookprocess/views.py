"""Views for the public-facing book listing and detail pages.

These simple function-based views are intentionally thin: they
prepare the queryset and context used by the templates and delegate
presentation to the HTML templates under ``books/``.

The views support basic filtering, search and pagination. They are
designed for use in the site's frontend and admin preview pages.
"""

from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Book, Genre, Nationality


def books_list_view(request):
    """Render a paginated list of books with optional filters and search.

    The view reads several optional GET parameters from ``request.GET``:

    - ``search``: a free-text search applied to title, ISBN and author
      names (case-insensitive, partial matches).
    - ``genre``: a numeric genre id to filter the list by genre.
    - ``adapted``: when set to ``'true'`` filters books marked as
      adapted.
    - ``nationality``: an author nationality id to filter books by the
      primary author's nationality.
    - ``per_page``: number of results per page (allowed values: 10, 25,
      50). Defaults to 10 for invalid input.
    - ``page``: page number for pagination.

    Parameters
    ----------
    request : django.http.HttpRequest
        The incoming request object containing GET parameters.

    Returns
    -------
    django.http.HttpResponse
        A rendered template response using ``books/books_list.html`` and a
        context containing ``page_obj``, ``genres``, ``nationalities`` and
        the applied filters.
    """
    books = Book.objects.all().prefetch_related('bookauthor_set__author__nationality', 'genre').order_by('-id')

    search_query = request.GET.get('search', '').strip()
    if search_query:
        books = books.filter(
            Q(title__icontains=search_query) |
            Q(isbn__icontains=search_query) |
            Q(bookauthor__author__first_name__icontains=search_query) |
            Q(bookauthor__author__last_name__icontains=search_query)
        ).distinct()

    genre_filter = request.GET.get('genre', '').strip()
    if genre_filter:
        books = books.filter(genre_id=genre_filter)

    adapted_filter = request.GET.get('adapted', '').strip()
    if adapted_filter:
        books = books.filter(adapted=adapted_filter == 'true')

    nationality_filter = request.GET.get('nationality', '').strip()
    if nationality_filter:
        books = books.filter(bookauthor__author__nationality_id=nationality_filter).distinct()

    genres = Genre.objects.all().order_by('name')

    nationalities = Nationality.objects.all().order_by('name')

    per_page = request.GET.get('per_page', '10')
    try:
        per_page = int(per_page)
        if per_page not in [10, 25, 50]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(books, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'genres': genres,
        'nationalities': nationalities,
        'search_query': search_query,
        'genre_filter': genre_filter,
        'adapted_filter': adapted_filter,
        'nationality_filter': nationality_filter,
        'per_page': str(per_page),
    }

    return render(request, 'books/books_list.html', context)


def book_detail_view(request, book_id):
    """Render a detailed page for a specific book.

    Parameters
    ----------
    request : django.http.HttpRequest
        The incoming request object.
    book_id : int
        Primary key of the requested book.

    Returns
    -------
    django.http.HttpResponse
        A rendered template response using ``books/book_detail.html`` with
        ``book`` in the context.
    """
    book = get_object_or_404(
        Book.objects.prefetch_related('bookauthor_set__author__nationality', 'genre'),
        id=book_id
    )

    context = {
        'book': book,
    }

    return render(request, 'books/book_detail.html', context)
