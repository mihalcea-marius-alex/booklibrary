"""Management command to bulk-import books (and their authors) from Excel.

This command reads a spreadsheet containing book metadata and creates
``Book``, ``Author``, and ``BookAuthor`` records. It performs several
validation checks (ISBN format, matching counts of authors and
nationalities, genre existence and ISBN -> nationality consistency)
and reports progress using the project's ``notify`` helper.

The expected columns in the Excel file include::

    title, isbn, adapted, film_title, cover_path, authors,
    nationalities, genre

Where ``authors`` and ``nationalities`` are comma-separated lists of
equal length mapping each author to a nationality.
"""

from pathlib import Path
from auditlog.context import set_actor
from bookprocess.models import Book, Author, Genre, BookAuthor, Nationality
from bookprocess.utils import notify
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from pandas import read_excel


User = get_user_model()


def _to_isbn_string(cell):
    """Normalize a raw Excel cell to a 13-digit ISBN string candidate.

    Parameters
    ----------
    cell : Any
        Raw value from the Excel cell.

    Returns
    -------
    str
        A cleaned string with separators removed and trailing ".0" stripped.
        Can be empty when the cell is blank.
    """
    if cell is None:
        return ""
    try:
        from math import isnan
        if isinstance(cell, float):
            if isnan(cell):
                return ""
            s = f"{cell:.0f}"
        else:
            s = str(cell).strip()
    except Exception:
        s = str(cell).strip()

    if s.endswith(".0"):
        s = s[:-2]
    s = s.replace(" ", "").replace("-", "")
    return s


class Command(BaseCommand):
    """A management command for importing books and related data.

    The command will create ``Book`` instances, save provided cover
    files (if present), create or fetch ``Author`` instances, and
    populate the ``BookAuthor`` relationship with ordering preserved.
    """

    def add_arguments(self, parser):
        """Register command-line arguments.

        Parameters
        ----------
        parser : argparse.ArgumentParser
            The parser instance supplied by Django's management
            framework. This method should call ``add_argument`` on the
            parser to declare accepted CLI parameters.
        Returns
        -------
        None
        """

        parser.add_argument("excel_file", type=str)
        parser.add_argument(
            "--user",
            type=str,
            help="Username of the user performing this action (for audit logging).",
        )

    def handle(self, *args, **options):
        """Execute the import.

        Parameters
        ----------
        *args
            Positional arguments passed by Django.
        **options
            A dict-like object with keys expected by this command:

            - ``excel_file`` (str): path to the Excel file
            - ``user`` (str, optional): username to set as the audit actor

        Returns
        -------
        None
        """

        username = options.get("user")
        user = User.objects.filter(username=username).first() if username else None
        request = getattr(self, "request", None)

        excel_file = Path(options["excel_file"])
        excel_folder = excel_file.parent

        if not excel_file.exists():
            notify(request, self, f"File not found: {excel_file}", "error")
            return

        df = read_excel(
            excel_file,
            dtype=str,
            keep_default_na=False,
            converters={"isbn": _to_isbn_string},
        )

        for idx, row in df.iterrows():
            row_num = idx + 2
            try:
                title = str(row.get("title") or "").strip()
                isbn = _to_isbn_string(row.get("isbn"))
                raw_adapted = str(row.get("adapted") or "").strip()
                adapted = raw_adapted.lower() in ["true", "1", "yes"]
                film_title = str(row.get("film_title") or "").strip()
                cover_path = str(row.get("cover_path") or "").strip()
                authors_raw = str(row.get("authors") or "").strip()
                nationalities_raw = str(row.get("nationalities") or "").strip()
                genre_name = str(row.get("genre") or "").strip()

                required_fields = {
                    "title": title,
                    "isbn": isbn,
                    "authors": authors_raw,
                    "nationalities": nationalities_raw,
                    "genre": genre_name,
                    "adapted": raw_adapted,
                }
                if adapted:
                    required_fields["film_title"] = film_title

                invalid = False
                for field, value in required_fields.items():
                    if not value or str(value).lower() == "nan":
                        notify(request, self, f"Row {row_num}: {field} missing, skipping", "warning")
                        invalid = True
                        break
                if invalid:
                    continue

                if not (isbn.isdigit() and len(isbn) == 13):
                    notify(request, self, f"Row {row_num}: Invalid ISBN '{isbn}'", "warning")
                    continue

                authors_list = [a.strip() for a in authors_raw.split(",") if a.strip()]
                nationalities_list = [n.strip() for n in nationalities_raw.split(",") if n.strip()]

                if len(authors_list) != len(nationalities_list):
                    notify(request, self, f"Row {row_num}: authors count != nationalities count", "warning")
                    continue

                try:
                    primary_nat = Nationality.objects.get(name=nationalities_list[0])
                except Nationality.DoesNotExist:
                    notify(request, self, f"Row {row_num}: Primary nationality '{nationalities_list[0]}' not found", "warning")
                    continue

                country_code_from_isbn = isbn[3:6]
                if str(primary_nat.code).zfill(3) != country_code_from_isbn:
                    notify(request, self, f"Row {row_num}: ISBN code {country_code_from_isbn} != primary author {authors_list[0]} code {primary_nat.code}", "warning")
                    continue

                try:
                    genre = Genre.objects.get(name=genre_name)
                except Genre.DoesNotExist:
                    notify(request, self, f"Row {row_num}: Genre '{genre_name}' not found", "warning")
                    continue

                if Book.objects.filter(isbn=isbn).exists():
                    notify(request, self, f"Row {row_num}: ISBN {isbn} already exists, skipping", "warning")
                    continue

                with set_actor(user):
                    book = Book(
                        title=title,
                        genre=genre,
                        adapted=adapted,
                        film_title=film_title if adapted else None,
                        isbn=isbn,
                    )
                    if cover_path:
                        cover_file = Path(cover_path)
                        if not cover_file.is_absolute():
                            cover_file = excel_folder / cover_path
                        if cover_file.exists():
                            with open(cover_file, "rb") as f:
                                book.cover.save(cover_file.name, File(f))
                    book.save()

                book_authors = []
                for order, (author_name, nat_name) in enumerate(zip(authors_list, nationalities_list)):
                    parts = author_name.split()
                    first = parts[0]
                    last = " ".join(parts[1:]) if len(parts) > 1 else ""
                    nationality, _ = Nationality.objects.get_or_create(name=nat_name)
                    with set_actor(user):
                        author, created = Author.objects.get_or_create(
                            first_name=first,
                            last_name=last,
                            defaults={"nationality": nationality},
                        )
                        if created:
                            notify(request, self, f"Row {row_num}: Created author '{first} {last}' ({nat_name})", "success")
                    book_authors.append(BookAuthor(book=book, author=author, order=order + 1))
                BookAuthor.objects.bulk_create(book_authors)

                notify(request, self, f"Row {row_num}: Imported book '{title}' ({isbn})", "success")

            except Exception as e:
                notify(request, self, f"Row {row_num}: Error — {e}", "error")
