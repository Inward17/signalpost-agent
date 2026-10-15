"""Terminal envelope, refresh diff against the previous snapshot, and evidence-cited synthesis."""
from __future__ import annotations

from typing import Any

from .dossier import SECTIONS, Dossier
from .http import sha256

SCHEMA = "signalpost-envelope/1.0"
# keys whose disappearance is a real-world change; dated feeds (announcements, news, filings) just roll out of window
REMOVABLE = ("job|", "role|", "subunit|", "social|", "email|", "phone|", "official_website", "careers_page")
MATERIAL = ("legal_name", "registry_status", "legal_form", "registered_business_address", "official_website", "role|DAGL", "role|LEDE",
            "revenue|", "operating_result|", "net_result|")
CHANGE_NAMES = {"job|": ("new_job", "closed_job"), "role|": ("new_role", "removed_role"), "subunit|": ("new_location", "closed_location"),
                "social|": ("new_social_profile", "removed_social_profile"), "update|": ("new_registry_change", None),
                "news|": ("new_company_news", None)}
FIN_FIELDS = ("revenue", "operating_result", "profit_before_tax", "net_result", "total_assets", "equity", "total_debt", "payroll_costs", "audit_status")


def _change_type(claim: dict[str, Any], kind: str) -> str:
    key = claim["claim_key"]
    for prefix, (added, removed) in CHANGE_NAMES.items():
        if key.startswith(prefix):
            return (added if kind == "added" else removed) or f"{kind}_{claim['field']}"
    if claim["field"] in FIN_FIELDS and kind == "added":
        return "new_filing"
    if claim["field"] == "website_description":
        return "changed_description"
    return f"{kind}_{claim['field']}"


