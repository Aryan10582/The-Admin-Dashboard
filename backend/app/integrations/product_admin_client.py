from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import perf_counter
from urllib.parse import urljoin

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


@dataclass(frozen=True)
class ProductOrganizationListItem:
    product_organization_id: str
    organization_name: str
    lifecycle_status: str | None = None
    billing_mode: str | None = None
    billing_calculation_status: str | None = None
    currency: str | None = None
    credit_status: str | None = None
    credit_balance: Decimal | None = None
    outstanding_dues: Decimal | None = None
    service_status: str | None = None
    product_active_status: bool | None = None
    last_active_at: str | None = None
    product_updated_at: str | None = None
    product_api_version: str | None = None
    product_request_id: str | None = None
    safe_metadata: dict | None = None


@dataclass(frozen=True)
class ProductOrganizationListResult:
    is_success: bool
    organizations: list[ProductOrganizationListItem]
    next_cursor: str | None = None
    has_more: bool = False
    product_request_id: str | None = None
    error_category: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ProductDeliveryResult:
    success: bool
    product_organization_id: str | None = None
    applied_change: str | None = None
    current_product_value: str | None = None
    product_api_version: str | None = None
    sync_confirmed: bool = False
    error_code: str | None = None
    safe_error_message: str | None = None
    product_request_id: str | None = None
    idempotency_key: str | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class ProductPendingChangeStatusResult(ProductDeliveryResult):
    pass


