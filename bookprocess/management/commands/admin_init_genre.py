"""Management command to populate the project's ``Genre`` table.

This module provides a small Django management command used by
administrators to ensure a canonical set of genres exists in the
database.
"""
from auditlog.context import set_actor
from bookprocess.models import Genre
from bookprocess.utils import notify
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

GENRES = [
    "Adventure",
    "Archaeology",
    "Art",
    "Biography",
    "Cooking",
    "Crime",
    "Drama",
    "Fantasy",
    "Fiction",
    "Folklore",
    "Historical Fiction",
    "History",
    "Horror",
    "Mystery",
    "Nature",
    "Non-Fiction",
    "Philosophy",
    "Poetry",
    "Romance",
    "Science Fiction",
    "Science",
    "Self-Help",
    "Technology",
    "Thriller",
    "Travel"
] #: Choices available.

User = get_user_model()
class Command(BaseCommand):
    """Populate the ``Genre`` table with a canonical list of genres.

    This command is idempotent and safe to run multiple times. For each
    entry in the module-level :data:`GENRES` list the command will call
    :meth:`django.db.models.Manager.get_or_create` to ensure the row
    exists. Creation and informational messages are emitted via the
    :func:`bookprocess.utils.notify` helper which integrates with the
    project's admin messaging system.
    """

    def add_arguments(self, parser):
        """Register command-line arguments.

        Parameters
        ----------
        parser : argparse.ArgumentParser
            The parser instance provided by Django's management
            framework. This method should call ``add_argument`` on the
            parser to declare accepted CLI parameters.
        Returns
        -------
        None
        """

        parser.add_argument(
            "--user",
            type=str,
            help="Username of the user performing this action (for audit logging).",
        )

    def handle(self, *args, **kwargs):
        """Execute the genre population.

        Parameters
        ----------
        *args
            Positional args passed by Django.
        **kwargs
            Keyword args parsed from the CLI. Relevant keys:

            - ``user`` (str, optional): username to set as the audit actor.

        Returns
        -------
        None
        """

        username = kwargs.get("user")
        user = User.objects.filter(username=username).first() if username else None
        request = getattr(self, "request", None)

        for name in GENRES:
            try:
                with set_actor(user):
                    obj, created = Genre.objects.get_or_create(name=name)

                    if created:
                        notify(request, self, f"Created genre '{name}'", "success")
                    else:
                        notify(request, self, f"Genre '{name}' already exists.", "info")

            except Exception as e:
                notify(request, self, f"Failed to create genre '{name}': {e}", "error")
