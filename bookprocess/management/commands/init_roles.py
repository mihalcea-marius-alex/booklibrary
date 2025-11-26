"""Management command to initialize user groups and permissions.

This module provides a Django management command that creates predefined
user groups (Administrator, Auditor) and assigns model-level permissions
to each. It is designed to be run once during initial setup or whenever
group configurations need to be refreshed.
"""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from auditlog.models import LogEntry
from bookprocess.models import Author, Book, Genre, Nationality, Statistic, BookAuthor


class Command(BaseCommand):
    """Initialize predefined user groups with fine-grained permissions.

    This command creates two groups:

    - **administrator**: Has CRUD permissions on core models (Author, Book,
      Genre, Nationality, BookAuthor) and read-only on Statistic, Group, User.
    - **auditor**: Has read-only access to audit log entries (LogEntry).
    """

    def handle(self, *args, **options):
        """Execute the role initialization.

        This method defines a dictionary of groups and their associated
        model permissions, then creates or updates each group to ensure
        the correct permissions are assigned.

        Parameters
        ----------
        *args
            Positional arguments passed by Django.
        **options
            Keyword arguments passed by Django.

        Returns
        -------
        None
        """
        groups = {
            'administrator': {
                'desc': 'Custom CRUD permissions per model',
                'models': {
                    Nationality: ['view', 'add', 'delete'],
                    Genre: ['view', 'add', 'delete'],
                    Author: ['add', 'change', 'delete', 'view'],
                    Book: ['add', 'change', 'delete', 'view'],
                    BookAuthor: ['add', 'change', 'delete', 'view'],
                    Statistic: ['view'],
                    Group: ['view'],
                    User: ['view'],
                }
            },
            'auditor': {
                'desc': 'Read-only access (view) permissions to AuditLog entries.',
                'models': {
                    LogEntry: ['view'],
                }
            }
        }

        for name, cfg in groups.items():
            group, created = Group.objects.get_or_create(name=name)
            self.stdout.write(
                self.style.SUCCESS(f'Group created: {name}') if created else f'The {name} group already exists.'
            )

            perms = []
            for model, perm_list in cfg['models'].items():
                ct = ContentType.objects.get_for_model(model)
                for p in perm_list:
                    codename = f'{p}_{model._meta.model_name}'
                    try:
                        perm = Permission.objects.get(content_type=ct, codename=codename)
                        perms.append(perm)
                    except Permission.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f'Missing permission: {codename}'))

            group.permissions.set(perms)
            group.save()
            self.stdout.write(self.style.SUCCESS(f'Updated permissions for: {name}'))

        self.stdout.write(self.style.SUCCESS('Role initialization complete.'))
