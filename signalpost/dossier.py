"""Per-company fact store: claims, evidence and section availability states."""
from __future__ import annotations

import json
import threading
from typing import Any

from .http import Response, sha256, utc_now

STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")
SECTIONS = (
    "identity", "financials", "leadership", "locations", "website", "social_profiles",
    "contact", "jobs", "public_activity",
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Dossier:
    def __init__(self, org: str, seed: dict[str, Any] | None = None):
        self.org = org
        self.seed = seed or {}
        self.entity: dict[str, Any] = {}       # raw live registry entity (identity anchor)
        self.subunit_orgs: set[str] = set()
        self.subunit_names: list[str] = []
        self.website_candidates: list[dict[str, str]] = []
        self.claims: list[dict[str, Any]] = []
        self.evidence: dict[str, dict[str, Any]] = {}
        self.sections: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, Any]] = []
        self.requests = 0
        self.cost_usd = 0.0
        self.frozen = False  # set at deadline: late-finishing threads can no longer mutate the envelope
        self.lock = threading.Lock()

    # -- evidence & claims -------------------------------------------------
    def add_evidence(self, resp: Response | None, source_class: str, span: str, *, url: str | None = None,
                     extraction: str = "deterministic") -> str:
        source_url = url or (resp.final_url if resp else "")
        content = resp.sha256 if resp else sha256(span)
        ev_id = "ev-" + sha256(f"{source_url}|{content}|{span}")[:14]
        with self.lock:
            self.evidence.setdefault(ev_id, {
                "id": ev_id,
                "source_url": source_url,
                "requested_url": resp.url if resp else source_url,
                "source_class": source_class,
                "retrieved_at": resp.retrieved_at if resp else utc_now(),
                "http_status": resp.status if resp else None,
                "content_sha256": content,
                "claim_span": span[:500],
                "extraction_method": extraction,
            })
        return ev_id

    def claim(self, field: str, section: str, value: Any, evidence_ids: list[str], *, key: str | None = None,
              confidence: float = 1.0, reporting_period: str | None = None, effective_date: str | None = None,
              method: str = "deterministic", note: str | None = None) -> dict[str, Any]:
        """key = stable identity of the fact (for refresh diffs); claim_id also hashes the value."""
        key = key or field
        claim = {
            "claim_id": "cl-" + sha256(f"{self.org}|{key}|{canonical(value)}")[:16],
            "claim_key": key,
            "field": field,
            "section": section,
            "value": value,
            "availability": "available",
            "confidence": confidence,
            "evidence_ids": evidence_ids,
            "reporting_period": reporting_period,
            "effective_date": effective_date,
            "extraction_method": method,
        }
        if note:
            claim["note"] = note
        with self.lock:
            if not self.frozen and not any(c["claim_id"] == claim["claim_id"] for c in self.claims):
                self.claims.append(claim)
        return claim

    def section(self, name: str, state: str, reason: str, **extra: Any) -> None:
        assert state in STATES, state
        with self.lock:
            if self.frozen:
                return
            current = self.sections.get(name)
            # an available result is never downgraded by a later, weaker source check
            if current and current["state"] == "available" and state != "available":
                return
            if current and current["state"] == state == "available" and current["reason"] != reason:
                reason = f"{current['reason']}; {reason}"
                extra = {**{k: v for k, v in current.items() if k not in ("state", "reason")}, **extra}
            self.sections[name] = {"state": state, "reason": reason, **extra}

    def error(self, stage: str, message: str) -> None:
        with self.lock:
            self.errors.append({"stage": stage, "message": message[:300], "at": utc_now()})

    def values(self, field: str) -> list[Any]:
        return [c["value"] for c in self.claims if c["field"] == field]

    def first(self, field: str) -> Any:
        found = self.values(field)
        return found[0] if found else None
