from django.urls import path, register_converter

from . import api, views


class DocIdConverter:
    regex = "[a-f0-9]{16}"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class ExportFormatConverter:
    regex = "json|csv|xlsx"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(DocIdConverter, "doc")
register_converter(ExportFormatConverter, "fmt")

app_name = "portal"

urlpatterns = [
    # pages
    path("", views.extract, name="extract"),
    path("documents/<doc:doc_id>", views.document, name="document"),
    path("history", views.history, name="history"),
    path("settings", views.settings_page, name="settings"),
    # htmx partials
    path("partials/batch", views.batch_status, name="batch_status"),
    path("partials/review/<doc:doc_id>", views.review_partial, name="review_partial"),
    path("documents/<doc:doc_id>/selection", views.document_selection, name="document_selection"),
    path("documents/<doc:doc_id>/edit", views.document_edit, name="document_edit"),
    path("documents/<doc:doc_id>/reviewed", views.document_reviewed, name="document_reviewed"),
    # JSON API and downloads
    path("api/documents", api.upload, name="api_upload"),
    path("api/samples/<slug:sample_id>", api.run_sample, name="api_sample"),
    path("api/documents/<doc:doc_id>", api.document_json, name="api_document"),
    path("api/documents/<doc:doc_id>/file", api.document_file, name="api_document_file"),
    path("api/documents/<doc:doc_id>/figures/<str:figure_id>", api.document_figure, name="api_document_figure"),
    path("api/documents/<doc:doc_id>/pictures.zip", api.document_pictures, name="api_document_pictures"),
    path("api/documents/<doc:doc_id>/retry", api.retry, name="api_retry"),
    path("api/documents/<doc:doc_id>/delete", api.delete, name="api_delete"),
    path("api/documents/<doc:doc_id>/export.<fmt:fmt>", api.export_one, name="api_export_one"),
    path("api/export.<fmt:fmt>", api.export_many, name="api_export_many"),
    path("api/export-pictures.zip", api.export_pictures, name="api_export_pictures"),
    path("api/catalog", api.catalog_json, name="api_catalog"),
    path("api/presets/<str:model_id>", api.preset_save, name="api_preset_save"),
    path("api/presets/<str:model_id>/<slug:preset_id>/delete", api.preset_delete, name="api_preset_delete"),
]
