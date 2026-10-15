"""Single outbound HTTP path: request budget, deadline, SSRF guard, robots, size limits."""
from __future__ import annotations

import hashlib
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


def assert_public_url(url: str) -> None:
    """Reject non-HTTP(S), localhost and any host resolving to a non-global address (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("only public http(s) URLs are allowed")
    if parsed.port not in (None, 80, 443):
        raise ValueError("non-standard port blocked")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("local host blocked")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ValueError("hostname did not resolve") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("non-public address blocked")


def resolves(host: str) -> bool:
    try:
        assert_public_url(f"https://{host}/")
        return True
    except ValueError:
        return False


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        assert_public_url(newurl)  # re-validate every hop (DNS rebinding / open redirect)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect())


class Client:
    """Every outbound request goes through here so budget and safety are enforced, not just reported."""

    def __init__(self, max_requests: int = 2000, deadline_s: float = 45 * 60, timeout: float = 15.0):
        self.max_requests = max_requests
        self.deadline = time.monotonic() + deadline_s
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

    def _host_slot(self, host: str) -> threading.Semaphore:
        with self._lock:
            if host not in self._host_locks:
                # ponytail: fixed per-host concurrency, token buckets if a source starts returning 429s
                self._host_locks[host] = threading.Semaphore(6 if host.endswith("brreg.no") else 2)
            return self._host_locks[host]

    # -- fetching -----------------------------------------------------------
    def get(self, url: str, *, headers: dict[str, str] | None = None, accept: str = "*/*", max_bytes: int = MAX_BYTES,
            check_robots: bool = False, retries: int = 1) -> Response:
        try:
            assert_public_url(url)
        except ValueError as exc:
            return Response(url, url, 0, error=f"blocked_url: {exc}")
        host = urllib.parse.urlparse(url).hostname or ""
        if check_robots and not self.robots_allowed(url):
            return Response(url, url, 0, error="blocked_robots")
        last = Response(url, url, 0, error="not attempted")
        for attempt in range(retries + 1):
            self._reserve(host)
            started = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, **(headers or {})})
            try:
                with self._host_slot(host):
                    timeout = max(2.0, min(self.timeout, self.time_left()))
                    with _OPENER.open(request, timeout=timeout) as resp:
                        body = resp.read(max_bytes + 1)
                        last = Response(url, resp.geturl(), resp.status, body[:max_bytes], resp.headers.get("content-type", ""),
                                        error="oversized" if len(body) > max_bytes else None,
                                        elapsed_ms=int((time.monotonic() - started) * 1000),
                                        headers={k.lower(): v for k, v in resp.headers.items()})
            except urllib.error.HTTPError as exc:
                last = Response(url, url, exc.code, error=f"HTTP {exc.code}", elapsed_ms=int((time.monotonic() - started) * 1000))
            except ValueError as exc:  # redirect to blocked address
                return Response(url, url, 0, error=f"blocked_url: {exc}")
            except Exception as exc:  # timeouts, TLS, connection resets
                last = Response(url, url, 0, error=f"{type(exc).__name__}: {str(exc)[:160]}", elapsed_ms=int((time.monotonic() - started) * 1000))
            with self._lock:
                self.bytes += len(last.body)
                self.latencies.append(last.elapsed_ms)
            if last.status in (429, 500, 502, 503, 504) and attempt < retries and self.time_left() > 30:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        return last

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
