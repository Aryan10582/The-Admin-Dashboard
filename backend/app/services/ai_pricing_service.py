class AiPricingService:
    """Future home for provider/model pricing sync and pricing version activation."""

    async def sync_pricing_versions(self) -> None:
        raise NotImplementedError("AI pricing sync is intentionally deferred to a later phase.")
