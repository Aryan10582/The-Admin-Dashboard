from fastapi import APIRouter

from app.api.v1 import auth, billing, health, organizations, products

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(organizations.router)
api_router.include_router(billing.router)
