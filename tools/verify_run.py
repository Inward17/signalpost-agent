#!/usr/bin/env python3
"""Check one run's output against the Signalpost contract rules. Exit 0 only if every hard rule passes.

    python tools/verify_run.py --input batch.jsonl --output out [--spot-check 5] [--max-requests 2000] [--max-minutes 45]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import read_inputs  # noqa: E402
from signalpost.registry import FIN_FIELDS as FIN_PATHS  # noqa: E402
from signalpost.website import is_news_item, social_handle_matches  # noqa: E402

STATES = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
SECTIONS = {"identity", "financials", "leadership", "locations", "website", "social_profiles", "contact", "jobs", "public_activity"}
FIN = {"revenue", "operating_result", "profit_before_tax", "net_result", "total_assets", "equity", "total_debt", "payroll_costs"}
REQUIRED = ("organisation_number", "state", "run", "legal_identity", "sections", "summary", "claims", "evidence", "source_snapshots",
            "refresh", "changes", "errors", "operations")


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "signalpost-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--spot-check", type=int, default=5, help="companies whose financials/name are re-fetched from source")
    ap.add_argument("--max-requests", type=int, default=2000)
    ap.add_argument("--max-minutes", type=float, default=45)
    a = ap.parse_args()

    fails: list[str] = []
    warns: list[str] = []
    fail = fails.append
    orgs, _, invalid = read_inputs(a.input)
    envs = [json.loads(l) for l in (a.output / "envelopes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    report = json.loads((a.output / "run-report.json").read_text(encoding="utf-8"))
    out_orgs = [e.get("organisation_number") for e in envs]

    # R1 one terminal envelope per input
    expected = set(orgs) | {i["organisation_number"] for i in invalid}
    if len(envs) != len(orgs) + len(invalid):
        fail(f"R1 envelope count {len(envs)} != inputs {len(orgs) + len(invalid)}")
    if len(set(out_orgs)) != len(out_orgs):
        fail("R1 duplicate envelopes")
    if set(out_orgs) != expected:
        fail(f"R1 org set mismatch: missing {sorted(expected - set(out_orgs))[:5]} extra {sorted(set(out_orgs) - expected)[:5]}")
    if not (a.output / "report.html").exists():
        fail("R1 report.html missing")

    counts = {"claims": 0, "evidence": 0, "websites": [], "jobs": 0, "stale": 0, "changes": 0}
    for e in envs:
        org = e.get("organisation_number")
        tag = f"[{org}]"
        for key in REQUIRED:  # R2 envelope sections
            if key not in e:
                fail(f"R2 {tag} missing key {key}")
        if e.get("state") not in STATES:
            fail(f"R3 {tag} invalid envelope state {e.get('state')}")
        secs = e.get("sections", {})
        if set(secs) != SECTIONS:
            fail(f"R3 {tag} section set {sorted(secs)}")
        for s, v in secs.items():
            if v.get("state") not in STATES or not v.get("reason"):
                fail(f"R3 {tag} section {s} state/reason invalid: {v}")
        evidence = {x["id"]: x for x in e.get("evidence", [])}
        for x in evidence.values():  # R4 evidence completeness
            if not (x.get("source_url") and x.get("retrieved_at") and x.get("content_sha256") and x.get("claim_span")):
                fail(f"R4 {tag} incomplete evidence {x.get('id')}")
            if not re.match(r"^https?://", x.get("source_url") or ""):
                fail(f"R4 {tag} evidence without URL {x.get('id')}")
        claim_ids = set()
        for c in e.get("claims", []):
            claim_ids.add(c["claim_id"])
            counts["claims"] += 1
            counts["stale"] += bool(c.get("stale"))
            if not c.get("evidence_ids") or any(i not in evidence for i in c["evidence_ids"]):
                fail(f"R4 {tag} claim {c['field']} has unresolved evidence")
            if c.get("availability") != "available" or c.get("value") in (None, "", [], {}):
                fail(f"R5 {tag} published claim without value: {c['field']}")
            sec_state = secs.get(c["section"], {}).get("state")
            if sec_state != "available" and not c.get("stale"):
                fail(f"R5 {tag} claim {c['field']} published while section {c['section']} is {sec_state}")
            if c["field"] in FIN:  # R6 financials: period + currency, numeric
                v = c["value"]
                if not c.get("reporting_period") or not v.get("currency") or not isinstance(v.get("amount"), (int, float)):
                    fail(f"R6 {tag} financial claim lacks period/currency/amount: {c}")
            if c["field"] == "job_posting" and c["value"].get("source") == "NAV Arbeidsplassen":  # R7 exact-company jobs
                span = " ".join(evidence[i]["claim_span"] for i in c["evidence_ids"] if i in evidence)
                m = re.search(r"employer\.orgnr = (\d{9})", span)
                if not (m or "exact registered legal name" in span):
                    fail(f"R7 {tag} job without orgnr/exact-name proof")
                counts["jobs"] += 1
            if c["field"] == "official_website":  # R7 exact-company website
                v = c["value"]
                if v.get("identity_score", 0) < 0.9 or not v.get("identity_method"):
                    fail(f"R7 {tag} website published below exact threshold")
                counts["websites"].append((org, e["legal_identity"].get("legal_name"), v["url"], v["identity_method"]))
        for c in e.get("claims", []):  # R14 Builderr audit rules: company-named socials, real posts, single job ads, no landing pages
            v = c["value"]
            if c["field"] == "social_profile" and not social_handle_matches(e["legal_identity"].get("legal_name") or "", v["url"]):
                fail(f"R14 {tag} social handle does not name the company: {v['url']}")
            if c["field"] == "company_news" and not is_news_item(v.get("title", ""), v.get("url", ""), "", require_post_url=False):
                fail(f"R14 {tag} news item is not a dated post: {v.get('url')}")
            if c["field"] == "careers_page":
                fail(f"R14 {tag} careers landing page published as a fact")
            if c["field"] == "job_posting" and v.get("source") == "NAV Arbeidsplassen" and not re.fullmatch(
                    r"https://arbeidsplassen\.nav\.no/stillinger/stilling/[0-9a-f-]{36}", str(v.get("url"))):
                fail(f"R14 {tag} NAV job is not a single-ad URL: {v.get('url')}")
        for p in e.get("summary", {}).get("points", []):  # R8 synthesis cites real claims
            if not p.get("claim_ids") or any(i not in claim_ids for i in p["claim_ids"]):
                fail(f"R8 {tag} summary point cites unknown claim")
        if e.get("state") == "available":
            name = next((c["value"] for c in e["claims"] if c["field"] == "legal_name"), None)
            if not name:
                fail(f"R9 {tag} available envelope without legal name claim")
        blob = json.dumps(e, ensure_ascii=False)
        if "fodselsdato" in blob or "fødselsdato" in blob:  # R10 data minimisation
            fail(f"R10 {tag} birth date field leaked")
        if (e.get("legal_identity") or {}).get("legal_form") == "ENK" and any(c["field"] == "registry_phone" for c in e["claims"]):
            fail(f"R10 {tag} sole-trader phone published")
        for ch in e.get("changes", []):  # R11 refresh changes carry provenance
            counts["changes"] += 1
            if ch.get("old_claim_id") and not ch.get("old_evidence"):
                fail(f"R11 {tag} change without preserved old evidence")
        counts["evidence"] += len(evidence)

    ops = report.get("operations", {})  # R12 budgets
    if ops.get("requests", 0) > a.max_requests:
        fail(f"R12 requests {ops['requests']} > {a.max_requests}")
    if report.get("runtime_s", 0) > a.max_minutes * 60:
        fail(f"R12 runtime {report['runtime_s']}s > {a.max_minutes} min")
    if ops.get("third_party_cost_usd", 0) > 10:
        fail("R12 third-party cost above $10")
    if not report.get("one_envelope_per_input"):
        fail("R12 run report flags missing envelopes")

    # R13 fabrication spot-check: re-fetch the source and compare published values
    spot = 0
    checked_values = 0
    for e in envs:
        if spot >= a.spot_check or e.get("state") != "available":
            continue
        org = e["organisation_number"]
        try:
            entity = fetch_json(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}")
            if entity.get("navn") != e["legal_identity"]["legal_name"]:
                warns.append(f"R13 [{org}] legal name differs from live registry now (may be a real change)")
            fin = [c for c in e["claims"] if c["field"] in FIN]
            if fin:
                records = fetch_json(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}")
                for c in fin:  # exact tuple: field, statement type, period end, currency, value
                    v = c["value"]
                    period_end = (c.get("reporting_period") or "").split("/")[-1]
                    rec = next((r for r in records if (r.get("regnskapstype") or "SELSKAP").lower() == v["statement"]
                                and (r.get("regnskapsperiode") or {}).get("tilDato") == period_end), None)
                    if rec is None:
                        warns.append(f"R13 [{org}] {c['field']} {period_end} {v['statement']}: period no longer in live API (rolled out?)")
                        continue
                    live = rec
                    for key in FIN_PATHS[c["field"]]:
                        live = live.get(key) if isinstance(live, dict) else None
                    if (rec.get("valuta") or "NOK") != v["currency"] or live is None or float(live) != float(v["amount"]):
                        fail(f"R13 [{org}] {c['field']} {v['statement']} {period_end}: published {v['amount']} {v['currency']}, live {live} {rec.get('valuta')}")
                    checked_values += 1
            spot += 1
        except Exception as exc:  # network flake is a warning, not a contract failure
            warns.append(f"R13 [{org}] spot-check skipped: {exc}")

    summary = {
        "input_rows": len(orgs) + len(invalid), "envelopes": len(envs), "claims": counts["claims"], "evidence": counts["evidence"],
        "websites_published": len(counts["websites"]), "jobs_published": counts["jobs"], "stale_claims": counts["stale"],
        "changes": counts["changes"], "requests": ops.get("requests"), "runtime_s": report.get("runtime_s"),
        "cost_usd": ops.get("third_party_cost_usd"), "spot_checked": spot, "financial_values_checked": checked_values,
        "section_available": {s: report["section_states"][s].get("available", 0) for s in report["section_states"]},
        "passed": not fails, "failures": fails[:40], "failure_count": len(fails), "warnings": warns[:20],
        "websites": counts["websites"],
    }
    (a.output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "websites"}, ensure_ascii=False))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
