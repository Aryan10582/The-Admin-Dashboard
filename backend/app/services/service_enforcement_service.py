class ServiceEnforcementService:
    """Future home for service status decisions and product confirmation sync."""

    async def sync_service_status_to_product(self) -> None:
        raise NotImplementedError("Service sync is intentionally deferred to a later phase.")
