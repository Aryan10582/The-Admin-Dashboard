class RevenueService:
    """Future home for revenue aggregation from ledger, payments, and product sync records."""

    def aggregate_revenue(self) -> None:
        raise NotImplementedError("Revenue aggregation is intentionally deferred to a later phase.")
