"""Admin customizations for the bookprocess application.

This module contains Django ``ModelAdmin`` subclasses, admin helper mixins
and small admin forms used across the project's admin interface. Its
purpose is to centralize common admin behaviour (pagination, file-based
population commands, CSV/JSON export utilities) and to
provide model-specific admin classes for ``Author``, ``Book``, ``Genre``,
``Nationality``, ``BookAuthor`` and supporting audit/logging integrations.
"""

###########################
#     Stadard Imports     #
###########################
from csv import writer
from datetime import datetime
from json import dumps, loads
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable
from zipfile import ZipFile

###########################
#    3rd Party Imports    #
###########################
from adminsortable2.admin import SortableInlineAdminMixin, SortableAdminBase
from auditlog.models import LogEntry
from auditlog.context import set_actor, disable_auditlog
from django_admin_listfilter_dropdown.filters import DropdownFilter, RelatedDropdownFilter
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Case, When, IntegerField, Sum, ForeignKey
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path
from django.utils.html import format_html
from django.shortcuts import render

###########################
#       Local Imports     #
###########################
from .management.commands.admin_init_author import Command as AuthorsCmd
from .management.commands.admin_init_book import Command as BookCmd
from .management.commands.admin_init_genre import Command as GenreCmd
from .management.commands.admin_init_nationality import Command as NationalityCmd
from .models import Author, Book, Genre, Nationality, BookAuthor, Statistic
from .services import AuditLogService

###########################
#     Helper Classes      #
###########################
class AdminSave(admin.ModelAdmin):
    """Helper mixin to centralize save behaviour for admin models.

    This mixin sets the audit actor when saving from the admin so audit
    logs correctly attribute the change to the current user.

    """

    def save_model(self, request, obj, form, change):
        """Save the model instance with audit actor set.

        Parameters
        ----------
        request : django.http.HttpRequest
            The active HTTP request.
        obj : django.db.models.Model
            The model instance being saved.
        form : django.forms.Form
            The admin form used to validate the instance.
        change : bool
            True if updating an existing object, False for creation.

        Returns
        -------
        None
        """
        with set_actor(request.user):
            super().save_model(request, obj, form, change)

