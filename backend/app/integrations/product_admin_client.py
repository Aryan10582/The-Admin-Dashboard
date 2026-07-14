from dataclasses import dataclass
from time import perf_counter

import httpx


@dataclass(frozen=True)
class ProductHealthResult:
    is_success: bool
    response_time_ms: int | None
    status_code: int | None = None
    error_category: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ProductOrganizationLookupResult:
    is_success: bool
    product_organization_id: str | None = None
    product_deployment_id: str | None = None
    payload: dict | None = None
    error_category: str | None = None
    error_message: str | None = None


class ProductAdminClient:
    def __init__(
        self,
        api_base_url: str,
        api_version: str = "v1",
        api_secret: str | None = None,
        health_check_url: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_version = api_version
        self.api_secret = api_secret
        self.health_check_url = (health_check_url or f"{self.api_base_url}/health").rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/plain, */*"}
        if self.api_secret:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        return headers

    async def health_check(self) -> ProductHealthResult:
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(self.health_check_url, headers=self._headers())
        except httpx.TimeoutException:
            return ProductHealthResult(
                is_success=False,
                response_time_ms=None,
                error_category="timeout",
                error_message="Product health check timed out",
            )
        except httpx.ConnectError:
            return ProductHealthResult(
                is_success=False,
                response_time_ms=None,
                error_category="connection_error",
                error_message="Could not connect to product health endpoint",
            )
        except httpx.RequestError:
            return ProductHealthResult(
                is_success=False,
                response_time_ms=None,
                error_category="request_error",
                error_message="Product health endpoint could not be reached",
            )
        except Exception:
            return ProductHealthResult(
                is_success=False,
                response_time_ms=None,
                error_category="unexpected_client_error",
                error_message="Unexpected product health client error",
            )

        response_time_ms = int((perf_counter() - started_at) * 1000)
        if response.is_success:
            return ProductHealthResult(is_success=True, response_time_ms=response_time_ms, status_code=response.status_code)

        return ProductHealthResult(
            is_success=False,
            response_time_ms=response_time_ms,
            status_code=response.status_code,
            error_category="http_error",
            error_message=f"Product health endpoint returned HTTP {response.status_code}",
        )

    async def get_organizations(self) -> list[dict]:
        raise NotImplementedError("Product organization sync is intentionally deferred.")

    async def get_organization_detail(self, product_organization_id: str) -> ProductOrganizationLookupResult:
        url = f"{self.api_base_url}/{self.api_version}/organizations/{product_organization_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.TimeoutException:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="timeout",
                error_message="Product organization lookup timed out",
            )
        except httpx.ConnectError:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="connection_error",
                error_message="Could not connect to product organization endpoint",
            )
        except httpx.RequestError:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="request_error",
                error_message="Product organization endpoint could not be reached",
            )

        if response.status_code == 404:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="not_found",
                error_message="Product organization was not found",
            )
        if not response.is_success:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="http_error",
                error_message=f"Product organization endpoint returned HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="invalid_response",
                error_message="Product organization endpoint returned an invalid response",
            )
        if not isinstance(payload, dict):
            return ProductOrganizationLookupResult(
                is_success=False,
                error_category="invalid_response",
                error_message="Product organization endpoint returned an unusable response",
            )

        product_id = payload.get("id") or payload.get("organization_id") or payload.get("product_organization_id")
        deployment_id = payload.get("product_deployment_id") or payload.get("deployment_id")
        return ProductOrganizationLookupResult(
            is_success=True,
            product_organization_id=str(product_id) if product_id is not None else None,
            product_deployment_id=str(deployment_id) if deployment_id is not None else None,
            payload=payload,
        )

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
