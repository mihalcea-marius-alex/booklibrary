"""Management command to bulk-import authors from an Excel file.

This module provides a Django management command intended for admins to
import author names and their nationalities from an Excel spreadsheet.
It performs lightweight validation, reports progress via the project's
``notify`` helper and records the acting user in the ``auditlog``
context when available.

The expected Excel sheet should contain at least two columns:
- ``author``: a full author name (first name and optional last name(s)).
- ``nationality``: the exact name of an existing ``Nationality`` row.
"""
from pathlib import Path
from auditlog.context import set_actor
from bookprocess.models import Author, Nationality
from bookprocess.utils import notify
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from pandas import read_excel, isna

User = get_user_model()

class Command(BaseCommand):
    """A management command to import authors from an Excel file.

    This command reads an Excel file, validates the presence of required
    columns and creates or updates ``Author`` instances.
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
            A mapping containing the parsed CLI options. Expected keys:

            - ``excel_file`` (str): Path to the Excel file to read.
            - ``user`` (str, optional): Username to set as the audit actor.

        Returns
        -------
        None
        """

        username = options.get("user")
        user = User.objects.filter(username=username).first() if username else None
        request = getattr(self, "request", None)

        excel_file = Path(options["excel_file"])
        if not excel_file.exists():
            notify(request, self, f"File not found: {excel_file}", "error")
            return

        df = read_excel(excel_file)

        for idx, row in df.iterrows():
            row_num = idx + 2

            try:
                author_value = row.get("author")
                nationality_value = row.get("nationality")

                if isna(author_value):
                    notify(request, self, f"Row {row_num}: author missing, skipping", "warning")
                    continue

                if isna(nationality_value):
                    notify(request, self, f"Row {row_num}: nationality missing, skipping", "warning")
                    continue

                author_name = str(author_value).strip()
                nationality_name = str(nationality_value).strip()

                if not author_name:
                    notify(request, self, f"Row {row_num}: author missing, skipping", "warning")
                    continue

                if not nationality_name:
                    notify(request, self, f"Row {row_num}: nationality missing, skipping", "warning")
                    continue

                if not any(c.isalpha() for c in author_name):
                    notify(request, self, f"Row {row_num}: author name '{author_name}' contains no letters, skipping", "warning")
                    continue

                try:
                    nationality = Nationality.objects.get(name=nationality_name)
                except Nationality.DoesNotExist:
                    notify(
                        request,
                        self,
                        f"Row {row_num}: Nationality '{nationality_name}' not found, skipping",
                        "warning",
                    )
                    continue

                parts = author_name.split()
                first_name = parts[0]
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

                with set_actor(user):
                    author, created = Author.objects.get_or_create(
                        first_name=first_name,
                        last_name=last_name,
                        defaults={"nationality": nationality},
                    )

                    if created:
                        notify(
                            request,
                            self,
                            f"Row {row_num}: Created author '{author_name}' ({nationality_name})",
                            "success",
                        )
                    else:
                        notify(
                            request,
                            self,
                            f"Row {row_num}: Author '{author_name}' already exists, skipping",
                            "info",
                        )

            except Exception as e:
                notify(request, self, f"Row {row_num}: Error — {e}", "error")
