"""Security utilities for input sanitization and validation."""

from urllib.parse import urlparse


def escape_css_string(value: str) -> str:
    """Escape a string for safe CSS selector interpolation.

    Handles single quotes, double quotes, backslashes, newlines,
    null bytes, and other special CSS characters.
    """
    if not isinstance(value, str):
        return ""
    # Escape backslashes first, then quotes, then control chars
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "\\'")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n ")
    value = value.replace("\r", "\\r ")
    value = value.replace("\x00", "")
    return value


def escape_xpath_string(value: str) -> str:
    """Escape quotes in a string for safe XPath interpolation."""
    if not isinstance(value, str):
        return ""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", '.', ".join(f"'{p}'" for p in parts) + ")"


def validate_url(url: str, blocked_domains: set, allowed_domains: set) -> bool:
    """
    Validate URL against block/allow lists using proper domain extraction.
    Returns True if URL is allowed, False if blocked.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return False

    hostname_lower = hostname.lower()

    # Check blocked domains (exact domain or subdomain match)
    for blocked in blocked_domains:
        blocked = blocked.lower().strip()
        if not blocked:
            continue
        if hostname_lower == blocked or hostname_lower.endswith("." + blocked):
            return False

    # Check allowed domains (if specified, only allow exact matches)
    if allowed_domains:
        for allowed in allowed_domains:
            allowed = allowed.lower().strip()
            if not allowed:
                continue
            if hostname_lower == allowed or hostname_lower.endswith("." + allowed):
                return True
        return False  # allowed_domains specified but no match

    return True


# ---------------------------------------------------------------------------
# Additional security hardening utilities
# ---------------------------------------------------------------------------


def set_resource_limits(max_cpu_seconds: int = 300, max_memory_gb: float = 8.0):
    """Set process resource limits (CPU & memory)."""
    try:
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds)
        )
        max_mem_bytes = int(max_memory_gb * 1024 * 1024 * 1024)
        resource.setrlimit(resource.RLIMIT_AS, (max_mem_bytes, max_mem_bytes))
    except (ValueError, OSError, ImportError):
        pass  # May not be available on all platforms (e.g. Windows)


def validate_action_json(action_json: str) -> bool:
    """Validate action JSON format and content."""
    import json

    try:
        data = json.loads(action_json)
        if "action" not in data:
            return False
        allowed_actions = {"click", "type", "scroll", "goto", "wait", "finish"}
        if data["action"] not in allowed_actions:
            return False
        if "params" in data and not isinstance(data["params"], dict):
            return False
        return True
    except json.JSONDecodeError:
        return False


def validate_url_strict(
    url: str, blocked_domains: set, allowed_domains: set
) -> bool:
    """Strict URL validation with additional checks."""
    if not validate_url(url, blocked_domains, allowed_domains):
        return False

    # Block data URLs
    if url.startswith("data:"):
        return False

    # Block javascript URLs
    if url.startswith("javascript:"):
        return False

    # Block extremely long URLs (potential buffer overflow)
    if len(url) > 2048:
        return False

    return True


def validate_selector(selector: str) -> bool:
    """Validate CSS/XPath selector to prevent injection."""
    import re

    # Block dangerous patterns
    dangerous_patterns = [
        r"<script",
        r"javascript:",
        r"on\w+=",  # Event handlers
        r"url\s*\(",
        r"expression\s*\(",  # CSS expressions
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, selector, re.IGNORECASE):
            return False
    return True

