from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PendingChangeStatus
from app.models.base import Base, TimestampMixin


class PendingProductChange(Base, TimestampMixin):
    __tablename__ = "pending_product_changes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    status: Mapped[PendingChangeStatus] = mapped_column(
        Enum(PendingChangeStatus),
        default=PendingChangeStatus.saved,
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
