import os
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request

NETWORKS = tuple(ip_network(value) for value in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7",
))


def auth_mode() -> str:
    mode = os.environ.get("AUTH_MODE", "oauth")
    if mode not in {"oauth", "local", "both"}:
        raise RuntimeError("AUTH_MODE must be oauth, local, or both")
    return mode


def is_local_request(request: Request) -> bool:
    try:
        address = ip_address(request.client.host)
        address = getattr(address, "ipv4_mapped", None) or address
        return any(address in network for network in NETWORKS)
    except (ValueError, AttributeError):
        return False


def require_provider(provider: str, request: Request) -> None:
    mode = auth_mode()
    if (provider == "local" and mode == "oauth") or (provider != "local" and mode == "local"):
        raise HTTPException(404, "Login method disabled")
    if provider == "local" and not is_local_request(request):
        raise HTTPException(403, "Local login requires a connection from the local network")
