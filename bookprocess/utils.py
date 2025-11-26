"""Utility helpers for ISBN generation, model serialization and messaging.
"""

from random import choice, randint
from typing import Optional
from django.apps import apps
from django.contrib import messages
from django.db.models import ForeignKey, ManyToManyField
from django.db.models.fields.files import ImageFieldFile, FieldFile

PREFIXES = ['978', '979'] #: Allowed ISBN-13 prefixes.

def isbn13_check_digit(digits12: str) -> str:
    """Calculate the ISBN-13 check digit for 12 digits.

    The ISBN-13 check digit uses alternating weights 1 and 3 for the
    first 12 digits. This helper computes the final check digit so the
    full 13-digit ISBN is valid according to the ISBN-13 specification.

    Parameters
    ----------
    digits12 : str
        Exactly 12 numeric characters representing the first 12 digits
        of an ISBN-13 number.

    Returns
    -------
    str
        A single character string representing the check digit ("0".."9").
    """
    if len(digits12) != 12 or not digits12.isdigit():
        raise ValueError("digits12 must contain exactly 12 digits (0-9).")
    total = 0
    for i, ch in enumerate(digits12):
        weight = 1 if (i % 2 == 0) else 3
        total += int(ch) * weight
    check = (10 - (total % 10)) % 10
    return str(check)


def _normalize_nat_code(nat_code: Optional[str]) -> str:
    """Normalize an input nationality code to a 3-digit string.

    The function keeps only digits from the input and returns a 3-digit
    string. If input is missing or contains no digits the sentinel
    ``'000'`` is returned.

    Parameters
    ----------
    nat_code : Optional[str]
        Input that may contain a nationality code (digits and other
        characters are tolerated).

    Returns
    -------
    str
        A 3-character digit string (e.g. ``'600'`` or ``'007'``) or
        ``'000'`` for missing/invalid input.
    """
    if not nat_code:
        return "000"
    s = str(nat_code).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return "000"
    if len(digits) >= 3:
        return digits[:3]
    return digits.rjust(3, "0")


def _is_allowed_nat_code(code3: str) -> bool:
    """Return whether a 3-digit nationality code is allowed for ISBN seed.

    The current policy permits the sentinel codes ``'000'`` and
    ``'111'``, the range ``600-621`` and the range ``950-989``. This
    function centralizes that rule and can be extended if a canonical
    list of allowed codes is provided later.

    Parameters
    ----------
    code3 : str
        A 3-character string containing digits.

    Returns
    -------
    bool
        True when the code is permitted as part of the ISBN seed.
    """
    if code3 in {"000", "111"}:
        return True
    try:
        n = int(code3)
    except ValueError:
        return False
    if 600 <= n <= 621:
        return True
    if 950 <= n <= 989:
        return True
    return False


def _get_book_model():
    """Retrieve the Book model class dynamically.

    This helper uses Django's app registry to avoid circular import
    issues when the Book model needs to be referenced in utility
    functions that are imported early in the module initialization.

    Returns
    -------
    type
        The :class:`bookprocess.models.Book` model class.
    """
    return apps.get_model("bookprocess", "Book")

def _get_main_author_code_from_book(book_instance) -> Optional[str]:
    """Extract the primary author's nationality code from a Book instance.
    Parameters
    ----------
    book_instance
        A :class:`bookprocess.models.Book` instance.

    Returns
    -------
    Optional[str]
        The 3-character nationality code extracted from the chosen
        author, or ``None`` if no author or nationality is available.
    """
    try:
        BookAuthor = apps.get_model("bookprocess", "BookAuthor")
    except LookupError:
        BookAuthor = None

    try:
        if BookAuthor:
            qs = BookAuthor.objects.filter(book=book_instance).order_by('order').select_related('author', 'author__nationality')
            if qs.exists():
                main_author = qs.first().author
                if main_author.nationality:
                    return main_author.nationality.code

        first_author = book_instance.authors.first()
        if first_author and first_author.nationality:
            return first_author.nationality.code
    except Exception:
        return None

    return None

def generate_unique_isbn_for_nationality(nat_code: Optional[str], max_tries: int = 5000) -> str:
    """Generate a unique ISBN-13 string using a nationality code seed.

    The function normalizes the provided nationality code and, if it is
    not allowed, falls back to the sentinel ``'000'`` code. It then
    repeatedly generates candidate ISBNs (prefix + nat + pub_id + check)
    until a non-existing ISBN is found or ``max_tries`` is reached.

    Parameters
    ----------
    nat_code : Optional[str]
        Input nationality code used as part of the ISBN seed.
    max_tries : int
        Maximum number of attempts to find a unique ISBN before raising
        a RuntimeError.

    Returns
    -------
    str
        A unique, 13-character ISBN string.
    """
    nat = _normalize_nat_code(nat_code)
    if not _is_allowed_nat_code(nat):
        nat = "000"

    Book = _get_book_model()

    for _ in range(max_tries):
        prefix = choice(PREFIXES)
        pub_id = f"{randint(0, 999999):06d}"
        first12 = prefix + nat + pub_id
        control = isbn13_check_digit(first12)
        isbn13 = first12 + control
        if not Book.objects.filter(isbn=isbn13).exists():
            return isbn13

    raise RuntimeError("Nu am reușit să genereze un ISBN unic în limita încercărilor.")


