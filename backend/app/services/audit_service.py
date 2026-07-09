from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.schemas.audit import AuditLogCreate


def create_audit_log(db: Session, payload: AuditLogCreate) -> AuditLog:
    audit_log = AuditLog(**payload.model_dump(), created_at=datetime.now(timezone.utc))
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log