class AdminDelete(admin.ModelAdmin):
    """Helper mixin that ensures audit actor is set when deleting models."""

    def delete_model(self, request, obj):
        """Delete a single object with audit actor set.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        obj : django.db.models.Model
            The model instance to delete.

        Returns
        -------
        None
        """
        with set_actor(request.user):
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Delete a queryset of objects with audit actor set.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        queryset : django.db.models.query.QuerySet
            The queryset of objects to delete.

        Returns
        -------
        None
        """
        with set_actor(request.user):
            super().delete_queryset(request, queryset)

class AdminPagination(admin.ModelAdmin):
    """Mixin to add pagination controls and extra changelist context."""
    populate_url: str | None = None #: URL suffix for the model population view
    populate_button: str | None = None #:Label for the populate button shown in the changelist.
    multiple_url: str | None = None #: URL for multi-object operations (e.g. add-multiple view).
    multiple_button: str |None = None #: Label for the multiple action button.
    change_list_template = "admin/admin_pagination_changelist.html" #: Template path used to render the custom changelist when this mixin is applied.
    list_per_page = 10 #:Current page size for the changelist (can be overridden via GET).
    list_per_page_options = [10, 20, 50] #: Allowed page-size options presented to the user.

    def __init__(self, model, admin_site):
        """Initialize the pagination helper.

        Parameters
        ----------
        model : django.db.models.Model
            The model class this admin manages.
        admin_site : django.contrib.admin.AdminSite
            The admin site instance.

        Returns
        -------
        None
        """
        super().__init__(model, admin_site)

        model_name = model._meta.model_name
        model_verbose = model._meta.verbose_name_plural.title()

        if self.populate_url is None:
            self.populate_url = f"populate-{model_name}/"
        if self.populate_button is None:
            self.populate_button = f"Populate {model_verbose}"

    def changelist_view(self, request, extra_context=None):
        """Customize the changelist view with pagination and extra template context.

        Reads an optional ``list_per_page`` GET parameter to adjust the
        page size for the changelist and injects UI labels/URLs used by
        the custom changelist template.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request object.
        extra_context : dict
            Additional context to include in the template.

        Returns
        -------
        django.http.HttpResponse
            The response returned by the parent ``changelist_view``.
        """
        request.GET = request.GET.copy()
        try:
            page_param = int(request.GET.pop("list_per_page", [self.list_per_page])[0])
            self.list_per_page = page_param
        except (ValueError, TypeError):
            self.list_per_page = self.list_per_page

        extra_context = extra_context or {}
        extra_context["list_per_page_options"] = self.list_per_page_options
        extra_context["populate_url"] = self.populate_url
        extra_context["populate_button"] = self.populate_button
        extra_context["multiple_url"] = self.multiple_url
        extra_context["multiple_button"] = self.multiple_button

        return super().changelist_view(request, extra_context=extra_context)

    class Media:
        """Media assets required by the pagination UI."""
        js = ("admin/js/admin_paginator_dropdown.js",) #: JavaScript files included on the admin pages that use this mixin.

class AdminPopulate(admin.ModelAdmin):
    """Mixin that provides file-upload and command-based population helpers."""
    populate_form_class: type[forms.Form] | None = None #: Form class used to accept uploaded files (when provided).
    populate_command_class: type | None = None #: Management command class responsible for importing data.
    is_zip_file: bool = False #: When True uploaded files are treated as ZIP.
    populate_title: str | None = None #: Human readable title for the upload page.
    populate_route: str | None = None #: URL route suffix for the populate view.
    admin_file_upload_form = "admin/admin_file_upload_form.html" #: Template path used to render the populate file upload form.

    def __init__(self, model, admin_site):
        """Initialize the populate helper for this admin.

        Parameters
        ----------
        model : django.db.models.Model
            The model class this admin is registered for.
        admin_site : django.contrib.admin.AdminSite
            The admin site instance.

        Returns
        -------
        None
        """
        super().__init__(model, admin_site)

        opts = model._meta
        model_name = opts.model_name
        model_verbose = opts.verbose_name.title()

        if self.populate_route is None:
            self.populate_route = f"populate-{model_name}/"

        if self.populate_title is None:
            self.populate_title = f"Populate {model_verbose}"

    def get_urls(self):
        """Return admin URLs, prepending the populate route.

        Returns
        -------
        list
            List of URL patterns for the admin, including the populate route.
        """
        urls = super().get_urls()

        opts = self.model._meta
        custom_urls = [
            path(
                self.populate_route,
                self.admin_site.admin_view(self.populate_view),
                name=f"{opts.app_label}_{opts.model_name}_populate",
            ),
        ]
        return custom_urls + urls

    def populate_view(self, request):
        """Handle requests to the populate endpoint.

        Depending on which configuration attributes are set this will either
        render/accept a file upload form (``populate_form_class`` present)
        or invoke a management command directly (``populate_command_class``).

        Parameters
        ----------
        request : django.http.HttpRequest
            Incoming HTTP request from the admin UI.

        Returns
        -------
        django.http.HttpResponse or django.http.HttpResponseRedirect
            Rendered form, success redirect, or error redirect.
        """

        if self.populate_form_class and self.populate_command_class:
            return self._handle_file_upload(request)

        if not(self.populate_form_class) and self.populate_command_class:
            return self._handle_command_execution(request)

        self.message_user(
            request,
            "No populate method configured.",
            messages.WARNING
        )
        return HttpResponseRedirect("../")

    def _execute_command(self, request, **extra_kwargs):
        """Execute the configured management command for population.

        The configured command class is instantiated, given access to the
        request as ``cmd.request`` and then its ``handle`` method is called
        with the current user and any ``extra_kwargs`` (for example the
        path to an extracted Excel file).

        Parameters
        ----------
        request : django.http.HttpRequest
            The current HTTP request.
        **extra_kwargs : dict
            Extra keyword arguments forwarded to the command's ``handle``.

        Returns
        -------
        django.http.HttpResponseRedirect
            Redirects back to the model changelist after execution.
        """
        if not self.populate_command_class:
            self.message_user(
                request,
                "No populate command class defined.",
                messages.WARNING
            )
            return HttpResponseRedirect("../")

        try:
            cmd = self.populate_command_class()
            cmd.request = request
            cmd.handle(user=request.user, **extra_kwargs)

        except Exception as e:
            self.message_user(request, f"Error: {e}", messages.ERROR)

        return HttpResponseRedirect("../")

    def _handle_file_upload(self, request):
        """Process the populate file upload and run the populate command.

        On POST this validates the form, writes the uploaded file to a
        temporary directory and, if configured, extracts an Excel file from
        a ZIP archive before calling ``_execute_command`` with the file path.

        Parameters
        ----------
        request : django.http.HttpRequest
            The incoming request containing POST data and FILES.

        Returns
        -------
        django.http.HttpResponse or django.shortcuts.render
            Redirect after processing or the rendered upload form for GET or
            invalid data.
        """
        if request.method == "POST":
            form = self.populate_form_class(request.POST, request.FILES)
            if form.is_valid():
                uploaded_file = form.cleaned_data.get("file")

                if not uploaded_file:
                    self.message_user(request, "No file uploaded.", messages.ERROR)
                    return HttpResponseRedirect("../")

                with TemporaryDirectory() as tmpdir:
                    tmpdir = Path(tmpdir)
                    tmp_path = tmpdir / uploaded_file.name

                    with open(tmp_path, "wb+") as f:
                        for chunk in uploaded_file.chunks():
                            f.write(chunk)

                    if self.is_zip_file:
                        excel_file = self._extract_excel_from_zip(tmp_path)
                        if not excel_file:
                            self.message_user(request, "No Excel file found in ZIP.",
                                              messages.ERROR)
                            return HttpResponseRedirect("../")
                    else:
                        excel_file = tmp_path

                    try:
                        self._execute_command(request, excel_file=str(excel_file))
                    except Exception as e:
                        self.message_user(request, f"Error: {e}", messages.ERROR)

                    return HttpResponseRedirect("../")
        else:
            form = self.populate_form_class()

        opts = self.model._meta
        context = self.admin_site.each_context(request)
        context.update({
            "form": form,
            "title": self.populate_title,
            "opts": opts,
        })
        return render(request, self.admin_file_upload_form, context)

    def _handle_command_execution(self, request):
        """Execute the configured populate command without a file upload.

        This is used when the admin configuration provides only
        ``populate_command_class`` and expects the command to perform any
        required actions itself.

        Parameters
        ----------
        request : django.http.HttpRequest
            The incoming request.

        Returns
        -------
        django.http.HttpResponseRedirect
            Redirect back to the model changelist.
        """
        return self._execute_command(request)

    def _extract_excel_from_zip(self, zip_path):
        """Extract the first Excel file (``*.xlsx``) from a ZIP archive.

        Parameters
        ----------
        zip_path : pathlib.Path
            Path to the ZIP file on disk.

        Returns
        -------
        pathlib.Path
            Path to the extracted Excel file if found, otherwise ``None``.
        """
        extract_path = zip_path.parent / zip_path.stem

        try:
            with ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)

            excel_file = next(extract_path.glob("*.xlsx"), None)
            return excel_file
        except Exception:
            return None

class AdminCount(admin.ModelAdmin):
    """Small mixin providing a grouped count helper used by statistics admins. """
    def aggregate_count(self, model, value_field):
        """Return aggregated counts grouped by a related field.

        Parameters
        ----------
        model : django.db.models.Model
            The model to query (for example ``Book``).
        value_field : str
            The related field to group by (for example ``'genre__name'``).

        Returns
        -------
        django.db.models.query.QuerySet
            QuerySet of dicts containing the grouped value and a ``count`` key.
        """
        return (
            model.objects
            .values(value_field)
            .annotate(count=Count("id"))
            .order_by("-count")
        )

class AdminWriteCSV(admin.ModelAdmin):
    """Mixin to export admin data as CSV files."""
    filename: str | None = None #:  Default filename for the generated CSV when not overridden.
    sections: list[tuple[str, list[str], str, Callable]] = [] #:Sections configuration used by :meth:`export_csv` describing title headers, rows iterable and a row formatting callable.

    def __init__(self, model, admin_site):
        """Initialize the CSV export mixin.

        Parameters
        ----------
        model : django.db.models.Model
            The model class that the admin wraps.
        admin_site : django.contrib.admin.AdminSite
            The admin site instance.

        Returns
        -------
        None
        """
        super().__init__(model, admin_site)

        model_name = model._meta.model_name

        if self.filename is None:
            self.filename = f"{model_name}.csv"

    def export_csv(self, sections):
        """Generate an HttpResponse with the supplied sections written as CSV.

        Parameters
        ----------
        sections : Iterable
            Iterable of tuples (title, headers, rows, row_func) describing
            each CSV section. ``row_func`` is called with each row object to
            return an iterable of values to write.

        Returns
        -------
        django.http.HttpResponse
            Response object containing the CSV payload and appropriate
            Content-Disposition header for download.
        """
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{self.filename}"'
        response.write('\ufeff')
        writer_csv = writer(response)

        def write_section(title, headers, rows, row_func):
            """Write a single CSV section to the response writer.

            Parameters
            ----------
            title : str
                Section title written as a heading row.
            headers : Iterable
                Iterable of header column names.
            rows : Iterable
                Iterable of row objects to be formatted.
            row_func : Callable
                Callable that accepts a row object and returns an iterable
                of column values for that row.

            Returns
            -------
            None
                Writes directly to the CSV writer attached to the response.
            """
            writer_csv.writerow([title])
            writer_csv.writerow(headers)
            for row in rows:
                writer_csv.writerow(row_func(row))
            writer_csv.writerow([])

        for title, headers, rows, row_func in sections:
            write_section(title, headers, rows, row_func)

        return response

class AdminWriteJSON(admin.ModelAdmin):
    """Mixin to add a JSON export action to admin classes."""

    filename: str | None = None #: Default filename for the exported JSON file.
    actions = ['export_as_json'] #: Admin actions exposed by this mixin.

    def __init__(self, model, admin_site):
        """Initialize the JSON export mixin.

        Parameters
        ----------
        model : django.db.models.Model
            The model class this admin represents.
        admin_site : django.contrib.admin.AdminSite
            The admin site instance.

        Returns
        -------
        None
        """
        super().__init__(model, admin_site)

        opts = model._meta
        self.exclude = getattr(self, 'exclude', [])
        self.model_name = opts.model_name
        self.model_fields = [f for f in opts.get_fields() if not (f.many_to_many or f.one_to_many) and f.name not in self.exclude]

        if self.filename is None:
            self.filename = f"{self.model_name}.json"

    @admin.action(description="Export selected items as JSON")
    def export_as_json(self, request, queryset):
        """Admin action: export the selected objects as a JSON file.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        queryset : django.db.models.query.QuerySet
            The selected objects to export.

        Returns
        -------
        django.http.HttpResponse
            A response containing the JSON representation and an
            appropriate Content-Disposition header for download.
        """
        data = []
        for obj in queryset:
            obj_data = {}
            for field in self.model_fields:
                value = getattr(obj, field.name)

                if isinstance(field, ForeignKey):
                    value = str(value) if value else None
                elif isinstance(value, datetime):
                    value = value.strftime("%Y-%m-%d %H:%M:%S")

                obj_data[field.name] = value
            data.append(obj_data)

        response = HttpResponse(
            dumps(data, indent=4, ensure_ascii=False),
            content_type="application/json"
        )
        response["Content-Disposition"] = f'attachment; filename="{self.filename}"'
        return response

class AdminPopulateForm(forms.Form):
    """Base form used by admin populate views to accept a single file."""

    allowed_extensions = [] #: File extensions accepted by the form (e.g. ['.xlsx', '.zip']).
    file_label = None #: Label for the input; auto-generated when ``None``.
    file_help_text = None #: Help text for the input; auto-generated when ``None``.

    def __init__(self, *args, **kwargs):
        """Initialize the populate form.

        Parameters
        ----------
        *args, **kwargs
            Forwarded to ``forms.Form.__init__``.

        Returns
        -------
        None
        """
        super().__init__(*args, **kwargs)

        if self.file_label is None:
            if self.allowed_extensions:
                ext_str = "/".join(self.allowed_extensions).upper()
                self.file_label = f"Upload {ext_str} File"
            else:
                self.file_label = "Upload File"

        if self.file_help_text is None:
            if self.allowed_extensions:
                self.file_help_text = f"Allowed: {', '.join(self.allowed_extensions)}"
            else:
                self.file_help_text = "Select a file."

        widget_attrs = {}
        if self.allowed_extensions:
            widget_attrs["accept"] = ", ".join(self.allowed_extensions)

        self.fields["file"] = forms.FileField(
            label=self.file_label,
            help_text=self.file_help_text,
            widget=forms.ClearableFileInput(attrs=widget_attrs)
        )

    def clean(self):
        """Validate the uploaded file and ensure allowed extension.

        Returns
        -------
        dict
            The cleaned form data.
        """
        cleaned_data = super().clean()
        file = cleaned_data.get("file")

        if file and self.allowed_extensions:
            file_ext = file.name.lower().split(".")[-1]
            allowed_exts = [ext.lstrip(".").lower() for ext in self.allowed_extensions]

            if file_ext not in allowed_exts:
                self.add_error("file", f"Only {', '.join(self.allowed_extensions)} allowed.")

        return cleaned_data

############################
#    Nationality Class     #
############################
@admin.register(Nationality)
class NationalityAdmin(AdminPagination, AdminPopulate, AdminSave, AdminDelete):
    """Admin for the :class:`bookprocess.models.Nationality` lookup model."""
    list_display = ('name', 'code') #: Fields shown in the changelist (``name``, ``code``).
    search_fields = list_display #: Fields used for search.
    populate_command_class = NationalityCmd #: Management command used to populate nationality data.

############################
#       Genre Class        #
############################
@admin.register(Genre)
class GenreAdmin(AdminPagination, AdminPopulate, AdminSave, AdminDelete):
    """Admin for the :class:`bookprocess.models.Genre` lookup model."""
    list_display = ('name',) #: Fields shown in the changelist (``name``).
    search_fields = list_display #: Fields used for search.
    populate_command_class = GenreCmd #: Management command used to populate genre data.

############################
#      AuditLog Class      #
############################
admin.site.unregister(LogEntry)
@admin.register(LogEntry)
class LogEntryAdmin(AdminWriteJSON):
    """Admin for audit log entries with helper formatters."""
    list_display = ("formatted_timestamp", "actor", "action", "object_repr", "changes_formatted") #: Standard Django admin option for list display and filtering.
    list_filter = ("action", "actor") #: Standard Django admin option for list display and filtering.
    search_fields = ("object_repr", "actor__username", "changes") #: Standard Django admin option for list display and filtering.
    exclude = [
        'object_pk',
        'serialized_data',
        'changes_text',
        'cid',
        'remote_addr',
        'remote_port',
        'additional_data',
        'actor_email',
    ] #: Standard Django admin option for list display and filtering.

    def changes_formatted(self, obj):
        """Format the stored change payload resolving related FK names.

        This helper transforms the JSON-like ``changes`` stored on audit
        log entries into a readable string. When a changed field is a
        ForeignKey the helper will attempt to look up the referred object
        and display its string representation instead of the raw id.

        Parameters
        ----------
        obj : auditlog.models.LogEntry
            The audit log entry instance.

        Returns
        -------
        str
            A human readable description of the changes or ``"-"`` when no
            meaningful data is present.
        """
        if not obj.changes:
            return "-"

        try:
            if isinstance(obj.changes, str):
                changes = loads(obj.changes)
            else:
                changes = obj.changes
        except Exception:
            return str(obj.changes)

        if not obj.content_type:
            return str(changes)

        model_class = obj.content_type.model_class()
        if not model_class:
            return str(changes)

        formatted = []
        for field_name, values in changes.items():
            if not isinstance(values, list) or len(values) != 2:
                formatted.append(f"{field_name}: {values}")
                continue

            old_val, new_val = values

            try:
                field = model_class._meta.get_field(field_name)

                if hasattr(field, 'related_model'):
                    fk_model = field.related_model

                    old_id = None if old_val in ["None", None, ""] else int(old_val)
                    new_id = None if new_val in ["None", None, ""] else int(new_val)

                    old_obj = fk_model.objects.filter(pk=old_id).first() if old_id else None
                    new_obj = fk_model.objects.filter(pk=new_id).first() if new_id else None

                    old_display = str(old_obj) if old_obj else "None"
                    new_display = str(new_obj) if new_obj else "None"

                    formatted.append(f"{field_name}: {old_display} → {new_display}")
                else:

                    formatted.append(f"{field_name}: {old_val} → {new_val}")
            except Exception:
                formatted.append(f"{field_name}: {old_val} → {new_val}")

        return "; ".join(formatted) if formatted else "-"

    changes_formatted.short_description = "Changes"

    def formatted_timestamp(self, obj):
        """Return a human-friendly timestamp for display in list views.

        Parameters
        ----------
        obj : auditlog.models.LogEntry
            The audit log entry instance.

        Returns
        -------
        str
            Formatted timestamp as ``YYYY-MM-DD HH:MM:SS``.
        """
        return obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    formatted_timestamp.admin_order_field = "timestamp"
    formatted_timestamp.short_description = "Timestamp"

############################
#     Statistic Class      #
############################
@admin.register(Statistic)
class StatisticAdmin(AdminCount, AdminWriteCSV):
    """Admin used to display aggregated site statistics."""

    change_list_template = "admin/admin_statistics_changelist.html" #: Template used to render the statistics changelist.

    def get_books_per_genre(self):
        """Return counts of books grouped by genre name.

        Returns
        -------
        django.db.models.query.QuerySet
            QuerySet of dicts with keys ``genre__name`` and ``count``.
        """
        return self.aggregate_count(Book, "genre__name")

    def get_authors_per_nationality(self):
        """Return counts of authors grouped by nationality name.

        Returns
        -------
        django.db.models.query.QuerySet
            QuerySet of dicts with keys ``nationality__name`` and ``count``.
        """
        return self.aggregate_count(Author, "nationality__name")

    def get_author_stats(self):
        """Compute per-author statistics for solo and co-authored books.

        The function annotates authors with counts of books where they are the
        sole author and counts where the book has more than one author.

        Returns
        -------
        list
            List of dictionaries in the form ``{"author": str, "solo_books": int, "coauthored_books": int}``.
        """
        books_with_author_count = Book.objects.annotate(num_authors=Count('authors'))

        authors_stats_qs = Author.objects.annotate(
            solo_books=Sum(
                Case(
                    When(books__in=books_with_author_count.filter(num_authors=1), then=1),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            coauthored_books=Sum(
                Case(
                    When(books__in=books_with_author_count.filter(num_authors__gt=1), then=1),
                    default=0,
                    output_field=IntegerField()
                )
            )
        )

        author_stats = [
            {
                "author": str(author),
                "solo_books": author.solo_books or 0,
                "coauthored_books": author.coauthored_books or 0,
            }
            for author in authors_stats_qs
        ]
        return author_stats

    def changelist_view(self, request, extra_context=None):
        """Render the custom statistics changelist view.

        This view prepares multiple statistic sections (books per genre,
        authors per nationality and per-author stats) and injects them into
        the changelist template. Supports CSV export via ``?export=csv``.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        extra_context : dict
            Additional context to pass to the changelist template.

        Returns
        -------
        django.http.HttpResponse
            The response for the changelist (or CSV file when requested).
        """
        extra_context = extra_context or {}

        books_per_genre = self.get_books_per_genre()
        authors_per_nationality = self.get_authors_per_nationality()
        author_stats = self.get_author_stats()

        sections = [
            ("Books per Genre", ["Genre", "Count"], books_per_genre, lambda r: (r["genre__name"], r["count"])),
            ("Authors per Nationality", ["Nationality", "Count"], authors_per_nationality, lambda r: (r["nationality__name"], r["count"])),
            ("Author Statistics", ["Author", "Solo Books", "Co-authored Books"], author_stats, lambda r: (r["author"], r["solo_books"], r["coauthored_books"])),
        ]

        if request.GET.get("export") == "csv":
            return self.export_csv(sections)

        stats = {
            "books_per_genre": self.get_books_per_genre(),
            "authors_per_nationality": self.get_authors_per_nationality(),
            "author_stats": self.get_author_stats(),
        }
        extra_context.update(stats)

        return super().changelist_view(request, extra_context=extra_context)

############################
#      Author Classes      #
############################
class AuthorBookInLine(admin.TabularInline):
    """Inline showing basic book info for an Author's books."""
    model = BookAuthor #: The through model (``BookAuthor``) used by this inline.
    can_delete = False #: Whether items can be deleted from the inline.
    extra = 0 #: Number of extra blank rows shown on the add view.
    max_num = 0 #: Maximum number of inline forms to display.
    show_change_link = False #: Whether a change link is shown for each inline row.
    fields = (
        'title',
        'authors',
        'genre',
        'isbn',
        'cover',
        'adapted',
        'film_title'
    ) #: The fields shown in the inline.
    readonly_fields = fields #: Fields that are displayed read-only in the inline.

    def title(self, obj):
        """Return the title of the related book for display in the inline.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            The related Book title.
        """
        return obj.book.title

    def authors(self, obj):
        """Return a comma-separated list of authors for the related book.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            Comma-separated author names.
        """
        authors = obj.book.ordered_authors()
        return ", ".join(str(a) for a in authors)

    def genre(self, obj):
        """Return the genre name of the related book.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            The related Book's genre name.
        """
        return obj.book.genre.name

    def isbn(self, obj):
        """Return the ISBN of the related book.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            The ISBN string.
        """
        return obj.book.isbn

    def cover(self, obj):
        """Return an HTML thumbnail linking to the book cover or a placeholder.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            HTML-safe snippet with an <img> tag or "-" when no cover exists.
        """
        if obj.book.cover:
            url = obj.book.cover.url
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-height:50px;" />'
                '</a>',
                url, url
            )
        return "-"

    def adapted(self, obj):
        """Return whether the related book is an adaptation (film/etc.).

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        bool
            True when the book is marked as adapted, False otherwise.
        """
        return obj.book.adapted

    def film_title(self, obj):
        """Return the film title for adapted works or '-' when not present.

        Parameters
        ----------
        obj : bookprocess.models.BookAuthor
            The inline relation instance.

        Returns
        -------
        str
            The film title or ``"-"`` when not available.
        """
        return obj.book.film_title or "-"

