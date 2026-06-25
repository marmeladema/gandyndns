"""gandyndns: a dynamic DNS updater built on the Gandi LiveDNS API."""

from .core import (
    GANDI_API_URL,
    IPIFY_URLS,
    gandyndns,
    get_global_ipv6,
    get_public_addresses,
    resolve_addresses,
    resolve_ipv6,
)

__all__ = [
    "GANDI_API_URL",
    "IPIFY_URLS",
    "gandyndns",
    "get_global_ipv6",
    "get_public_addresses",
    "resolve_addresses",
    "resolve_ipv6",
]

__version__ = "0.5"
