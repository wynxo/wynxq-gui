"""Validation and classification for user-configured Ollama origins."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .ollama import OllamaClient

def validate_workspace_endpoint(endpoint: str) -> str:
    """Validate an explicit Ollama origin without forcing it to loopback."""
    value = str(endpoint or "").strip()
    if not value or any(ord(c) < 33 for c in value):
        raise ValueError("Enter an Ollama URL such as http://192.168.1.50:11434")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Ollama URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Ollama URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Ollama URL needs a host name or IP address")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Put credentials in a reverse proxy, not in the Ollama URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use the Ollama server origin only, with no path, query, or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Ollama port must be between 1 and 65535")

    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    except ValueError:
        host = host.rstrip(".").lower()
        if not host or len(host) > 253 or any(len(label) > 63 for label in host.split(".")):
            raise ValueError("Invalid Ollama host name")
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-._")
        if any(ch not in allowed for ch in host):
            raise ValueError("Invalid Ollama host name")
    return f"{parsed.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def endpoint_scope(endpoint: str) -> str:
    """Human-facing scope for the endpoint status shown by the UI."""
    try:
        parsed = urlsplit(validate_workspace_endpoint(endpoint))
        host = parsed.hostname or ""
        if host == "localhost":
            return "local"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            lowered = host.lower()
            if lowered.endswith((".local", ".lan", ".home", ".home.arpa", ".internal")):
                return "lan"
            return "remote"
        if address.is_loopback:
            return "local"
        if address.is_private or address.is_link_local:
            return "lan"
        return "remote"
    except Exception:
        return "invalid"


class WorkspaceOllamaClient(OllamaClient):
    """Ollama client whose endpoint policy permits explicit non-loopback origins."""

    endpoint_validator = staticmethod(validate_workspace_endpoint)


__all__ = ['WorkspaceOllamaClient']
