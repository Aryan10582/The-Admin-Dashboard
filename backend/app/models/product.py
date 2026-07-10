from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CompatibilityStatus, Environment, ProductHealthStatus, SyncStatus
from app.models.base import Base, TimestampMixin


class ProductDeployment(Base, TimestampMixin):
    __tablename__ = "product_deployments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_name: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    region: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    environment: Mapped[Environment] = mapped_column(Enum(Environment), index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    health_check_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admin_api_version: Mapped[str] = mapped_column(String(50), default="v1", nullable=False)
    supported_endpoints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compatibility_status: Mapped[CompatibilityStatus] = mapped_column(
        Enum(CompatibilityStatus),
        default=CompatibilityStatus.unknown,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_under_maintenance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health_status: Mapped[ProductHealthStatus] = mapped_column(
        Enum(ProductHealthStatus),
        default=ProductHealthStatus.not_responding,
        nullable=False,
    )
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
