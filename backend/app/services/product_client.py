from app.core.config import settings
from app.integrations.product_admin_client import ProductAdminClient
from app.models.product import ProductDeployment


def build_product_client(deployment: ProductDeployment, api_secret: str | None = None) -> ProductAdminClient:
    return ProductAdminClient(
        api_base_url=deployment.api_base_url,
        api_version=deployment.admin_api_version,
        api_secret=api_secret,
        health_check_url=deployment.health_check_url,
        timeout_seconds=settings.product_health_timeout_seconds,
    )