class AuthorPopulateForm(AdminPopulateForm):
    """Populate form specialized for author imports (Excel files)."""
    allowed_extensions = [".xlsx"] #: Allowed file extensions for the form.

@admin.register(Author)
class AuthorAdmin(AdminPagination, AdminPopulate, AdminSave, AdminDelete):
    """Admin for the :class:`bookprocess.models.Author` model."""
    inlines = [AuthorBookInLine] #: Inline admin classes shown on the author change view (e.g. book list).
    list_display = ('name', 'nationality') #: Columns shown in the changelist.
    search_fields = ('first_name', 'last_name') #: Fields used for search in the changelist.
    list_filter = (
        ('nationality', RelatedDropdownFilter),
    ) #: Tuple of list filters applied in the changelist.
    populate_form_class = AuthorPopulateForm #: Form class used to upload author import files.
    populate_command_class = AuthorsCmd #:  Management command used to import author data.

    def get_readonly_fields(self, request, obj=None):
        """Return read-only fields for the Author admin.

        If the author is the primary author on any book, prevent changing
        the ``nationality`` via the admin to preserve data consistency.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        obj : Author
            The instance being viewed/edited (None on add form).

        Returns
        -------
        list
            A list of field names that should be read-only.
        """
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.books.filter(bookauthor__order=1).exists():
            readonly.append('nationality')
        return readonly

    def name(self, obj):
        """Return a human-friendly name for the author instance.

        This method is used in the admin list display. It proxies to the
        model's ``name()`` helper.

        Parameters
        ----------
        obj : Author
            The author instance.

        Returns
        -------
        str
            The formatted author name.
        """
        return obj.name()
    name.admin_order_field = 'first_name'

