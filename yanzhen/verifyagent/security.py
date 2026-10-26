"""Exact-origin local/test policy. No arbitrary DNS, redirects, credentials or code."""
from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
import posixpath

from .schema import Target


class PolicyError(ValueError):
    pass


def origin(url: str) -> str:
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.fragment:
        raise PolicyError("Only credential-free HTTP(S) targets are allowed")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError:
        raise PolicyError("Invalid port") from None
    host = p.hostname.lower()
    if host == "localhost":
        host = "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise PolicyError("This release accepts literal test IPs or localhost, preventing DNS rebinding") from None
    if address.is_link_local or address.is_multicast or address.is_unspecified or (not address.is_private and not address.is_loopback) or (address.is_reserved and not address.is_loopback):
        raise PolicyError("Public, metadata, multicast and reserved targets are blocked")
    netloc = f"[{host}]" if address.version == 6 else host
    return f"{p.scheme}://{netloc}:{port}"


class TargetPolicy:
    def __init__(self, target: Target, allowed: str | None = None):
        self.target = target
        if not target.authorized:
            raise PolicyError("Explicit local/test target authorization is required")
        self.allowed = {origin(x.strip()) for x in (allowed if allowed is not None else os.getenv("YZ_VERIFY_ALLOWED_ORIGINS", "")).split(",") if x.strip()}
        self.base_origin = origin(target.base_url)
        base_path = urlsplit(target.base_url).path or "/"
        self.path_prefix = base_path if base_path.endswith("/") else posixpath.dirname(base_path) + "/"
        if self.base_origin not in self.allowed:
            raise PolicyError("Target origin is not in server-side YZ_VERIFY_ALLOWED_ORIGINS")
        # The acceptance control plane is never a permissible target.
        if self.base_origin in {f"http://127.0.0.1:{os.getenv('YZ_PORT', '8765')}"}:
            raise PolicyError("The acceptance control plane cannot be the tested target")
        self.validate(target.base_url)

    def validate(self, url: str) -> str:
        absolute = urljoin(self.target.base_url.rstrip("/") + "/", url)
        p = urlsplit(absolute)
        if p.scheme == "about" and absolute == "about:blank":
            return absolute
        if origin(absolute) != self.base_origin:
            raise PolicyError("Cross-origin requests and redirects are blocked")
        if re.search(r"[\x00-\x20\\]", absolute):
            raise PolicyError("Ambiguous URL encoding")
        decoded = p.path
        for _ in range(3):
            decoded = unquote(decoded)
        normalized = posixpath.normpath(decoded)
        if "\\" in decoded or not (normalized + ("/" if decoded.endswith("/") else "")).startswith(self.path_prefix):
            raise PolicyError("Request escapes the authorized application path")
        # Normalize localhost before connecting; no network DNS resolution is required.
        fixed = urlsplit(self.base_origin)
        return urlunsplit((p.scheme, fixed.netloc, p.path or "/", p.query, ""))


def secret_headers(target: Target, actor: str) -> dict[str, str]:
    if actor == "anonymous":
        return {}
    if actor not in target.identities:
        raise PolicyError("Required test identity was not configured")
    output = {}
    for header, env in target.identities[actor].header_env.items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", header) or not re.fullmatch(r"YZ_VERIFY_SECRET_[A-Z0-9_]{1,80}", env):
            raise PolicyError("Identity headers must use named server-side secret references")
        if header.lower() in {"host", "origin", "content-length", "connection", "proxy-authorization"}:
            raise PolicyError("Routing headers cannot be configured by an identity")
        value = os.getenv(env)
        if not value or "\n" in value or "\r" in value:
            raise PolicyError("Required identity secret is unavailable")
        output[header] = value
    return output


class Redactor:
    def __init__(self, target: Target | None=None):
        self.values = {v for actor in (target.identities if target else {}) for v in secret_headers(target, actor).values()}
        self.values |= {value for key,value in os.environ.items() if value and (key in {'YZ_LLM_API_KEY','YZ_DEEPSEEK_API_KEY','DEEPSEEK_API_KEY','YZ_SWARM_PROXY_KEY'} or key.startswith('YZ_VERIFY_SECRET_'))}
        self.values |= {v[7:] for v in self.values if v.lower().startswith("bearer ") and len(v)>7}

    def __call__(self, obj):
        if isinstance(obj, dict):
            return {k: "[REDACTED]" if re.search(r"password|token|secret|authorization|cookie|api.?key", k, re.I) else self(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self(v) for v in obj]
        if isinstance(obj, str):
            for value in sorted(self.values, key=len, reverse=True):
                obj = obj.replace(value, "[REDACTED]")
            return obj[:16000]
        return obj
