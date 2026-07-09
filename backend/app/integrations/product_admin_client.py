import httpx


class ProductAdminClient:
    def __init__(self, api_base_url: str, api_version: str = "v1", api_secret: str | None = None) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_version = api_version
        self.api_secret = api_secret

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_secret:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        return headers

    async def health_check(self) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self.api_base_url}/health", headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def get_organizations(self) -> list[dict]:
        raise NotImplementedError("Product organization sync is intentionally deferred.")

    async def get_organization_detail(self, product_organization_id: str) -> dict:
        raise NotImplementedError("Product organization detail sync is intentionally deferred.")

    async def get_billing(self, product_organization_id: str) -> dict:
        raise NotImplementedError("Billing integration is intentionally deferred.")

    async def update_billing(self, product_organization_id: str, payload: dict, idempotency_key: str) -> dict:
        raise NotImplementedError("Billing integration is intentionally deferred.")

    async def add_credits(self, product_organization_id: str, payload: dict, idempotency_key: str) -> dict:
        raise NotImplementedError("Credit integration is intentionally deferred.")

    async def deduct_credits(self, product_organization_id: str, payload: dict, idempotency_key: str) -> dict:
        raise NotImplementedError("Credit integration is intentionally deferred.")

    async def record_manual_payment(self, product_organization_id: str, payload: dict, idempotency_key: str) -> dict:
        raise NotImplementedError("Manual payment integration is intentionally deferred.")

    async def get_token_usage(self, product_organization_id: str) -> dict:
        raise NotImplementedError("AI usage integration is intentionally deferred.")

    async def get_revenue(self) -> dict:
        raise NotImplementedError("Revenue integration is intentionally deferred.")

    async def get_plans(self) -> list[dict]:
        raise NotImplementedError("Plan integration is intentionally deferred.")

    async def get_models(self) -> list[dict]:
        raise NotImplementedError("AI model integration is intentionally deferred.")

    async def create_impersonation_token(self, product_organization_id: str, idempotency_key: str) -> dict:
        raise NotImplementedError("Impersonation integration is intentionally deferred.")

    async def get_sync_status(self) -> dict:
        raise NotImplementedError("Sync integration is intentionally deferred.")
