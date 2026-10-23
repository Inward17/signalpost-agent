"""NAV Arbeidsplassen job-vacancy feed (official public API, public token). Ads are matched by employer orgnr."""
from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

from .dossier import Dossier
from .http import BudgetExhausted, Client

FEED = "https://pam-stilling-feed.nav.no"
FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "online.no", "live.no", "yahoo.com", "icloud.com", "hotmail.no", "msn.com"}


def on_feed_origin(url: str) -> bool:
    """The bearer token may only go to https://pam-stilling-feed.nav.no (default port, no embedded credentials)."""
    p, feed = urllib.parse.urlparse(url), urllib.parse.urlparse(FEED)
    try:
        port = p.port
    except ValueError:
        return False
    return p.scheme == "https" and p.hostname == feed.hostname and port in (None, 443) and not p.username and not p.password


def single_ad_url(ad: dict[str, Any]) -> str:
    """Always the ad's own page on Arbeidsplassen, never a search or listing link the ad data may carry."""
    link = str(ad.get("link") or "")
    if re.fullmatch(r"https://arbeidsplassen\.nav\.no/stillinger/stilling/[0-9a-f-]{36}", link):
        return link
    return f"https://arbeidsplassen.nav.no/stillinger/stilling/{ad.get('uuid')}"


def norm(name: str | None) -> str:
    return " ".join(re.findall(r"[^\W_]+", str(name or "").casefold()))  # unicode-aware: keeps ö, é, ü


class JobIndex:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.pages = 0
        self.window_start: str | None = None
        self.complete = False
        self.error: str | None = None
        self.token: str | None = None
        self.by_name: dict[str, list[dict[str, Any]]] = {}

    def build(self, client: Client, window_days: int, max_pages: int) -> None:
        self.token = os.environ.get("NAV_FEED_TOKEN")
        if not self.token:
            resp = client.get(FEED + "/api/publicToken", accept="text/plain")
            lines = [ln.strip() for ln in resp.text().splitlines() if ln.strip()] if resp.ok else []
            self.token = lines[-1] if lines else None
        if not self.token:
            self.error = "could not obtain NAV public feed token"
            return
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        self.window_start = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = {"Authorization": f"Bearer {self.token}", "If-Modified-Since": format_datetime(since, usegmt=True)}
        url: str | None = FEED + "/api/v1/feed"
        try:
            while url and self.pages < max_pages:
                resp = client.get(url, headers=headers, accept="application/json", max_bytes=8_000_000)
                headers.pop("If-Modified-Since", None)
                if resp.status == 304:
                    break
                if not resp.ok:
                    self.error = f"feed page failed: {resp.error}"
                    return
                body = resp.json()
                self.pages += 1
                for item in body.get("items", []):
                    entry = item.get("_feed_entry") or {}
                    if entry.get("uuid"):
                        self.entries[entry["uuid"]] = {**entry, "entry_url": FEED + item.get("url", "")}
                next_url = body.get("next_url")
                url = urllib.parse.urljoin(FEED, next_url) if next_url else None
                if url and not on_feed_origin(url):
                    self.error = f"feed pagination pointed off the NAV feed host or off https ({url[:80]}); stopped"  # never send the token elsewhere
                    url = None
                    break
            self.complete = url is None and not self.error
        except BudgetExhausted as exc:
            self.error = str(exc)
        # ponytail: index rebuilt per run; persist cursor in state dir if feed walking gets expensive
        for entry in self.entries.values():
            if entry.get("status") == "ACTIVE":
                self.by_name.setdefault(norm(entry.get("businessName")), []).append(entry)

    def candidates(self, d: Dossier) -> list[dict[str, Any]]:
        legal = norm(d.entity.get("navn"))
        if not legal or not self.by_name:
            return []
        names = {legal, *map(norm, d.subunit_names)}
        found = []
        for business, entries in self.by_name.items():
            if business in names or business.startswith(legal + " "):
                found.extend(entries)
        return sorted(found, key=lambda e: e.get("sistEndret") or "", reverse=True)


def collect_jobs(client: Client, d: Dossier, index: JobIndex, per_company: int = 15) -> None:
    if index.error and not index.entries:
        d.section("jobs", "blocked", f"NAV job feed unavailable: {index.error}")
        return
    legal = norm(d.entity.get("navn"))
    accepted = 0
    for entry in index.candidates(d)[:per_company]:
        if not on_feed_origin(entry["entry_url"]):
            continue  # entry URLs come from feed data: the bearer token only goes to the feed host
        resp = client.get(entry["entry_url"], headers={"Authorization": f"Bearer {index.token}"}, accept="application/json")
        if not resp.ok:
            continue
        body = resp.json()
        ad = body.get("ad_content") or {}
        employer = ad.get("employer") or {}
        orgnr = str(employer.get("orgnr") or "")
        if body.get("status") != "ACTIVE":
            continue
        if orgnr:
            if orgnr != d.org and orgnr not in d.subunit_orgs:
                continue  # same/similar name, different legal entity: never published
            proof = f"employer.orgnr = {orgnr}" + (" (registered subunit)" if orgnr != d.org else "")
        elif norm(employer.get("name")) == legal:
            proof = f"employer.name = '{employer.get('name')}' (exact registered legal name; orgnr not supplied)"
        else:
            continue
        locations = [", ".join(filter(None, [w.get("city") or w.get("municipal"), w.get("county")])) for w in ad.get("workLocations") or []]
        value = {
            "title": ad.get("title"), "job_title": ad.get("jobtitle") or None,
            "url": single_ad_url(ad),
            "published": (ad.get("published") or "")[:10] or None, "expires": (ad.get("expires") or "")[:10] or None,
            "application_due": ad.get("applicationDue"), "locations": [l for l in locations if l],
            "occupation": [c.get("level2") for c in ad.get("occupationCategories") or [] if c.get("level2")],
            "engagement": ad.get("engagementtype"), "extent": ad.get("extent"), "positions": ad.get("positioncount"),
            "employer_name": employer.get("name"), "source": "NAV Arbeidsplassen",
        }
        ev = d.add_evidence(resp, "official_job_feed", f"{proof}; title = '{ad.get('title')}'; status ACTIVE", url=entry["entry_url"])
        d.claim("job_posting", "jobs", value, [ev], key=f"job|{ad.get('uuid')}", effective_date=value["published"],
                confidence=1.0 if orgnr else 0.95)
        accepted += 1
        homepage = employer.get("homepage") or ""
        if orgnr == d.org and homepage:
            d.website_candidates.append({"url": homepage, "origin": "nav_employer_homepage"})
        for contact in ad.get("contactList") or []:
            domain = str(contact.get("email") or "").rpartition("@")[2].strip().lower()
            if orgnr == d.org and domain and domain not in FREE_MAIL and "." in domain:
                d.website_candidates.append({"url": domain, "origin": "nav_contact_email_domain"})
    scope = f"NAV feed changes since {index.window_start} ({index.pages} pages{'' if index.complete else ', partial'})"
    if accepted:
        d.section("jobs", "available", f"{accepted} active NAV ad(s) verified by employer organisation number; {scope}")
    else:
        d.section("jobs", "not_available", f"no active NAV ads for this organisation number or its subunits; {scope}")
