"""Unit tests for the bookprocess models.

This module contains a concise test suite for the core models used by
the application: ``Nationality``, ``Genre``, ``Author``, ``Book`` and
``BookAuthor``. Each test class focuses on a single model and all
test functions include short Sphinx-friendly docstrings so automated
documentation generators can surface the intent of each test.

Note
----
These are Django TestCase-based tests and rely on the test database
provided by Django's test runner; they are intentionally small and
fast so they can run during development.
"""

from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import ValidationError

from .models import (
    Book,
    Genre,
    Author,
    Nationality,
    BookAuthor,
)


class NationalityTests(TestCase):
    """Unit tests for the :class:`Nationality` model.

    Covers string representation, validation of the ``code`` field and
    a uniqueness check on the ``name`` field.
    """

    def test_str(self):
        """__str__ returns the human-readable nationality name."""
        n = Nationality.objects.create(name="Romania", code="600")
        self.assertEqual(str(n), "Romania")

    def test_code_too_long_validation(self):
        """A ``code`` longer than three characters fails model validation."""
        n = Nationality(name="Bad", code="TOOLONG")
        with self.assertRaises(ValidationError):
            n.full_clean()

    def test_unique_name(self):
        """Creating two nationalities with the same name violates uniqueness."""
        Nationality.objects.create(name="A", code="001")
        with self.assertRaises(IntegrityError):
            Nationality.objects.create(name="A", code="002")


class GenreTests(TestCase):
    """Unit tests for the :class:`Genre` model.

    Ensures the genre's string representation and unique-name constraint
    behave as expected.
    """

    def test_str(self):
        """__str__ returns the genre name."""
        g = Genre.objects.create(name="Fiction")
        self.assertEqual(str(g), "Fiction")

    def test_unique_name(self):
        """Duplicate genre names should raise an IntegrityError."""
        Genre.objects.create(name="X")
        with self.assertRaises(IntegrityError):
            Genre.objects.create(name="X")


class AuthorTests(TestCase):
    """Unit tests for the :class:`Author` model.

    Tests the name helpers and the behavior when creating an author
    without explicitly providing a nationality (uses default=0 sentinel).
    """

    def test_name_and_str(self):
        """Author.name() and __str__ return the full author name."""
        n = Nationality.objects.create(name="Country", code="600")
        a = Author.objects.create(first_name="Ion", last_name="Pop", nationality=n)
        self.assertEqual(a.name(), "Ion Pop")
        self.assertEqual(str(a), "Ion Pop")

    def test_requires_nationality(self):
        """Creating an Author without nationality uses the sentinel pk=0 row.

        Historically the code used ``default=0`` for the nationality FK. The
        test asserts that creating the author without specifying
        ``nationality`` succeeds and that the resulting instance points to
        the sentinel row with primary key 0.
        """
        a = Author.objects.create(first_name="No", last_name="Nat")
        self.assertIsNotNone(a.nationality)
        self.assertEqual(a.nationality.pk, 0)


class BookTests(TestCase):
    """Unit tests for the :class:`Book` model.

    Exercises ISBN generation/validation and ensures a saved ISBN is
    persisted and queryable.
    """

    def test_generate_isbn_and_str(self):
        """generate_isbn returns a 13-digit numeric string and __str__ includes it."""
        n = Nationality.objects.create(name="N", code="600")
        a = Author.objects.create(first_name="A", last_name="B", nationality=n)

        book = Book.objects.create(title="My Book", genre=Genre.objects.create(name="G"))
        book.authors.add(a)

        isbn = book.generate_isbn()
        self.assertIsInstance(isbn, str)
        self.assertEqual(len(isbn), 13)
        self.assertTrue(isbn.isdigit())

        book.isbn = isbn
        book.save()
        self.assertTrue(Book.objects.filter(isbn=isbn).exists())
        self.assertIn(isbn, str(book))

    def test_isbn_validator_rejects_bad_value(self):
        """The ISBN field rejects values that are not 13-digit numeric strings."""
        book = Book.objects.create(title="Bad ISBN", genre=Genre.objects.create(name="Z"))
        book.isbn = "123"
        with self.assertRaises(ValidationError):
            book.full_clean()

        book.isbn = "abc123def4567"
        with self.assertRaises(ValidationError):
            book.full_clean()

    def test_generate_isbn_unique(self):
        """Generated ISBNs should avoid collisions with existing books."""
        n = Nationality.objects.create(name="N2", code="601")
        a = Author.objects.create(first_name="X", last_name="Y", nationality=n)

        b1 = Book.objects.create(title="B1", genre=Genre.objects.create(name="G1"))
        b1.authors.add(a)
        isbn1 = b1.generate_isbn()
        b1.isbn = isbn1
        b1.save()

        b2 = Book.objects.create(title="B2", genre=Genre.objects.create(name="G2"))
        b2.authors.add(a)
        isbn2 = b2.generate_isbn()
        self.assertNotEqual(isbn1, isbn2)


class BookAuthorTests(TestCase):
    """Unit tests for the :class:`BookAuthor` through model.

    Verifies authors are returned in their stored order and that duplicate
    (book, author) pairs are rejected by the database constraint.
    """

    def test_ordered_authors(self):
        """ordered_authors returns authors sorted by the BookAuthor.order field."""
        n = Nationality.objects.create(name="N", code="602")
        a1 = Author.objects.create(first_name="First", last_name="One", nationality=n)
        a2 = Author.objects.create(first_name="Second", last_name="Two", nationality=n)
        book = Book.objects.create(title="Collab", genre=Genre.objects.create(name="X"))

        BookAuthor.objects.create(book=book, author=a2, order=1)
        BookAuthor.objects.create(book=book, author=a1, order=0)

        ordered = book.ordered_authors()
        self.assertEqual([a.pk for a in ordered], [a1.pk, a2.pk])

    def test_unique_constraint_duplicate(self):
        """Creating the same (book, author) pair twice raises IntegrityError."""
        n = Nationality.objects.create(name="N3", code="603")
        a = Author.objects.create(first_name="Solo", last_name="One", nationality=n)
        book = Book.objects.create(title="SoloBook", genre=Genre.objects.create(name="Y"))

        BookAuthor.objects.create(book=book, author=a, order=0)
        with self.assertRaises(IntegrityError):
            BookAuthor.objects.create(book=book, author=a, order=1)
