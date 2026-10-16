#!/usr/bin/env python3
"""Signalpost agent: one command, one terminal envelope per input organisation number.

    python run.py --input companies.jsonl --output out
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable

from signalpost import __version__
from signalpost.dossier import SECTIONS, Dossier
from signalpost.envelope import build
from signalpost.http import BudgetExhausted, Client, utc_now
from signalpost.jobs import JobIndex, collect_jobs
from signalpost.registry import fetch_accounts, fetch_entity, fetch_registry_updates, fetch_roles, fetch_subunits
from signalpost.report import write_html
from signalpost.website import research_website


def read_inputs(path: Path) -> tuple[list[str], dict[str, dict], list[dict]]:
    """Accepts JSON list/object, JSONL rows (organisation_number + optional snapshot fields) or plain text lines."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as fh:
        text = fh.read()
    stripped = text.strip()
    if stripped.startswith("["):
        rows = json.loads(stripped)
    elif stripped.startswith("{") and "\n" not in stripped:
        body = json.loads(stripped)
        rows = body.get("organisation_numbers") or body.get("companies") or [body]
    elif stripped.startswith("{"):
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        rows = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    orgs, seeds, invalid = [], {}, []
    for row in rows:
        raw = row.get("organisation_number") or row.get("orgnr") or row.get("organisasjonsnummer") if isinstance(row, dict) else row
        org = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if len(org) != 9:
            invalid.append({"input": raw, "organisation_number": org or str(raw)})
            continue
        if org in seeds:
            continue  # duplicate input rows collapse to one envelope
        orgs.append(org)
        seeds[org] = row if isinstance(row, dict) else {}
    return orgs, seeds, invalid


def load_previous(state_dir: Path, previous: Path | None) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if previous and previous.exists():
        for line in previous.read_text(encoding="utf-8").splitlines():
            if line.strip():
                env = json.loads(line)
                found[env["organisation_number"]] = env
    elif state_dir.exists():
        for file in state_dir.glob("*.json"):
            try:
                env = json.loads(file.read_text(encoding="utf-8"))
                found[env["organisation_number"]] = env
            except (json.JSONDecodeError, KeyError):
                continue
    return found


