"""Database models for the bookprocess application.

This module defines the core data models used by the application:
- ``Nationality`` -- country/nationality lookup
- ``Genre`` -- book genre
- ``Author`` -- book author
- ``Book`` -- main book record
- ``BookAuthor`` -- through model to order book authors
- ``Statistic`` -- simple JSON-backed statistics container
"""

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.db import models
from django.core.validators import RegexValidator

from .utils import generate_unique_isbn_from_book

User = get_user_model()
isbn_validator = RegexValidator(
    regex=r"^\d{13}$",
    message="ISBN must be a 13-digit string (digits only).",
    code="invalid_isbn",
)

class Nationality(models.Model):
    """A country or nationality used to classify authors."""
    name = models.CharField(max_length=100, unique=True) #: Human-readable name of the nationality (unique).
    code = models.CharField(max_length=3, unique=True) #: ISO-like short code for the nationality (unique, max length 3).

    class Meta:
        """Model metadata for :class:`Nationality`."""
        verbose_name_plural = "Nationalities" #: admin-friendly plural name.
        ordering = ['name'] #: Default ordering used by querysets and the admin changelist

    def __str__(self):
        """Return the human-readable name for the nationality.

        Returns
        -------
        str
            The nationality's name.
        """
        return f"{self.name}"


auditlog.register(Nationality)


class Genre(models.Model):
    """A book genre/category."""
    name = models.CharField(max_length=100, unique=True) #: Name of the genre (unique).

    class Meta:
        """Model metadata for :class:`Genre`."""
        ordering = ['name'] #: Default ordering for querysets (by genre name).

    def __str__(self):
        """Return the genre name.

        Returns
        -------
        str
            The genre's human readable name.
        """
        return f"{self.name}"


auditlog.register(Genre)


class Author(models.Model):
    """An author of books in the library."""
    first_name = models.CharField(max_length=100) #: Given name of the author.
    last_name = models.CharField(max_length=100) #: Family name of the author.
    nationality = models.ForeignKey(Nationality, on_delete=models.PROTECT, default=0) #: Foreign key to the author's nationality.

    def name(self):
        """Return the author's full name as "First Last".

        Returns
        -------
        str
            Full name composed from ``first_name`` and ``last_name``.
        """
        return f"{self.first_name} {self.last_name}"

    class Meta:
        """Model metadata for :class:`Author`."""
        ordering = ['last_name', 'first_name'] #: Default ordering used when querying authors in the admin.
        constraints = [
            models.UniqueConstraint(fields=['first_name', 'last_name', 'nationality'], name='unique_author')
        ] #: Constraints applicable.

    def __str__(self):
        """A readable representation for admin and debug views.

        Returns
        -------
        str
            Full name of the author ("First Last").
        """
        return f"{self.first_name} {self.last_name}"


auditlog.register(Author)


class Book(models.Model):
    """Represents a book record."""
    title = models.CharField(max_length=300) #: Title of the book.
    authors = models.ManyToManyField(Author, through='BookAuthor', related_name='books') #:  Authors related to the book. Uses :class:`BookAuthor` as a through model to preserve order.
    genre = models.ForeignKey(Genre, on_delete=models.PROTECT, default=0) #: Genre foreign key.
    cover = models.ImageField(upload_to='covers/', null=True, blank=True) #:  Optional cover image stored under ``covers/``.
    adapted = models.BooleanField(default=False) #: True if the book was adapted to film.
    film_title = models.CharField(max_length=300, null=True, blank=True) #: Title of the film adaptation when available.
    isbn = models.CharField(
        max_length=13,
        unique=True,
        editable=False,
        validators=[isbn_validator],
        help_text="ISBN-13: 13 digits, generated automatically.",
    ) #: Unique, non-editable ISBN generated for the book.

    def generate_isbn(self):
        """Generate a unique ISBN for this book.

        This delegates to :func:`bookprocess.utils.generate_unique_isbn_from_book`.

        Returns
        -------
        str
            A generated ISBN string (13 characters).
        """
        return generate_unique_isbn_from_book(self)

    def ordered_authors(self):
        """Return authors ordered by their ``order`` value in :class:`BookAuthor`.

        Returns
        -------
        list[Author]
            Ordered list of :class:`Author` instances for this book.
        """
        return [ba.author for ba in self.bookauthor_set.order_by('order')]

    def __str__(self):
        """Readable representation showing title and ISBN.

        Returns
        -------
        str
            Representation in the form: "{title} ({isbn})".
        """
        return f"{self.title} ({self.isbn})"

    class Meta:
        """Model metadata for :class:`Book`."""
        ordering = ['title'] #: Default ordering for books (by title).

auditlog.register(Book)

class BookAuthor(models.Model):
    """Through model that preserves the ordering of authors for a book. """
    book = models.ForeignKey(Book, on_delete=models.CASCADE) #: ForeignKey to the related book.
    author = models.ForeignKey(Author, on_delete=models.PROTECT) #: ForeignKey to the related author.
    order = models.PositiveIntegerField(default=1) #: Position of the author in the book's author list.

    class Meta:
        """Model metadata for :class:`BookAuthor`."""
        ordering = ['order'] #: Ensures BookAuthor rows are ordered by the ``order`` field
        constraints = [
            models.UniqueConstraint(fields=['book', 'author'], name='unique_book_author')
        ] #: Enforces a uniqueness constraint across (book, author).

    def save(self, *args, **kwargs):
        """
        Auto-assign order based on existing authors for this book.

        Parameters
        ----------
        *args
            Positional arguments passed to the parent save method.
        **kwargs
            Keyword arguments passed to the parent save method.
        """
        if self.order == 1 and not self.pk:
            existing_max = BookAuthor.objects.filter(
                book=self.book
            ).aggregate(
                max_order=models.Max('order')
            )['max_order']

            if existing_max is not None:
                self.order = existing_max + 1
            else:
                self.order = 1

        super().save(*args, **kwargs)

    def __str__(self):
        """Return a short representation showing position and author.

        Returns
        -------
        str
            String in the format "<order>. <author>".
        """
        return f"{self.order}. {self.author}"

class Statistic(models.Model):
    """Container for precomputed statistics serialized as JSON."""
    books_per_genre = models.JSONField(default=dict) #: Mapping of genre identifiers/names to book counts.
    authors_per_nationality = models.JSONField(default=dict) #: Mapping of nationality identifiers/names to author counts.
    authors_stats = models.JSONField(default=list) #: Free-form list used to store computed author statistics.

    class Meta:
        """Model metadata for :class:`Statistic`.

        Provides a human-friendly verbose name for the admin.
        """
        verbose_name_plural = "Statistics"

    def __str__(self):
        """Return a short summary used in admin lists.

        The string includes counts for stored mappings to make instances
        identifiable in the admin without expanding the JSON blob.

        Returns
        -------
        str
            Statistics
        """
        return self._meta.verbose_name_plural
