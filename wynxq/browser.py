"""The embedded browser's policy layer.

The view itself is Qt WebEngine, loaded lazily by the QML panel so a machine
without it still starts. What lives here is everything that should not be
decided inside a QML file: whether the engine is present at all, what counts as
a navigable URL, and what the model is allowed to be told about the page.

The browser is a tool the *user* drives. Page text reaches the model only when
the user attaches it, and it is attached as untrusted data — the same treatment
screen text already gets.
"""
from __future__ import annotations

import functools
import ipaddress
import os
from urllib.parse import quote, urlsplit, urlunsplit

# Anything else — file:, data:, javascript:, chrome: — is refused rather than
# quietly rewritten, so the address bar never lies about where you are.
ALLOWED_SCHEMES = ("http", "https")

DEFAULT_HOME = "https://duckduckgo.com/"
SEARCH_TEMPLATE = "https://duckduckgo.com/?q={}"

MAX_PAGE_TEXT = 60000


@functools.lru_cache(maxsize=1)
def engine_available() -> bool:
    """Is Qt WebEngine importable in this installation?

    Cached: the answer cannot change while the process runs, and the import is
    expensive enough that the panel should not repeat it on every open.
    """
    try:
        import PySide6.QtWebEngineQuick  # noqa: F401
    except Exception:
        return False
    return True


def initialize() -> bool:
    """Prepare Qt WebEngine. Must run before the QApplication is created."""
    if not engine_available():
        return False
    _relax_sandbox_for_root()
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick
        QtWebEngineQuick.initialize()
    except Exception:
        return False
    return True


def _relax_sandbox_for_root() -> None:
    """Chromium refuses to start as root unless its sandbox is disabled.

    Only relevant in a container or a root shell, where the sandbox has no
    boundary to defend anyway — every process already runs as root. For any
    normal user this is a no-op and the sandbox stays on. An explicit
    QTWEBENGINE_CHROMIUM_FLAGS is always left alone.
    """
    if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS") is not None:
        return
    try:
        if os.geteuid() != 0:
            return
    except AttributeError:                       # not a POSIX platform
        return
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"


def unavailable_reason() -> str:
    if engine_available():
        return ""
    return ("Qt WebEngine is not installed in this environment. "
            "Links still open in your system browser.")


def _candidate_host(value: str) -> str:
    """Hostname from a schemeless address candidate, or '' when malformed."""
    head = str(value or "").split("/", 1)[0].split("?", 1)[0]
    if not head or " " in head:
        return ""
    try:
        parsed = urlsplit("//" + head)
        # Accessing .port is validation: `example.com:nope` must not be accepted
        # as an address merely because its hostname happens to parse.
        _ = parsed.port
        return str(parsed.hostname or "")
    except ValueError:
        return ""


def _looks_like_host(value: str) -> bool:
    """Distinguish `example.com/x` from `fix the login bug`."""
    host = _candidate_host(value)
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "." not in host:
        return False
    label = host.rsplit(".", 1)[-1]
    return label.isalpha() and len(label) >= 2


def _schemeless_is_loopback(value: str) -> bool:
    """Whether a host typed without a scheme is the local machine.

    Local development servers conventionally speak plain HTTP. Guessing HTTPS
    for `localhost:3000` makes a valid address look broken, while public hosts
    should still get the safer HTTPS default.
    """
    host = _candidate_host(value)
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize(text: str) -> str:
    """Turn what the user typed into a URL, or into a search.

    Returns '' when the input cannot be navigated to at all — a `file://` path
    or a `javascript:` snippet — so the caller can refuse instead of guessing.
    Schemeless loopback addresses default to HTTP for local development;
    internet hosts continue to default to HTTPS.
    """
    value = str(text or "").strip()
    if not value:
        return ""
    if any(ord(char) < 32 for char in value):
        return ""

    lowered = value.lower()
    authority = value.split("/", 1)[0]
    if "://" in value:
        scheme = lowered.split("://", 1)[0]
        if scheme not in ALLOWED_SCHEMES:
            return ""
    elif ":" in authority and not _looks_like_host(value):
        # `javascript:`, `data:`, `about:` and malformed host:port input are
        # refused, not turned into a search that hides the typing error.
        head = lowered.split(":", 1)[0]
        if head.isalpha() or "." in head or head.startswith("["):
            return ""

    if "://" not in value:
        if _looks_like_host(value):
            value = ("http://" if _schemeless_is_loopback(value) else "https://") + value
        else:
            return SEARCH_TEMPLATE.format(quote(value, safe=""))

    try:
        parsed = urlsplit(value)
        # As above, force port validation before the URL reaches WebEngine.
        _ = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc or not parsed.hostname:
        return ""
    return urlunsplit(parsed)


def display_url(url: str) -> str:
    """The address bar's reading of a URL: no scheme noise, no trailing slash."""
    value = str(url or "").strip()
    if not value or value == "about:blank":
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in ALLOWED_SCHEMES:
        return value
    shown = parsed.netloc + parsed.path
    if parsed.query:
        shown += "?" + parsed.query
    return shown.rstrip("/") or parsed.netloc


def host_of(url: str) -> str:
    try:
        return urlsplit(str(url or "")).netloc
    except ValueError:
        return ""


def is_secure(url: str) -> bool:
    try:
        return urlsplit(str(url or "")).scheme == "https"
    except ValueError:
        return False


def is_local(url: str) -> bool:
    """Is this a loopback address?

    Plain HTTP to `127.0.0.1` is not the risk that plain HTTP to the internet
    is, and a warning triangle on your own dev server is a warning people learn
    to ignore. It gets a neutral mark instead.
    """
    try:
        host = str(urlsplit(str(url or "")).hostname or "")
    except ValueError:
        return False
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def page_context(url: str, title: str, text: str) -> dict:
    """A page, packaged for the composer's context list.

    Bounded, and labelled as web content so the prompt builder can frame it as
    data rather than instructions.
    """
    body = str(text or "")
    truncated = len(body) > MAX_PAGE_TEXT
    if truncated:
        body = body[:MAX_PAGE_TEXT]
    heading = str(title or "").strip() or display_url(url) or "Web page"
    return {
        "url": str(url or ""),
        "title": heading,
        "host": host_of(url),
        "text": body,
        "truncated": truncated,
        "secure": is_secure(url),
    }