class ProductAdminClient:
    def __init__(
        self,
        api_base_url: str,
        api_version: str = "v1",
        api_secret: str | None = None,
        health_check_url: str | None = None,
        organization_list_path: str | None = None,
        organization_detail_path_template: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_version = api_version
        self.api_secret = api_secret
        self.health_check_url = (health_check_url or f"{self.api_base_url}/health").rstrip("/")
        self.organization_list_path = organization_list_path or f"/{self.api_version}/admin/organizations"
        self.organization_detail_path_template = organization_detail_path_template or f"/{self.api_version}/admin/organizations/{{organization_id}}"
        self.timeout_seconds = timeout_seconds

    def _url_for_path(self, path: str) -> str:
        return urljoin(f"{self.api_base_url}/", path.lstrip("/"))

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

    async def list_organizations(self, *, cursor: str | None = None, limit: int = 100) -> ProductOrganizationListResult:
        url = self._url_for_path(self.organization_list_path)
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url, headers=self._headers(), params=params)
        except httpx.TimeoutException:
            return ProductOrganizationListResult(False, [], error_category="timeout", error_message="Product organization list timed out")
        except httpx.ConnectError:
            return ProductOrganizationListResult(False, [], error_category="connection_error", error_message="Could not connect to product organization list endpoint")
        except httpx.RequestError:
            return ProductOrganizationListResult(False, [], error_category="request_error", error_message="Product organization list endpoint could not be reached")

        if not response.is_success:
            return ProductOrganizationListResult(False, [], error_category="http_error", error_message=f"Product organization list endpoint returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            return ProductOrganizationListResult(False, [], error_category="invalid_response", error_message="Product organization list returned invalid JSON")
        if not isinstance(payload, dict):
            return ProductOrganizationListResult(False, [], error_category="invalid_response", error_message="Product organization list returned an unusable response")

        raw_items = payload.get("organizations") or payload.get("items") or payload.get("data") or []
        if not isinstance(raw_items, list):
            return ProductOrganizationListResult(False, [], error_category="invalid_response", error_message="Product organization list items were not a list")

        items: list[ProductOrganizationListItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                return ProductOrganizationListResult(False, [], error_category="invalid_response", error_message="Product organization list contained an invalid item")
            product_org_id = raw.get("product_organization_id") or raw.get("organization_id") or raw.get("id")
            name = raw.get("organization_name") or raw.get("name")
            if not product_org_id or not name:
                return ProductOrganizationListResult(False, [], error_category="missing_required_data", error_message="Product organization item was missing ID or name")
            try:
                credit_balance = Decimal(str(raw["credit_balance"])) if raw.get("credit_balance") is not None else None
                outstanding_dues = Decimal(str(raw["outstanding_dues"])) if raw.get("outstanding_dues") is not None else None
            except (InvalidOperation, ValueError):
                return ProductOrganizationListResult(False, [], error_category="invalid_response", error_message="Product organization item had invalid decimal values")
            items.append(
                ProductOrganizationListItem(
                    product_organization_id=str(product_org_id),
                    organization_name=str(name),
                    lifecycle_status=raw.get("lifecycle_status"),
                    billing_mode=raw.get("billing_mode"),
                    billing_calculation_status=raw.get("billing_calculation_status"),
                    currency=str(raw["currency"]).upper() if raw.get("currency") else None,
                    credit_status=raw.get("credit_status"),
                    credit_balance=credit_balance,
                    outstanding_dues=outstanding_dues,
                    service_status=raw.get("service_status"),
                    product_active_status=raw.get("product_active_status"),
                    last_active_at=raw.get("last_active_at"),
                    product_updated_at=raw.get("product_updated_at"),
                    product_api_version=raw.get("product_api_version") or raw.get("api_version"),
                    product_request_id=raw.get("product_request_id") or payload.get("product_request_id"),
                    safe_metadata=raw.get("safe_metadata") if isinstance(raw.get("safe_metadata"), dict) else None,
                )
            )

        return ProductOrganizationListResult(
            is_success=True,
            organizations=items,
            next_cursor=payload.get("next_cursor"),
            has_more=bool(payload.get("has_more") or payload.get("next_cursor")),
            product_request_id=payload.get("product_request_id") or payload.get("request_id"),
        )

    async def get_organization_detail(self, product_organization_id: str) -> ProductOrganizationLookupResult:
        url = self._url_for_path(self.organization_detail_path_template.replace("{organization_id}", product_organization_id))
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

    async def deliver_pending_change(
        self,
        *,
        product_organization_id: str,
        action: str,
        payload: dict | None,
        idempotency_key: str,
        admin_id: str,
        reason: str | None,
    ) -> ProductDeliveryResult:
        url = f"{self.api_base_url}/{self.api_version}/admin/pending-changes"
        body = {
            "product_organization_id": product_organization_id,
            "action": action,
            "payload": payload or {},
            "idempotency_key": idempotency_key,
            "admin_id": admin_id,
            "reason": reason,
            "api_version": self.api_version,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=body)
        except httpx.TimeoutException:
            return ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Product delivery timed out")
        except httpx.ConnectError:
            return ProductDeliveryResult(success=False, error_code="connection_failure", safe_error_message="Could not connect to product API")
        except httpx.RequestError:
            return ProductDeliveryResult(success=False, error_code="request_error", safe_error_message="Product API request failed")
        except Exception:
            return ProductDeliveryResult(success=False, error_code="unexpected_client_failure", safe_error_message="Unexpected product client failure")

        try:
            data = response.json()
        except ValueError:
            return ProductDeliveryResult(
                success=False,
                error_code="invalid_response",
                safe_error_message="Product returned an invalid response",
                http_status=response.status_code,
            )
        if not isinstance(data, dict):
            return ProductDeliveryResult(
                success=False,
                error_code="invalid_response",
                safe_error_message="Product returned an unusable response",
                http_status=response.status_code,
            )
        if not response.is_success:
            return ProductDeliveryResult(
                success=False,
                error_code="http_failure",
                safe_error_message=f"Product API returned HTTP {response.status_code}",
                product_request_id=str(data.get("product_request_id") or data.get("request_id") or "") or None,
                http_status=response.status_code,
            )
        return ProductDeliveryResult(
            success=bool(data.get("success", False)),
            product_organization_id=str(data.get("product_organization_id") or data.get("organization_id") or "") or None,
            applied_change=str(data.get("applied_change") or data.get("action") or "") or None,
            current_product_value=str(data.get("current_product_value") or data.get("current_value") or "") or None,
            product_api_version=str(data.get("product_api_version") or data.get("api_version") or "") or None,
            sync_confirmed=bool(data.get("sync_confirmed") or data.get("confirmed")),
            error_code=str(data.get("error_code") or "") or None,
            safe_error_message=str(data.get("safe_error_message") or data.get("message") or "")[:500] or None,
            product_request_id=str(data.get("product_request_id") or data.get("request_id") or "") or None,
            idempotency_key=str(data.get("idempotency_key") or "") or None,
            http_status=response.status_code,
        )

    async def get_pending_change_status(self, idempotency_key: str) -> ProductPendingChangeStatusResult:
        url = f"{self.api_base_url}/{self.api_version}/admin/pending-changes/{idempotency_key}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.TimeoutException:
            return ProductPendingChangeStatusResult(success=False, error_code="timeout", safe_error_message="Product pending-change status lookup timed out")
        except httpx.ConnectError:
            return ProductPendingChangeStatusResult(success=False, error_code="connection_failure", safe_error_message="Could not connect to product API")
        except httpx.RequestError:
            return ProductPendingChangeStatusResult(success=False, error_code="request_error", safe_error_message="Product pending-change status lookup failed")
        except Exception:
            return ProductPendingChangeStatusResult(success=False, error_code="unexpected_client_failure", safe_error_message="Unexpected product status client failure")

        try:
            data = response.json()
        except ValueError:
            return ProductPendingChangeStatusResult(success=False, error_code="invalid_response", safe_error_message="Product returned an invalid status response", http_status=response.status_code)
        if not isinstance(data, dict):
            return ProductPendingChangeStatusResult(success=False, error_code="invalid_response", safe_error_message="Product returned an unusable status response", http_status=response.status_code)
        if not response.is_success:
            return ProductPendingChangeStatusResult(
                success=False,
                error_code="http_failure",
                safe_error_message=f"Product pending-change status endpoint returned HTTP {response.status_code}",
                product_request_id=str(data.get("product_request_id") or data.get("request_id") or "") or None,
                http_status=response.status_code,
            )
        return ProductPendingChangeStatusResult(
            success=bool(data.get("success", False)),
            product_organization_id=str(data.get("product_organization_id") or data.get("organization_id") or "") or None,
            applied_change=str(data.get("applied_change") or data.get("action") or "") or None,
            current_product_value=str(data.get("current_product_value") or data.get("current_value") or "") or None,
            product_api_version=str(data.get("product_api_version") or data.get("api_version") or "") or None,
            sync_confirmed=bool(data.get("sync_confirmed") or data.get("confirmed")),
            error_code=str(data.get("error_code") or "") or None,
            safe_error_message=str(data.get("safe_error_message") or data.get("message") or "")[:500] or None,
            product_request_id=str(data.get("product_request_id") or data.get("request_id") or "") or None,
            idempotency_key=str(data.get("idempotency_key") or "") or None,
            http_status=response.status_code,
        )

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
