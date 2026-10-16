#!/usr/bin/env python3
"""Handle erasure/correction requests and retention for the refresh state.

    python tools/purge.py --state-dir state --person "Ola Nordmann"   # remove a person's role claims everywhere
    python tools/purge.py --state-dir state --org 123456789            # remove a company's baseline and history
    python tools/purge.py --state-dir state --older-than-days 365      # drop history entries past retention

The append-only history is append-only for the agent, not for the data controller: this tool is the documented exception.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def scrub(env: dict, person: str) -> tuple[dict, int]:
    """Remove role claims naming the person, their evidence, and changes that mention them."""
    target = person.casefold().strip()
    drop = [c for c in env.get("claims", []) if c.get("field") == "role" and str(c["value"].get("name", "")).casefold() == target]
    ids = {i for c in drop for i in c["evidence_ids"]}
    env["claims"] = [c for c in env.get("claims", []) if c not in drop]
    env["evidence"] = [e for e in env.get("evidence", []) if e["id"] not in ids]
    env["changes"] = [ch for ch in env.get("changes", []) if target not in json.dumps(ch, ensure_ascii=False).casefold()]
    if "summary" in env:
        env["summary"]["points"] = [p for p in env["summary"].get("points", []) if target not in p["text"].casefold()]
    return env, len(drop)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", type=Path, default=Path("state"))
    ap.add_argument("--person")
    ap.add_argument("--org")
    ap.add_argument("--older-than-days", type=int)
    a = ap.parse_args()
    if not (a.person or a.org or a.older_than_days):
        ap.error("give --person, --org or --older-than-days")
    removed = 0
    if a.org:
        for f in (a.state_dir / f"{a.org}.json", a.state_dir / "history" / f"{a.org}.jsonl"):
            if f.exists():
                f.unlink()
                removed += 1
    if a.person:
        a.state_dir.mkdir(parents=True, exist_ok=True)
        with (a.state_dir / "suppressed_persons.txt").open("a", encoding="utf-8") as fh:  # future runs skip this person
            fh.write(a.person.strip() + "\n")
        for f in a.state_dir.glob("*.json"):
            env, n = scrub(json.loads(f.read_text(encoding="utf-8")), a.person)
            if n:
                f.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
                removed += n
        for f in (a.state_dir / "history").glob("*.jsonl"):
            lines = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            target = a.person.casefold()
            kept = []
            for entry in lines:
                before = len(entry["evidence"]) + len(entry["changes"])
                entry["evidence"] = [e for e in entry["evidence"] if target not in e.get("claim_span", "").casefold()]
                entry["changes"] = [c for c in entry["changes"] if target not in json.dumps(c, ensure_ascii=False).casefold()]
                removed += before - len(entry["evidence"]) - len(entry["changes"])
                kept.append(entry)
            f.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept), encoding="utf-8")
    if a.older_than_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=a.older_than_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for f in (a.state_dir / "history").glob("*.jsonl"):
            lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            kept = [l for l in lines if json.loads(l).get("at", "") >= cutoff]
            removed += len(lines) - len(kept)
            f.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    print(f"removed {removed} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
