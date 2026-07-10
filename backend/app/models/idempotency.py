from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import IdempotencyRecordStatus
from app.models.base import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("ix_idempotency_records_key", "idempotency_key", unique=True),
        Index("ix_idempotency_records_action_status", "action_type", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(String(150), nullable=False)
    request_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[IdempotencyRecordStatus] = mapped_column(
        Enum(IdempotencyRecordStatus),
        default=IdempotencyRecordStatus.started,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