def diff(d: Dossier, previous: dict[str, Any] | None, now: str) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Returns (changes, carried_stale_claims, refresh_meta). Same snapshot in => no changes out (idempotent)."""
    if not previous:
        for c in d.claims:
            c["first_observed_at"] = c["last_observed_at"] = now
        return [], [], {"is_first_run": True, "previous_run_id": None}
    prev_claims = {c["claim_key"]: c for c in previous.get("claims", [])}
    prev_evidence = {e["id"]: e for e in previous.get("evidence", [])}
    current_keys = {c["claim_key"] for c in d.claims}
    changes, carried = [], []
    unchanged = 0

    def change(kind: str, old: dict | None, new: dict | None) -> None:
        ref = new or old
        changes.append({
            "change_id": "ch-" + sha256(f"{d.org}|{ref['claim_key']}|{old and old['claim_id']}|{new and new['claim_id']}")[:16],
            "change_type": _change_type(ref, kind) if kind != "changed" else ("changed_description" if ref["field"] == "website_description" else f"changed_{ref['field']}"),
            "field": ref["field"], "claim_key": ref["claim_key"],
            "material": any(ref["claim_key"].startswith(m) for m in MATERIAL),
            "old_value": old and old["value"], "new_value": new and new["value"],
            "old_claim_id": old and old["claim_id"], "new_claim_id": new and new["claim_id"],
            "old_evidence": [prev_evidence[i] for i in (old or {}).get("evidence_ids", []) if i in prev_evidence],
            "new_evidence_ids": (new or {}).get("evidence_ids", []),
            "detected_at": now,
        })

    for c in d.claims:
        p = prev_claims.get(c["claim_key"])
        c["last_observed_at"] = now
        if p and p["claim_id"] == c["claim_id"]:
            c["first_observed_at"] = p.get("first_observed_at") or now
            unchanged += 1
            continue
        c["first_observed_at"] = now
        change("changed" if p else "added", p, c)
    for key, p in prev_claims.items():
        if key in current_keys:
            continue
        state = d.sections.get(p.get("section"), {}).get("state")
        if state in ("available", "not_available", "ambiguous"):  # source checked successfully this run
            if key.startswith(REMOVABLE) and not p.get("stale"):
                change("removed", p, None)
        elif state in ("blocked", "failed", None):
            # failed refresh keeps the last supported value and says so
            carried.append({**p, "stale": True, "note": f"retained from previous run: {p.get('section')} source {state or 'not checked'} this run"})
            for ev_id in p.get("evidence_ids", []):
                if ev_id in prev_evidence:
                    d.evidence.setdefault(ev_id, {**prev_evidence[ev_id], "retained_from_previous_run": True})
    meta = {"is_first_run": False, "previous_run_id": (previous.get("run") or {}).get("run_id"),
            "previous_completed_at": (previous.get("run") or {}).get("completed_at"),
            "unchanged_claims": unchanged, "changed_or_added": sum(1 for x in changes if x["new_claim_id"]),
            "removed": sum(1 for x in changes if not x["new_claim_id"]), "retained_stale_claims": len(carried)}
    return changes, carried, meta


# -- synthesis --------------------------------------------------------------------------
def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    s = f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a / 1e3:.0f}k" if a >= 1e3 else f"{a:.0f}"
    return ("-" if v < 0 else "") + s


def synthesize(d: Dossier, claims: list[dict], changes: list[dict], first_run: bool) -> dict[str, Any]:
    by_field: dict[str, list[dict]] = {}
    for c in claims:
        by_field.setdefault(c["field"], []).append(c)
    one = lambda f: (by_field.get(f) or [None])[0]  # noqa: E731
    points: list[dict[str, Any]] = []

    def say(text: str, *cs: dict | None) -> None:
        ids = [c["claim_id"] for c in cs if c]
        if ids:
            points.append({"text": text, "claim_ids": ids})

    name, form, muni, ind = one("legal_name"), one("legal_form"), one("municipality"), one("industry")
    founded, status, emp = one("founded_date"), one("registry_status"), one("registered_employees")
    if name:
        label = (ind["value"][0].get("label") if ind and ind["value"] else None) or "unspecified industry"
        say(f"{name['value']} is registered as {form['value']['label'].lower() + ' (' + form['value']['code'] + ')' if form else 'an entity'}"
            f"{' based in ' + muni['value'].title() if muni else ''}, registered under '{label}'"
            f"{', founded ' + founded['value'] if founded else ''}.", name, form, muni, ind, founded)
    if status and status["value"] != "active":
        say(f"Registry status: {status['value'].replace('_', ' ')}.", status)
    desc = one("website_description") or one("registered_activity")
    if desc:
        src = "its website" if desc["field"] == "website_description" else "its registered purpose"
        say(f"What it does (per {src}): {str(desc['value'])[:240]}", desc)
    if emp:
        say(f"{emp['value']} employees registered (as of {emp.get('effective_date') or 'n/a'}).", emp)
    revenues = sorted([c for c in by_field.get("revenue", []) if c["value"]["statement"] == "selskap"], key=lambda c: c["reporting_period"], reverse=True)
    if revenues:
        latest = revenues[0]
        period = latest["reporting_period"]
        op = next((c for c in by_field.get("operating_result", []) if c["reporting_period"] == period and c["value"]["statement"] == "selskap"), None)
        net = next((c for c in by_field.get("net_result", []) if c["reporting_period"] == period and c["value"]["statement"] == "selskap"), None)
        text = f"Latest filed accounts ({period[-10:-6]}): revenue {_money(latest['value']['amount'])} {latest['value']['currency']}"
        text += f", operating result {_money(op['value']['amount'])}" if op else ""
        text += f", net result {_money(net['value']['amount'])}" if net else ""
        if len(revenues) > 1 and revenues[1]["value"]["amount"]:
            growth = (latest["value"]["amount"] - revenues[1]["value"]["amount"]) / abs(revenues[1]["value"]["amount"]) * 100
            text += f"; revenue {'up' if growth >= 0 else 'down'} {abs(growth):.0f}% vs {revenues[1]['reporting_period'][-10:-6]} (calculated)"
        say(text + ".", latest, op, net, revenues[1] if len(revenues) > 1 else None)
    leaders = [c for c in by_field.get("role", []) if c["value"]["role_code"] in ("DAGL", "LEDE")]
    if leaders:
        say("Leadership: " + "; ".join(f"{c['value']['role']}: {c['value']['name']}" for c in leaders) + ".", *leaders)
    subs = by_field.get("registered_workplace", [])
    if subs:
        places = sorted({c["value"].get("municipality") or "" for c in subs} - {""})
        say(f"{len(subs)} registered workplace(s){': ' + ', '.join(p.title() for p in places[:8]) if places else ''}.", *subs)
    site = one("official_website")
    if site:
        say(f"Verified website: {site['value']['url']} ({site['value']['identity_method']}).", site)
    socials = by_field.get("social_profile", [])
    if socials:
        say("Company-linked profiles: " + ", ".join(c["value"]["platform"] for c in socials) + ".", *socials)
    jobs = [c for c in by_field.get("job_posting", []) if not c.get("stale")]
    if jobs:
        say(f"Hiring: {len(jobs)} open position(s), e.g. " + "; ".join(str(c["value"]["title"])[:60] for c in jobs[:3]) + ".", *jobs[:3])
    news = sorted(by_field.get("company_news", []), key=lambda c: c.get("effective_date") or "", reverse=True)
    if news:
        say("Latest company news: " + "; ".join(f"{c['value']['date']} {c['value']['title'][:70]}" for c in news[:3]) + ".", *news[:3])
    updates = sorted(by_field.get("registry_change", []), key=lambda c: c.get("effective_date") or "", reverse=True)
    if updates:
        say("Recent official register changes: " + "; ".join(f"{c['value']['date']} " + (", ".join(x['field'] for x in c['value']['changes']) or c['value']['type'])
            for c in updates[:3]) + ".", *updates[:3])
    unknowns = []
    for name_, sec in d.sections.items():
        if sec["state"] != "available":
            unknowns.append({"section": name_, "state": sec["state"], "reason": sec["reason"]})
    change_text = [f"{c['change_type']}: {c['field']} {'→ ' + str(c['new_value'])[:80] if c['new_value'] is not None else '(no longer listed)'}" for c in changes[:10]]
    return {
        "headline": points[0]["text"] if points else f"Organisation {d.org}: no published facts.",
        "points": points,
        "changes": change_text or ["First observation of this company; no previous snapshot to compare." if first_run else "No changes since the previous run."],
        "unknowns": unknowns,
        "method": "deterministic template over published claims (no LLM); every point cites claim_ids",
    }


def build(d: Dossier, *, run: dict[str, Any], previous: dict[str, Any] | None, now: str) -> dict[str, Any]:
    for name in SECTIONS:
        d.sections.setdefault(name, {"state": "not_available", "reason": "source not reached in this run"})
    changes, carried, refresh = diff(d, previous, now)
    claims = d.claims + carried
    for c in carried:  # a failed source with a retained value still has an answer to show
        sec = d.sections.get(c["section"])
        if sec and sec["state"] in ("blocked", "failed"):
            sec["retained_stale_claims"] = sec.get("retained_stale_claims", 0) + 1
    e = d.entity
    legal_identity = {
        "organisation_number": d.org,
        "legal_name": e.get("navn"),
        "legal_form": (e.get("organisasjonsform") or {}).get("kode"),
        "status": next((c["value"] for c in claims if c["field"] == "registry_status"), None),
        "registered_address": next((c["value"] for c in claims if c["field"] == "registered_business_address"), None),
        "municipality": (e.get("forretningsadresse") or {}).get("kommune"),
        "industry": next((c["value"] for c in claims if c["field"] == "industry"), None),
        "registry_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{d.org}",
        "public_register_page": f"https://virksomhet.brreg.no/nb/oppslag/enheter/{d.org}",
    }
    site = next((c["value"] for c in claims if c["field"] == "official_website"), None)
    public_brand = {
        "brand_names": [c["value"] for c in claims if c["field"] == "public_brand"],
        "official_website": site and site["url"],
        "social_profiles": [c["value"] for c in claims if c["field"] == "social_profile"],
        "relationship": "exact_entity" if site else None,
    }
    snapshots = {}
    for ev in d.evidence.values():
        snapshots.setdefault((ev["source_url"], ev["content_sha256"]), {
            "url": ev["source_url"], "content_sha256": ev["content_sha256"], "retrieved_at": ev["retrieved_at"],
            "source_class": ev["source_class"], "http_status": ev["http_status"]})
    identity_state = d.sections["identity"]["state"]
    return {
        "schema_version": SCHEMA,
        "organisation_number": d.org,
        "state": "available" if identity_state == "available" else identity_state,
        "run": run,
        "legal_identity": legal_identity,
        "public_brand": public_brand,
        "sections": {k: d.sections[k] for k in SECTIONS},
        "summary": synthesize(d, claims, changes, refresh["is_first_run"]),
        "claims": sorted(claims, key=lambda c: (SECTIONS.index(c["section"]) if c["section"] in SECTIONS else 99, c["claim_key"])),
        "evidence": sorted(d.evidence.values(), key=lambda e_: e_["id"]),
        "source_snapshots": sorted(snapshots.values(), key=lambda s: (s["url"], s["content_sha256"])),
        "refresh": refresh,
        "changes": changes,
        "errors": d.errors,
        "operations": {"requests": d.requests, "third_party_cost_usd": round(d.cost_usd, 4)},
    }
