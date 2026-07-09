from sqlalchemy.orm import Session

from app.core.enums import AuditResultStatus
from app.schemas.audit import AuditLogCreate
from app.services.audit_service import create_audit_log


def test_audit_service_can_create_audit_log_entry(db_session: Session) -> None:
    audit_log = create_audit_log(
        db_session,
        AuditLogCreate(
            action="foundation.test",
            result_status=AuditResultStatus.success,
            reason="test audit foundation",
        ),
    )

    assert audit_log.id is not None
    assert audit_log.action == "foundation.test"
    assert audit_log.result_status == AuditResultStatus.success
