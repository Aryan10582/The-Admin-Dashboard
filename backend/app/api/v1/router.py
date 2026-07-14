from fastapi import APIRouter

from app.api.v1 import auth, billing, failures, health, organizations, pending_changes, plans, products, sync

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(organizations.router)
api_router.include_router(plans.router)
api_router.include_router(billing.router)
api_router.include_router(pending_changes.router)
api_router.include_router(sync.router)
api_router.include_router(failures.router)
