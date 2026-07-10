from sqlalchemy.orm import Session

from app.models.billing import BillingLedgerEntry
from app.repositories.base import BaseRepository


class BillingLedgerRepository(BaseRepository[BillingLedgerEntry]):
    """Append-only ledger access; future write APIs should insert correction/reversal rows, not mutate entries."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, BillingLedgerEntry)
