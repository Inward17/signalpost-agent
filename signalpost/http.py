"""Single outbound HTTP path: request budget, deadline, SSRF guard, robots, size limits."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

USER_AGENT = "signalpost-agent/1.0 (company research; +https://builderr.ai/challenges/signalpost)"
MAX_BYTES = 2_000_000


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


class BudgetExhausted(Exception):
    pass


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    body: bytes = b""
    content_type: str = ""
    error: str | None = None
    retrieved_at: str = field(default_factory=utc_now)
    elapsed_ms: int = 0
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None

    @property
    def sha256(self) -> str:
        return sha256(self.body)

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def _validated_ip(host: str, port: int) -> str:
    """Resolve once and require every address to be globally routable; return the address to connect to."""
    host = (host or "").lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("local host blocked")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ValueError("hostname did not resolve") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise ValueError("non-public address blocked")
    return addresses[0]


def assert_public_url(url: str) -> None:
    """Early reject of non-HTTP(S), odd ports, local names and non-public addresses (fast fail before any request)."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("only public http(s) URLs are allowed")
    if parsed.port not in (None, 80, 443):
        raise ValueError("non-standard port blocked")
    _validated_ip(host, parsed.port or (443 if parsed.scheme == "https" else 80))


def resolves(host: str) -> bool:
    try:
        assert_public_url(f"https://{host}/")
        return True
    except ValueError:
        return False


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to the exact address that passed validation, so a second DNS answer can never redirect the socket (no rebinding)."""

    def connect(self) -> None:
        self.sock = socket.create_connection((_validated_ip(self.host, self.port), self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        sock = socket.create_connection((_validated_ip(self.host, self.port), self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # TLS still verifies the real hostname


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # noqa: ANN001
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # noqa: ANN001
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-subscription-token", "x-api-key"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib must not follow redirects itself: Client.get follows them hop by hop so each one is validated,
    counted against the budget, rate-limited per host, and stripped of credentials when the origin changes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None  # urllib then raises HTTPError(3xx), which Client.get handles


def _origin(url: str) -> tuple[str, str, int]:
    p = urllib.parse.urlparse(url)
    return p.scheme, (p.hostname or "").lower(), p.port or (443 if p.scheme == "https" else 80)


def redirect_headers(headers: dict[str, str], current: str, target: str) -> dict[str, str]:
    """Headers for the next hop: credentials never cross to another origin (scheme, host or port)."""
    if _origin(current) == _origin(target):
        return dict(headers)
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


# ProxyHandler({}) ignores environment proxies so the pinned socket is the real destination
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPHandler(), _PinnedHTTPSHandler(), _NoRedirect())


class Client:
    """Every outbound request goes through here so budget and safety are enforced, not just reported."""

    def __init__(self, max_requests: int = 2000, deadline_s: float = 45 * 60, timeout: float = 15.0, reserve_s: float = 0.0,
                 max_cost_usd: float = 10.0):
        """reserve_s: tail of the deadline kept free for writing output; no request may start inside it."""
        self.max_requests = max_requests
        self.deadline = time.monotonic() + deadline_s - reserve_s
        self.timeout = timeout
        self.requests = 0
        self.bytes = 0
        self.by_host: dict[str, int] = {}
        self.latencies: list[int] = []
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Semaphore] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()
        self.local = threading.local()  # .dossier set by the runner to attribute requests per company
        self.third_party_cost_usd = 0.0
        self.max_cost_usd = max_cost_usd

    # -- budget -----------------------------------------------------------
    def remaining(self) -> int:
        return self.max_requests - self.requests

    def time_left(self) -> float:
        return self.deadline - time.monotonic()

    def _reserve(self, host: str) -> None:
        with self._lock:
            if self.requests >= self.max_requests:
                raise BudgetExhausted("request budget exhausted")
            if self.time_left() <= 0:
                raise BudgetExhausted("run deadline reached")
            self.requests += 1
            self.by_host[host] = self.by_host.get(host, 0) + 1
        owner = getattr(self.local, "dossier", None)
        if owner is not None:
            owner.requests += 1

    def reserve_cost(self, usd: float) -> None:
        """Called BEFORE any paid API request: refuses the call if it could push spend past the ceiling."""
        with self._lock:
            if self.third_party_cost_usd + usd > self.max_cost_usd:
                raise BudgetExhausted(f"third-party cost ceiling ${self.max_cost_usd:.2f} reached")
            self.third_party_cost_usd += usd

    def _host_slot(self, host: str) -> threading.Semaphore:
        with self._lock:
            if host not in self._host_locks:
                # ponytail: fixed per-host concurrency, token buckets if a source starts returning 429s
                self._host_locks[host] = threading.Semaphore(6 if host.endswith("brreg.no") else 2)
            return self._host_locks[host]

    # -- fetching -----------------------------------------------------------
    def get(self, url: str, *, headers: dict[str, str] | None = None, accept: str = "*/*", max_bytes: int = MAX_BYTES,
            check_robots: bool = False, retries: int = 1) -> Response:
        hop_headers = {"User-Agent": USER_AGENT, "Accept": accept, **(headers or {})}
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                assert_public_url(current)
            except ValueError as exc:
                return Response(url, current, 0, error=f"blocked_url: {exc}")
            if check_robots and not self.robots_allowed(current):
                return Response(url, current, 0, error="blocked_robots")
            resp, location = self._fetch_once(url, current, hop_headers, max_bytes, retries)
            if location is None:
                return resp
            target = urllib.parse.urljoin(current, location)
            hop_headers = redirect_headers(hop_headers, current, target)
            current = target
        return Response(url, current, 0, error=f"too many redirects (>{MAX_REDIRECTS})")

    def _fetch_once(self, original: str, url: str, headers: dict[str, str], max_bytes: int, retries: int) -> tuple[Response, str | None]:
        """One hop (with retries). Returns (response, redirect Location or None). Every attempt reserves budget."""
        host = urllib.parse.urlparse(url).hostname or ""
        last = Response(original, url, 0, error="not attempted")
        for attempt in range(retries + 1):
            self._reserve(host)
            started = time.monotonic()
            request = urllib.request.Request(url, headers=headers)
            location = None
            try:
                with self._host_slot(host):
                    timeout = max(1.0, min(self.timeout, self.time_left()))
                    with _OPENER.open(request, timeout=timeout) as resp:
                        body = resp.read(max_bytes + 1)
                        last = Response(original, resp.geturl(), resp.status, body[:max_bytes], resp.headers.get("content-type", ""),
                                        error="oversized" if len(body) > max_bytes else None,
                                        elapsed_ms=int((time.monotonic() - started) * 1000),
                                        headers={k.lower(): v for k, v in resp.headers.items()})
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location") if exc.code in REDIRECT_CODES and exc.headers else None
                last = Response(original, url, exc.code, error=None if location else f"HTTP {exc.code}",
                                elapsed_ms=int((time.monotonic() - started) * 1000))
            except ValueError as exc:  # pinned connection refused a non-public address
                return Response(original, url, 0, error=f"blocked_url: {exc}"), None
            except Exception as exc:  # timeouts, TLS, connection resets
                last = Response(original, url, 0, error=f"{type(exc).__name__}: {str(exc)[:160]}", elapsed_ms=int((time.monotonic() - started) * 1000))
            with self._lock:
                self.bytes += len(last.body)
                self.latencies.append(last.elapsed_ms)
            if location:
                return last, location
            if last.status in (429, 500, 502, 503, 504) and attempt < retries and self.time_left() > 30:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last, None
        return last, None

    def robots_allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}"
        with self._robots_lock:
            known = key in self._robots
        if not known:
            parser: urllib.robotparser.RobotFileParser | None = None
            resp = self.get(key + "/robots.txt", accept="text/plain", max_bytes=300_000, retries=0)
            if resp.status == 200 and not resp.error:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text().splitlines())
            elif resp.status in (401, 403):
                parser = urllib.robotparser.RobotFileParser()
                parser.disallow_all = True
            with self._robots_lock:
                self._robots[key] = parser
        parser = self._robots[key]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def sitemaps(self, base: str) -> list[str]:
        parsed = urllib.parse.urlparse(base)
        parser = self._robots.get(f"{parsed.scheme}://{parsed.netloc}")
        return list((parser.site_maps() if parser else None) or [])

    def stats(self) -> dict[str, Any]:
        lat = sorted(self.latencies)
        return {
            "requests": self.requests,
            "max_requests": self.max_requests,
            "bytes": self.bytes,
            "requests_by_host_top": dict(sorted(self.by_host.items(), key=lambda kv: -kv[1])[:15]),
            "p50_ms": lat[len(lat) // 2] if lat else None,
            "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        }