############################
#        Book Classes      #
############################
class BookForm(forms.ModelForm):
    """Form used in the Book admin providing validation and media assets."""

    class Meta:
        """Meta configuration linking the form to the Book model and including all fields."""
        model = Book #: Model used for this form.
        fields = "__all__" #: Fields from model.

    def clean(self):
        """Validate interdependent fields for Book.

        Returns
        -------
        dict
            The cleaned form data dictionary.
        """
        cleaned_data = super().clean()
        adapted = cleaned_data.get("adapted")
        film_title = cleaned_data.get("film_title")

        if adapted and not film_title:
            self.add_error("film_title", "Please enter a film title for adapted books.")

        if not adapted:
            cleaned_data['film_title'] = None

        return cleaned_data

    class Media:
        """Include custom JavaScript for dynamic field behavior within the admin form."""
        js = ("admin/js/admin_book_form_adapted_film_isbn_cover.js","admin/js/admin_book_form_authors.js") #: JavaScript files included for dynamic behavior in the admin form.

class BookAddMultipleForm(forms.Form):
    """Form for adding multiple books for the same author dynamically."""
    author = forms.ModelChoiceField(
        queryset=Author.objects.all(),
        label="Select Author",
        required=True,
        widget=forms.Select(attrs={'class': 'vForeignKeyRawIdAdminField'})
    ) #: The ModelChoiceField selecting the author to attach to created books.

