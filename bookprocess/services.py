"""This module provides wrapper around the ``auditlog`` app to
record audit entries for book-related events.
"""

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from bookprocess.utils import serialize_model_instance


class AuditLogService:
    """Helper methods to create audit log entries for domain events."""

    @staticmethod
    def log_book_creation(user, book):
        """Log a book creation event to the audit log.

        The function serializes the ``book`` instance and stores the
        resulting values in the ``changes`` field of the audit.

        Parameters
        ----------
        user: str
            The responsible for the creation.
        book: Book
            The Book model instance that was created.

        Returns
        -------
        None
        """
        book_data = serialize_model_instance(book)
        changes = {key: [None, value] for key, value in book_data.items()}

        LogEntry.objects.create(
        content_type=ContentType.objects.get_for_model(book),
        object_pk=str(book.pk),
        object_repr=str(book),
        action=LogEntry.Action.CREATE,
        changes=changes,
        actor=user,
        timestamp=timezone.now(),
        )

    @staticmethod
    def log_book_update(user, book, changes):
        """Create a single UPDATE audit log entry with the given changes.

        Parameters
        ----------
        user : django.contrib.auth.models.User
            Acting user to attribute the update to.
        book : Book
            The updated instance.
        changes : dict
            Mapping field -> [old, new] for fields that changed.

        Returns
        -------
        None
        """
        if not changes:
            return
        LogEntry.objects.create(
            content_type=ContentType.objects.get_for_model(book),
            object_pk=str(book.pk),
            object_repr=str(book),
            action=LogEntry.Action.UPDATE,
            changes=changes,
            actor=user,
            timestamp=timezone.now(),
        )
