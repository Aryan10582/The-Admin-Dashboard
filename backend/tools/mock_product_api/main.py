"""
MOCK/DEVELOPMENT ONLY product admin API for local Admin Dashboard demos.

This module is intentionally outside app/ and is never imported by production
business logic. Start it manually with uvicorn when real product deployments
are unavailable.
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


SCENARIOS = {
    "confirmed_success",
    "slow_success",
    "timeout",
    "temporary_5xx",
    "organization_not_found",
    "organization_mismatch",
    "deployment_mismatch",
    "incompatible_api_version",
    "idempotency_key_mismatch",
    "product_rejection",
    "accepted_unconfirmed",
    "ambiguous_2xx",
    "contradictory_value",
    "unknown_plan_code",
    "unsupported_plan_version",
    "currency_mismatch",
    "billing_mode_incompatibility",
    "contradictory_plan",
    "status_lookup_confirms",
    "status_lookup_unknown",
    "empty_organizations",
    "malformed_organizations",
}


class ScenarioRequest(BaseModel):
    scenario: str


class MockState:
    scenario = "confirmed_success"
    deliveries: dict[str, dict] = {}
    organizations = [
        {
            "product_organization_id": "org_101",
            "organization_name": "City Clinic",
            "lifecycle_status": "active",
            "billing_mode": "prepaid_credits",
            "billing_calculation_status": "active",
            "currency": "USD",
            "credit_status": "healthy_balance",
            "credit_balance": "100.00",
            "outstanding_dues": "0.00",
            "service_status": "running",
            "product_active_status": True,
        },
        {
            "product_organization_id": "org_205",
            "organization_name": "City Clinic",
            "lifecycle_status": "trial",
            "billing_mode": "prepaid_credits",
            "billing_calculation_status": "usage_tracking_only",
            "currency": "USD",
            "credit_status": "low_balance",
            "credit_balance": "5.00",
            "outstanding_dues": "0.00",
            "service_status": "running",
            "product_active_status": True,
        },
        {
            "product_organization_id": "org_309",
            "organization_name": "Vision Center",
            "lifecycle_status": "suspended",
            "billing_mode": "postpaid_manual_settlement",
            "billing_calculation_status": "paused",
            "currency": "USD",
            "credit_status": "outstanding_dues",
            "credit_balance": "0.00",
            "outstanding_dues": "25.00",
            "service_status": "paused",
            "product_active_status": False,
        },
    ]


state = MockState()
app = FastAPI(title="MOCK DEVELOPMENT Product Admin API")


def _request_id() -> str:
    return f"mock-req-{uuid4()}"


def _scenario_from_request(request: Request) -> str:
    return request.headers.get("X-Mock-Scenario") or request.query_params.get("scenario") or state.scenario


def _delivery_response(body: dict, scenario: str, *, from_lookup: bool = False) -> dict:
    idempotency_key = str(body.get("idempotency_key") or "")
    action = str(body.get("action") or "")
    product_org_id = str(body.get("product_organization_id") or "")
    response = {
        "success": True,
        "product_organization_id": product_org_id,
        "applied_change": action,
        "current_product_value": (body.get("payload") or {}).get("requested_intended_service_status"),
        "product_api_version": body.get("api_version") or "v1",
        "sync_confirmed": True,
        "product_request_id": _request_id(),
        "idempotency_key": idempotency_key,
        "mock": True,
        "from_status_lookup": from_lookup,
    }
    payload = body.get("payload") or {}
    if action in {"assign_plan_version", "change_plan_version"}:
        response["plan_code"] = payload.get("plan_code")
        response["plan_version"] = payload.get("plan_version_number")
        response["current_product_value"] = f"{payload.get('plan_code')}@v{payload.get('plan_version_number')}"
    if scenario == "organization_mismatch":
        response["product_organization_id"] = "mock-wrong-org"
    elif scenario == "deployment_mismatch":
        response["product_deployment_id"] = "mock-wrong-deployment"
        response["success"] = False
        response["error_code"] = "deployment_mismatch"
        response["safe_error_message"] = "Mock deployment mismatch"
    elif scenario == "incompatible_api_version":
        response["product_api_version"] = "v999"
    elif scenario == "idempotency_key_mismatch":
        response["idempotency_key"] = f"wrong-{idempotency_key}"
    elif scenario == "product_rejection":
        response.update(success=False, error_code="product_rejection", safe_error_message="Mock product rejection")
    elif scenario in {"unknown_plan_code", "unsupported_plan_version", "currency_mismatch", "billing_mode_incompatibility"}:
        response.update(success=False, error_code=scenario, safe_error_message=f"Mock {scenario.replace('_', ' ')}")
    elif scenario == "accepted_unconfirmed":
        response["sync_confirmed"] = False
    elif scenario == "ambiguous_2xx":
        return {"product_request_id": _request_id(), "message": "Mock ambiguous response"}
    elif scenario == "contradictory_value":
        response["current_product_value"] = "mock-contradictory-value"
    elif scenario == "contradictory_plan":
        response["plan_code"] = "mock_wrong_plan"
        response["plan_version"] = 999
    elif scenario == "status_lookup_unknown":
        response.update(success=False, sync_confirmed=False, error_code="unclear_confirmation", safe_error_message="Mock status lookup could not confirm application")
    return response


@app.post("/mock/scenario")
async def set_scenario(payload: ScenarioRequest) -> dict:
    if payload.scenario not in SCENARIOS:
        raise HTTPException(status_code=422, detail=f"Unsupported mock scenario: {payload.scenario}")
    state.scenario = payload.scenario
    return {"success": True, "scenario": state.scenario}


@app.get("/mock/state")
async def get_state() -> dict:
    return {"scenario": state.scenario, "delivery_count": len(state.deliveries), "known_idempotency_keys": list(state.deliveries.keys())}


@app.delete("/mock/state")
async def reset_state() -> dict:
    state.scenario = "confirmed_success"
    state.deliveries.clear()
    return {"success": True}


@app.get("/health")
async def health(request: Request):
    scenario = _scenario_from_request(request)
    if scenario == "slow_success":
        await asyncio.sleep(1)
    if scenario == "timeout":
        await asyncio.sleep(30)
    if scenario == "temporary_5xx":
        return JSONResponse({"success": False, "error_code": "temporary_5xx"}, status_code=503)
    return {
        "success": True,
        "mock": True,
        "scenario": scenario,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/{api_version}/organizations/{product_organization_id}")
async def organization_detail(api_version: str, product_organization_id: str, request: Request):
    scenario = _scenario_from_request(request)
    if scenario == "organization_not_found":
        raise HTTPException(status_code=404, detail="Mock organization not found")
    if scenario == "temporary_5xx":
        return JSONResponse({"success": False, "error_code": "temporary_5xx"}, status_code=503)
    if scenario == "timeout":
        await asyncio.sleep(30)
    response_id = product_organization_id
    if scenario == "organization_mismatch":
        response_id = "mock-wrong-org"
    organization = next((item for item in state.organizations if item["product_organization_id"] == response_id), None)
    if organization is not None:
        return {
            **organization,
            "id": response_id,
            "product_organization_id": response_id,
            "product_deployment_id": request.query_params.get("deployment_id"),
            "api_version": api_version,
            "product_api_version": api_version,
            "mock": True,
        }
    return {
        "id": response_id,
        "product_organization_id": response_id,
        "product_deployment_id": request.query_params.get("deployment_id"),
        "api_version": api_version,
        "mock": True,
    }


@app.get("/{api_version}/admin/organizations")
async def organization_list(api_version: str, request: Request, limit: int = 100, cursor: str | None = None):
    scenario = _scenario_from_request(request)
    if scenario == "temporary_5xx":
        return JSONResponse({"success": False, "error_code": "temporary_5xx"}, status_code=503)
    if scenario == "timeout":
        await asyncio.sleep(30)
    if scenario == "malformed_organizations":
        return {"items": [{"organization_name": "Missing ID"}]}
    if scenario == "empty_organizations":
        return {"items": [], "has_more": False, "product_request_id": _request_id()}
    start = int(cursor or "0")
    page = state.organizations[start : start + limit]
    next_offset = start + len(page)
    return {
        "items": [{**item, "product_api_version": api_version, "product_request_id": _request_id()} for item in page],
        "next_cursor": str(next_offset) if next_offset < len(state.organizations) else None,
        "has_more": next_offset < len(state.organizations),
        "product_request_id": _request_id(),
    }


@app.get("/{api_version}/admin/organizations/{product_organization_id}")
async def admin_organization_detail(api_version: str, product_organization_id: str, request: Request):
    return await organization_detail(api_version, product_organization_id, request)


@app.post("/{api_version}/admin/pending-changes")
async def deliver_pending_change(api_version: str, payload: dict, request: Request):
    scenario = _scenario_from_request(request)
    if scenario == "timeout":
        await asyncio.sleep(30)
    if scenario == "temporary_5xx":
        return JSONResponse({"success": False, "error_code": "temporary_5xx", "product_request_id": _request_id()}, status_code=503)

    body = {**payload, "api_version": api_version}
    idempotency_key = str(body.get("idempotency_key") or "")
    if idempotency_key in state.deliveries:
        return state.deliveries[idempotency_key]
    response = _delivery_response(body, scenario)
    state.deliveries[idempotency_key] = response
    return response


@app.get("/{api_version}/admin/pending-changes/{idempotency_key}")
async def pending_change_status(api_version: str, idempotency_key: str, request: Request):
    scenario = _scenario_from_request(request)
    if scenario == "status_lookup_unknown":
        return _delivery_response({"idempotency_key": idempotency_key, "api_version": api_version}, scenario, from_lookup=True)
    if idempotency_key in state.deliveries:
        return {**state.deliveries[idempotency_key], "from_status_lookup": True}
    if scenario == "status_lookup_confirms":
        response = _delivery_response(
            {
                "idempotency_key": idempotency_key,
                "api_version": api_version,
                "product_organization_id": request.query_params.get("product_organization_id") or "prod-demo-org",
                "action": request.query_params.get("action") or "credits.add",
            },
            "confirmed_success",
            from_lookup=True,
        )
        state.deliveries[idempotency_key] = response
        return response
    return {
        "success": False,
        "sync_confirmed": False,
        "error_code": "unclear_confirmation",
        "safe_error_message": "Mock status lookup could not confirm application",
        "product_request_id": _request_id(),
        "idempotency_key": idempotency_key,
    }
