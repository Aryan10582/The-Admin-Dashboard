from ipaddress import ip_address
from urllib.parse import urlsplit

from app.core.config import settings


def validate_product_admin_url(value: str) -> None:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must include a host")
    if hostname in {host.lower() for host in settings.product_api_allowed_hosts}:
        return
    if not settings.is_production:
        return
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("Product API host is not allowed in production")
    try:
        address = ip_address(hostname)
    except ValueError:
        return
    if address.is_loopback or address.is_link_local or address.is_private or address.is_multicast or address.is_reserved or address.is_unspecified:
        raise ValueError("Product API host is not allowed in production")
