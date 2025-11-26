"""
Django management command to populate the Nationality table
with all countries and their corresponding ISBN codes.
"""
from auditlog.context import set_actor
from bookprocess.utils import notify
from bookprocess.models import Nationality
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

COUNTRIES = [
("950", "Argentina"),
("984", "Bangladesh"),
("985", "Belarus"),
("619", "Bulgaria"),
("976", "Caribbean Community"),
("956", "Chile"),
("958", "Colombia"),
("953", "Croatia"),
("959", "Cuba"),
("977", "Egypt"),
("951", "Finland"),
("618", "Greece"),
("962", "Hong Kong"),
("615", "Hungary"),
("602", "Indonesia"),
("600", "Iran"),
("965", "Israel"),
("601", "Kazakhstan"),
("614", "Lebanon"),
("609", "Lithuania"),
("967", "Malaysia"),
("613", "Mauritius"),
("607", "Mexico"),
("978", "Nigeria"),
("608", "North Macedonia"),
("969", "Pakistan"),
("612", "Peru"),
("621", "Philippines"),
("972", "Portugal"),
("606", "Romania"),
("603", "Saudi Arabia"),
("981", "Singapore"),
("961", "Slovenia"),
("982", "South Pacific"),
("955", "Sri Lanka"),
("957", "Taiwan"),
("611", "Thailand"),
("605", "Türkiye"),
("617", "Ukraine"),
("111", "United Kingdom"),
("000", "United States"),
("980", "Venezuela"),
("604", "Vietnam"),
] #: Choices available.

User = get_user_model()
class Command(BaseCommand):
    """
    Populates the Nationality table with all countries and their codes.
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
            help="Username of the user performing this action (for audit logging)."
        )

    def handle(self, *args, **kwargs):
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
        username = kwargs.get("user")
        user = User.objects.filter(username=username).first() if username else None
        request = getattr(self, "request", None)

        for code, name in COUNTRIES:
            try:
                with set_actor(user):
                    obj, created = Nationality.objects.get_or_create(
                        code=code,
                        defaults={"name": name}
                    )

                    if created:
                        notify(request, self, f"Created nationality '{name}' ({code})", "success")
                    else:
                        notify(request, self, f"Nationality '{name}' ({code}) already exists.", "info")

            except Exception as e:
                notify(request, self, f"Failed to process nationality '{name}' ({code}): {e}", "error")