def generate_unique_isbn_from_book(book_instance, nat_code_override: Optional[str] = None) -> str:
    """Generate a unique ISBN-13 for a Book instance.

    The function first respects an explicit ``nat_code_override`` if
    provided; otherwise it attempts to extract the main author's
    nationality code and delegate to
    :func:`generate_unique_isbn_for_nationality`. If neither is
    available it falls back to using ``'000'`` as the seed.

    Parameters
    ----------
    book_instance
        The Book instance for which an ISBN should be generated.
    nat_code_override : Optional[str]
        An explicit nationality code to use instead of extracting from
        the book's authors.

    Returns
    -------
    str
        A unique ISBN-13 string.
    """
    if nat_code_override:
        return generate_unique_isbn_for_nationality(nat_code_override)

    try:
        nat_from_author = _get_main_author_code_from_book(book_instance)
        if nat_from_author:
            return generate_unique_isbn_for_nationality(nat_from_author)
    except Exception:
        pass

    return generate_unique_isbn_for_nationality("000")

def represent_related(obj):
    """Return a human-friendly representation for a related object.

    The helper inspects common attribute names (``name``, ``title``,
    ``code``, ``full_name``) and returns the first matching attribute's
    value. If the attribute is callable it will be called. If no known
    attribute is present the object's ``str()`` value is returned.

    Parameters
    ----------
    obj
        Any model instance (or ``None``).

    Returns
    -------
    Optional[str]
        A human-readable string or ``None`` if ``obj`` is ``None``.
    """
    if obj is None:
        return None
    for field in ["name", "title", "code", "full_name"]:
        if hasattr(obj, field):
            val = getattr(obj, field)
            if callable(val):
                return val()
            return val
    return str(obj)

def serialize_model_instance(instance):
    """Serialize a Django model instance into a human-readable dict.

    The serializer converts foreign keys into a representative string
    (using :func:`represent_related`), flattens many-to-many relations
    into comma-separated lists of names, and converts file fields to
    their stored filenames. The function uses ``select_related`` and
    ``prefetch_related`` to minimize DB queries when re-loading the
    instance by primary key.

    Parameters
    ----------
    instance
        A saved Django model instance (must have a valid ``pk``).

    Returns
    -------
    dict
        Mapping of field name -> serializable value.
    """

    data = {}
    opts = instance._meta

    instance = (
        instance.__class__.objects
        .select_related(*[f.name for f in opts.fields if isinstance(f, ForeignKey)])
        .prefetch_related(*[f.name for f in opts.many_to_many])
        .get(pk=instance.pk)
    )

    for field in opts.get_fields():
        if field.auto_created and not field.concrete:
            continue

        name = field.name
        value = getattr(instance, name, None)

        if isinstance(field, ForeignKey):
            data[name] = represent_related(value)
        elif isinstance(field, ManyToManyField):
            related_qs = getattr(instance, name).all()
            data[name] = ', '.join([represent_related(obj) for obj in related_qs])
        elif isinstance(value, (ImageFieldFile, FieldFile)):
            data[name] = value.name if value else None
        else:
            data[name] = value

    return data

def notify(request=None, command=None, msg="", level="info"):
    """Display a message via Django messages or a management command.

    The helper centralizes how messages are emitted so callers can be
    ignorant of the current execution context (web request vs. manage
    command). When ``request`` is provided the Django messages API is
    used; when ``command`` is provided the management command's style
    helpers are used; otherwise the message prints to stdout.

    Parameters
    ----------
    request : Optional[django.http.HttpRequest]
        Optional request object; when provided the message is added to
        the request using Django's messages framework.
    command : Optional[django.core.management.BaseCommand]
        Optional management command instance; when provided the message
        is written to the command's stdout using the styled helper.
    msg : str
        The message text to display.
    level : str
        One of ``'info'``, ``'success'``, ``'warning'`` or ``'error'``.
    """
    if request is not None:
        level_fn = getattr(messages, level, messages.info)
        level_fn(request, msg)
    elif command is not None:
        style_fn = getattr(command.style, level.upper(), command.style.SUCCESS)
        command.stdout.write(style_fn(msg))
    else:
        print(msg)
