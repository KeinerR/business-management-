from pathlib import Path

from django.db import transaction

from tenantdata.models import Document, DocumentVersion


@transaction.atomic
def add_document_version(document, uploaded_file, user, notes=""):
    """Append an immutable version while serializing version allocation."""
    locked = Document.objects.select_for_update().get(pk=document.pk)
    latest = locked.versions.order_by("-version").values_list("version", flat=True).first() or 0
    version = DocumentVersion(
        document=locked,
        version=latest + 1,
        original_name=Path(uploaded_file.name).name[:255],
        mime_type=getattr(uploaded_file, "content_type", "")[:120],
        size=getattr(uploaded_file, "size", 0),
        notes=notes,
        uploaded_by=user,
    )
    version.file.save(version.original_name, uploaded_file, save=False)
    version.save()
    locked.save(update_fields=["updated_at"])
    return version
