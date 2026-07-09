class SyncService:
    async def sync_product_deployment(self, product_deployment_id: str) -> None:
        raise NotImplementedError("Real product sync is intentionally deferred to a later phase.")