def failed_envelope(org: str, run_meta: dict, stage: str, message: str, reason: str, requests: int = 0) -> dict[str, Any]:
    """Contract-complete envelope for an input that could not be researched."""
    return {"schema_version": "signalpost-envelope/1.0", "organisation_number": org, "state": "failed", "run": run_meta,
            "legal_identity": {"organisation_number": org, "legal_name": None},
            "public_brand": {"brand_names": [], "official_website": None, "social_profiles": []},
            "sections": {s: {"state": "failed", "reason": reason} for s in SECTIONS},
            "summary": {"headline": f"Organisation {org}: not researched ({reason}).", "points": [], "changes": [],
                        "unknowns": [{"section": s, "state": "failed", "reason": reason} for s in SECTIONS], "method": "fallback"},
            "claims": [], "evidence": [], "source_snapshots": [], "refresh": {}, "changes": [],
            "errors": [{"stage": stage, "message": message}], "operations": {"requests": requests, "third_party_cost_usd": 0.0}}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path, help="JSON / JSONL / text list of organisation numbers")
    ap.add_argument("--output", default=Path("out"), type=Path, help="output directory")
    ap.add_argument("--state-dir", default=Path("state"), type=Path, help="previous snapshots for refresh diffs")
    ap.add_argument("--previous", type=Path, help="previous envelopes.jsonl (overrides --state-dir as refresh baseline)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max-requests", type=int, default=2000)
    ap.add_argument("--deadline-minutes", type=float, default=42.0, help="hard stop; output is always written")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--jobs-window-days", type=int, default=45)
    ap.add_argument("--no-domain-guessing", action="store_true")
    args = ap.parse_args(argv)

    started_at, t0 = utc_now(), time.monotonic()
    run_id = args.run_id or "run-" + started_at.replace(":", "").replace("-", "")
    orgs, seeds, invalid = read_inputs(args.input)
    client = Client(max_requests=args.max_requests, deadline_s=args.deadline_minutes * 60)
    margin = 90.0  # seconds reserved for envelope building and writing
    dossiers = {org: Dossier(org, seeds[org]) for org in orgs}
    previous = load_previous(args.state_dir, args.previous)
    for org, prev in previous.items():
        if org in dossiers:
            site = next((c["value"] for c in prev.get("claims", []) if c.get("field") == "official_website"), None)
            dossiers[org].previous_site_domain = (site or {}).get("domain")
    print(f"[signalpost] {len(orgs)} companies, {len(invalid)} invalid inputs, {len(previous)} previous snapshots", file=sys.stderr)

    def phase(name: str, section: str, fn: Callable[[Client, Dossier], None], pick: Callable[[Dossier], bool] = lambda d: True) -> None:
        todo = [d for d in dossiers.values() if pick(d)]

        def one(d: Dossier) -> None:
            if client.time_left() < margin or client.remaining() <= 0:
                d.section(section, "blocked", "run time/request budget reached before this source was queried")
                return
            client.local.dossier = d
            try:
                fn(client, d)
            except BudgetExhausted as exc:
                d.section(section, "blocked", f"{exc} before this source completed")
            except Exception as exc:  # per-company exception boundary: the batch always continues
                d.section(section, "failed", f"{type(exc).__name__}: {str(exc)[:200]}")
                d.error(name, traceback.format_exc(limit=3))
            finally:
                client.local.dossier = None

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(one, d) for d in todo]
            done, pending = wait(futures, timeout=max(1.0, client.time_left() - margin))
            for f in pending:
                f.cancel()
        print(f"[signalpost] phase {name}: {len(todo)} companies, {client.requests} requests used, {time.monotonic() - t0:.0f}s", file=sys.stderr)

    identified = lambda d: bool(d.entity.get("navn"))  # noqa: E731
    phase("identity", "identity", fetch_entity)
    phase("accounts", "financials", fetch_accounts, identified)
    phase("roles", "leadership", fetch_roles, identified)
    phase("subunits", "locations", fetch_subunits, identified)
    phase("registry_updates", "public_activity", fetch_registry_updates, identified)

    jobs = JobIndex()
    if client.time_left() > margin:
        max_pages = max(5, min(160, client.remaining() // 6))
        try:
            jobs.build(client, args.jobs_window_days, max_pages)
        except Exception as exc:
            jobs.error = f"{type(exc).__name__}: {exc}"
    print(f"[signalpost] NAV feed: {jobs.pages} pages, {len(jobs.entries)} entries, error={jobs.error}", file=sys.stderr)
    phase("jobs", "jobs", lambda c, d: collect_jobs(c, d, jobs), identified)
    phase("website", "website", lambda c, d: research_website(c, d, allow_guessing=not args.no_domain_guessing), identified)

    completed_at = utc_now()
    for d in dossiers.values():
        d.frozen = True
    run_meta = {"run_id": run_id, "agent_version": __version__, "started_at": started_at, "completed_at": completed_at, "terminal_status": "completed"}
    envelopes: list[dict[str, Any]] = []
    for org in orgs:
        d = dossiers[org]
        try:
            envelopes.append(build(d, run=run_meta, previous=previous.get(org), now=completed_at))
        except Exception as exc:  # still exactly one terminal envelope
            envelopes.append(failed_envelope(org, run_meta, "build", f"{type(exc).__name__}: {exc}", "envelope build error", d.requests))
    for bad in invalid:
        envelopes.append(failed_envelope(bad["organisation_number"], run_meta, "input", f"invalid organisation number: {bad['input']!r}",
                                         "invalid organisation number input"))

    out = args.output
    atomic_write(out / "envelopes.jsonl", "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in envelopes))
    for env in envelopes:
        if env["state"] == "failed" and not env["claims"]:
            continue  # never overwrite a good baseline with a broken run
        atomic_write(args.state_dir / f"{env['organisation_number']}.json", json.dumps(env, ensure_ascii=False))
        hist = args.state_dir / "history" / f"{env['organisation_number']}.jsonl"
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8") as fh:  # append-only evidence + change log
            fh.write(json.dumps({"run_id": run_id, "at": completed_at, "evidence": env["evidence"], "changes": env["changes"]}, ensure_ascii=False) + "\n")

    section_states = {s: {} for s in SECTIONS}
    for env in envelopes:
        for s, v in env["sections"].items():
            section_states[s][v["state"]] = section_states[s].get(v["state"], 0) + 1
    report = {
        "run": run_meta,
        "input_rows": len(orgs) + len(invalid),
        "envelopes": len(envelopes),
        "one_envelope_per_input": len({e["organisation_number"] for e in envelopes}) == len(envelopes) == len(orgs) + len(invalid),
        "envelope_states": {k: sum(1 for e in envelopes if e["state"] == k) for k in {e["state"] for e in envelopes}},
        "section_states": section_states,
        "claims_total": sum(len(e["claims"]) for e in envelopes),
        "changes_total": sum(len(e["changes"]) for e in envelopes),
        "runtime_s": round(time.monotonic() - t0, 1),
        "operations": {**client.stats(), "third_party_cost_usd": round(client.third_party_cost_usd, 4),
                       "nav_feed_pages": jobs.pages, "nav_feed_entries": len(jobs.entries)},
        "per_company_requests": sorted(e["operations"]["requests"] for e in envelopes)[len(envelopes) // 2] if envelopes else 0,
    }
    atomic_write(out / "run-report.json", json.dumps(report, ensure_ascii=False, indent=2))
    write_html(out / "report.html", envelopes, report)
    print(json.dumps({k: report[k] for k in ("envelopes", "one_envelope_per_input", "envelope_states", "claims_total", "runtime_s")} |
                     {"requests": client.requests}, ensure_ascii=False))
    return 0 if report["one_envelope_per_input"] else 1


if __name__ == "__main__":
    sys.exit(main())
