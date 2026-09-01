from __future__ import annotations

from urllib.parse import urlparse

from socialoperator.config import SitePolicy


def is_url_allowed(url: str, policy: SitePolicy) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    host = parsed.hostname.lower()
    return host in policy.domains and any(
        parsed.path.startswith(prefix) for prefix in policy.allowed_path_prefixes
    )