class BookAuthorInline(SortableInlineAdminMixin, admin.TabularInline):
    """Inline admin for the BookAuthor through-model.

    Presents a sortable inline to associate authors with a Book and
    controls the number of empty extra forms shown on add vs edit.
    """
    model = BookAuthor #: The through model (``BookAuthor``) used by this inline.
    extra = 1 #: Number of extra blank forms to display on the add view.
    fields = ('author',) #: Fields shown in the inline form.
    autocomplete_fields = ('author',) #: Fields that use autocomplete widgets.
    sortable_field_name = 'order' #: Name of the field used by adminsortable2 for ordering.

    def get_extra(self, request, obj=None, **kwargs):
        """Return the number of extra inline forms to display.

        When editing an existing Book instance we don't show extra empty
        inline rows; when adding a new book we provide one extra row to
        easily add a first author.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        obj : None
            The parent object being edited. None on the add form.
        **kwargs : dict
            A dictionary of optional keyword arguments passed by Django.

        Returns
        -------
        int
            Number of extra inline forms to display.
        """
        if obj:
            return 0
        return 1

class BookPopulateForm(AdminPopulateForm):
    """Populate form for importing books; expects a ZIP containing an Excel file."""
    allowed_extensions = [".zip"] #: Allowed file extensions

@admin.register(Book)
class BookAdmin(SortableAdminBase, AdminPagination, AdminPopulate, AdminDelete):
    """Admin for the :class:`bookprocess.models.Book` model providing helpers for authors, covers and bulk add."""
    form = BookForm #: Custom form class used for add/change views (``BookForm``).
    inlines = [BookAuthorInline] #: Inline classes (``BookAuthorInline``) to manage authors.
    list_display = ('title', 'display_authors', 'isbn', 'genre', 'adapted', 'film_title') #: Columns shown in the changelist.
    search_fields = ('title', 'isbn', 'bookauthor__author__first_name', 'bookauthor__author__last_name') #: Fields used in changelist search.
    list_filter = (
        ('genre', RelatedDropdownFilter),
        ('adapted', DropdownFilter),
    ) #: Filters displayed in the changelist.
    readonly_fields = ('isbn', 'cover_preview') #:  Read-only fields in the change view.
    fieldsets = (
        (None, {
            'fields': (
                'title', 'genre', 'cover', 'cover_preview',
                'adapted', 'film_title', 'isbn'
            )
        }),
    ) #: Fieldset configuration used in the change form.

    multiple_url = "multiple/" #: Route suffix for the add-multiple view.
    multiple_button = "Add multiple books for the same author" #: Label for the multiple-add action button.
    populate_form_class = BookPopulateForm #: Populate form class used for importing books.
    populate_command_class = BookCmd #: Management command used for population imports.
    is_zip_file = True #: When True the populate view expects a ZIP containing an Excel file.

    def display_authors(self, obj):
        """Return a comma-separated list of the book's authors for display.

        Parameters
        ----------
        obj : Book
            The Book instance.

        Returns
        -------
        str
            Comma-separated author names or an em-dash when none are present.
        """
        authors = [ba.author for ba in obj.bookauthor_set.order_by('order')]
        return ", ".join(str(a) for a in authors) if authors else "—"
    display_authors.short_description = "Authors"

    def cover_preview(self, obj):
        """Return HTML for a clickable cover preview image.

        Parameters
        ----------
        obj : Book
            The Book instance. May be ``None`` in some admin contexts.

        Returns
        -------
        str
            An HTML snippet with an <img> wrapped in a link or an empty
            string when no cover is available.
        """
        if not obj or not getattr(obj, 'cover', None):
            return ""
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" style="height:150px;" /></a>',
            obj.cover.url, obj.cover.url
        )
    cover_preview.short_description = "Cover Preview"

    def save_model(self, request, obj, form, change):
        """ Create a new Book instance with proper audit handling.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        obj : Book
            The Book instance to save.
        form : django.forms.Form
            The admin form used to validate the instance.
        change : bool
            True if updating an existing object, False for creation.

        Returns
        -------
        None
        """
        if not change:
            with disable_auditlog():
                super().save_model(request, obj, form, change)
        else:
            if obj.pk:
                try:
                    before_obj = type(obj).objects.get(pk=obj.pk)
                    before = self._snapshot_book_state(before_obj)
                except type(obj).DoesNotExist:
                    before = None
            else:
                before = None

            request._bookadmin_before = getattr(request, "_bookadmin_before", {})
            if before is not None and obj.pk:
                request._bookadmin_before[obj.pk] = before

            with disable_auditlog():
                super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        """Save related formset data and perform post-save bookkeeping.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        form : django.forms.Form
            The parent Book admin form.
        formset : django.forms.BaseInlineFormSet
            The inline formset containing BookAuthor relations.
        change : bool
            True when updating an existing book, False for create.

        Returns
        -------
        None
            This method performs in-place saves and does not return a value.
        """
        self._save_authors_from_formset(formset)

        book = form.instance
        if not change:
            self._finalize_book_creation(request.user, book)
        else:
            self._update_book_isbn_if_needed(request.user, book)

            before = getattr(request, "_bookadmin_before", {}).get(book.pk)
            try:
                after_obj = type(book).objects.prefetch_related(
                    'bookauthor_set__author', 'genre'
                ).get(pk=book.pk)
            except type(book).DoesNotExist:
                after_obj = book
            after = self._snapshot_book_state(after_obj)
            changes = self._diff_snapshots(before, after) if before else {}

            if changes:
                AuditLogService.log_book_update(request.user, book, changes)

    def _save_authors_from_formset(self, formset):
        """Marks objects as ``_from_admin`` prior to saving so
        downstream hooks can differentiate admin-created relations.

        Parameters
        ----------
        formset : django.forms.BaseInlineFormSet
            The inline formset of BookAuthor instances.

        Returns
        -------
        None
        """
        instances = formset.save(commit=False)
        for instance in instances:
            instance._from_admin = True
            instance.save()

        for obj in formset.deleted_objects:
            obj._from_admin = True
            obj.delete()

        formset.save_m2m()

    def _finalize_book_creation(self, user, book):
        """Generate an ISBN for a newly created Book and emit a CREATE log.

        Parameters
        ----------
        user : django.contrib.auth.models.User
            The user performing the creation.
        book : Book
            The Book instance that was created.

        Returns
        -------
        None
        """

        first_author = book.bookauthor_set.order_by('order').first()
        if first_author:
            with disable_auditlog():
                book.isbn = book.generate_isbn()
                book.save(update_fields=['isbn'])
        AuditLogService.log_book_creation(user, book)


    def _update_book_isbn_if_needed(self, user, book):
        """Regenerate the ISBN only when the primary author's nationality changed.

        Parameters
        ----------
        user : django.contrib.auth.models.User
            Acting user (audit actor).
        book : Book
            Instance to possibly update.

        Returns
        -------
        None
        """
        first_author_rel = (
            book.bookauthor_set.order_by('order')
            .select_related('author__nationality')
            .first()
        )
        if not first_author_rel:
            return

        author = first_author_rel.author
        nat = getattr(author, "nationality", None)

        from .utils import _normalize_nat_code
        nat_code_current = _normalize_nat_code(getattr(nat, "code", None)) if nat else ""

        if not book.isbn:
            new_isbn = book.generate_isbn()
            if new_isbn:
                with disable_auditlog():
                    book.isbn = new_isbn
                    book.save(update_fields=['isbn'])
            return

        old_nat_code = book.isbn[3:6] if len(book.isbn) >= 6 else ""

        if not nat_code_current or nat_code_current == old_nat_code:
            return

        new_isbn = book.generate_isbn()
        if new_isbn and new_isbn != book.isbn:
            with disable_auditlog():
                book.isbn = new_isbn
                book.save(update_fields=['isbn'])

    def _snapshot_book_state(self, book):
        """Return a snapshot dict of fields used in manual update audit logs.

        Returns
        -------
        dict
            Keys: id, title, genre, cover, adapted, film_title, isbn, authors.
        """
        authors = [ba.author for ba in book.bookauthor_set.order_by('order')]
        authors_str = ", ".join(str(a) for a in authors) if authors else None

        return {
            "id": book.pk,
            "title": book.title,
            "genre": str(book.genre) if getattr(book, "genre", None) else None,
            "cover": getattr(book.cover, "name", None) or None,
            "adapted": bool(book.adapted),
            "film_title": book.film_title or None,
            "isbn": book.isbn or None,
            "authors": authors_str,
        }

    def _diff_snapshots(self, before, after):
        """Compute a changes dict for audit logging.

        Parameters
        ----------
        before : dict
            Pre-change snapshot.
        after : dict
            Post-change snapshot.

        Returns
        -------
        dict
            Mapping field_name -> [old_value, new_value]. Empty when there is
            no actual change.
        """
        if not before:
            return {}

        # Detect if any field actually changed
        any_changed = any(before.get(k) != after.get(k) for k in after.keys())
        if not any_changed:
            return {}

        # Include all fields in the log for context
        return {k: [before.get(k), after.get(k)] for k in after.keys()}

    def get_urls(self):
        """Return admin URL patterns including the multiple-create view.

        Returns
        -------
        list
            List of URL patterns for this admin.
        """
        return [
            path("multiple/", self.admin_site.admin_view(self.add_multiple_books_view)),
        ] + super().get_urls()

    def add_multiple_books_view(self, request):
        """Handle the add-multiple-books admin view.

        Supports GET to render the form and POST to process submitted
        multiple-book data.

        Parameters
        ----------
        request : django.http.HttpRequest
            The incoming request.

        Returns
        -------
        django.http.HttpResponse
            The rendered form or a redirect after processing.
        """
        if request.method == "POST":
            return self._handle_multiple_books_post(request)
        return self._render_multiple_books_form(request)

    def _handle_multiple_books_post(self, request):
        """Validates the form, creates Book instances and associated
        BookAuthor relations and shows a summary message.

        Parameters
        ----------
        request : django.http.HttpRequest
            The POST request containing form data.

        Returns
        -------
        django.http.HttpResponseRedirect or django.http.HttpResponse
            Redirect back to the changelist on success or the form
            rendered with errors on invalid input.
        """
        form = BookAddMultipleForm(request.POST)
        if not form.is_valid():
            return self._render_multiple_books_form(request, form)

        author = form.cleaned_data["author"]
        books_created = self._create_books_from_post_data(request, author)

        self._show_creation_message(request, books_created, author)
        return HttpResponseRedirect("../")

    def _create_books_from_post_data(self, request, author):
        """Loop through POSTed book entries and create Book objects.

        Parameters
        ----------
        request : django.http.HttpRequest
            The request containing POST data and FILES.
        author : Author
            The author to attach as the primary author to each created book.

        Returns
        -------
        int
            Number of successfully created books.
        """
        books_created = 0
        index = 0

        while f"book_{index}_title" in request.POST:
            created = self._create_single_book_from_post(request, index, author)
            if created:
                books_created += 1
            index += 1

        return books_created

    def _create_single_book_from_post(self, request, index, author):
        """Create a single Book from indexed POST fields.

        Parameters
        ----------
        request : django.http.HttpRequest
            The request with POST data and FILES.
        index : int
            The index used to locate the set of fields for this book.
        author : Author
            The primary author to associate with the created Book.

        Returns
        -------
        bool
            True when the book was created, False when required fields
            were missing.
        """
        title = request.POST.get(f"book_{index}_title", "").strip()
        if not title:
            return False

        book_data = self._extract_book_data_from_post(request, index)

        with disable_auditlog():
            book = Book.objects.create(**book_data)
            BookAuthor.objects.create(book=book, author=author, order=0)

            new_isbn = book.generate_isbn()
            if new_isbn:
                book.isbn = new_isbn
                book.save(update_fields=["isbn"])

        AuditLogService.log_book_creation(request.user, book)

        return True

    def _extract_book_data_from_post(self, request, index):
        """Extract a book's fields from POST using the given index.

        Parameters
        ----------
        request : django.http.HttpRequest
            The request containing POST and FILES.
        index : int
            The index used to construct field names.

        Returns
        -------
        dict
            Keyword args suitable for ``Book.objects.create(**kwargs)``.
        """
        genre_id = request.POST.get(f"book_{index}_genre")
        adapted = request.POST.get(f"book_{index}_adapted") == "on"

        try:
            genre = Genre.objects.get(id=genre_id) if genre_id else None
        except Genre.DoesNotExist:
            genre = None

        return {
            "title": request.POST.get(f"book_{index}_title", "").strip(),
            "genre": genre,
            "adapted": adapted,
            "film_title": request.POST.get(f"book_{index}_film_title", "").strip() if adapted else None,
            "cover": request.FILES.get(f"book_{index}_cover")
        }

    def _show_creation_message(self, request, books_created, author):
        """Display a success or warning message after attempting creation.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request for context (used by ``messages``).
        books_created : int
            Number of books successfully created.
        author : Author
            The author for whom books were created.

        Returns
        -------
        None
        """
        if books_created > 0:
            messages.success(request, f"Successfully added {books_created} book(s) for {author}!")
        else:
            messages.warning(request, "No books were added.")

    def _render_multiple_books_form(self, request, form=None):
        """Render the add-multiple-books form template.

        Parameters
        ----------
        request : django.http.HttpRequest
            The current request.
        form : BookAddMultipleForm
            Optional form instance (used to re-render validation errors).

        Returns
        -------
        django.http.HttpResponse
            Rendered HTML response of the form.
        """
        if form is None:
            form = BookAddMultipleForm()

        context = self.admin_site.each_context(request)
        context.update({
            "form": form,
            "genres": Genre.objects.all(),
            "title": "Add Multiple Books for Same Author",
            "opts": self.model._meta,
        })
        return render(request, "admin/admin_add_multiple_books_form.html", context)
