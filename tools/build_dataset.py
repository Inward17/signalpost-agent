#!/usr/bin/env python3
"""Merge verified run outputs into one deduplicated profile dataset (one envelope per organisation number).

    python tools/build_dataset.py --runs testruns/R01 testruns/R02 ... --output profiles/profiles.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path


def tested_commit(suite_dir: Path) -> str:
    """The commit the runs were executed at (recorded by run_all.sh), not whatever HEAD is now."""
    status = suite_dir / "status.txt"
    if status.exists() and status.read_text().startswith("commit "):
        return status.read_text().split()[1]
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", type=Path, required=True, help="run folders containing out/envelopes.jsonl + out/verification.json")
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    profiles: dict[str, dict] = {}
    sources = []
    for run in a.runs:
        verification = json.loads((run / "out" / "verification.json").read_text(encoding="utf-8"))
        if not verification["passed"]:
            raise SystemExit(f"{run} did not pass verification; refusing to include it")
        count = 0
        for line in (run / "out" / "envelopes.jsonl").read_text(encoding="utf-8").splitlines():
            env = json.loads(line)
            if env["state"] != "available":
                continue  # invalid inputs etc. are results, not profiles
            profiles[env["organisation_number"]] = env  # later runs win: freshest snapshot
            count += 1
        sources.append({"run": run.name, "profiles": count, "run_id": json.loads((run / "out" / "run-report.json").read_text())["run"]["run_id"]})
    a.output.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(profiles[o], ensure_ascii=False, separators=(",", ":")) + "\n" for o in sorted(profiles)).encode()
    with gzip.open(a.output, "wb") as fh:
        fh.write(body)
    sections = {}
    for env in profiles.values():
        for s, v in env["sections"].items():
            sections.setdefault(s, {}).setdefault(v["state"], 0)
            sections[s][v["state"]] += 1
    manifest = {
        "profiles": len(profiles),
        "unique_organisation_numbers": len(profiles),
        "claims": sum(len(e["claims"]) for e in profiles.values()),
        "evidence_records": sum(len(e["evidence"]) for e in profiles.values()),
        "agent_commit": tested_commit(a.runs[0].parent),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "source_runs": sources,
        "section_states": sections,
        "note": "Every included run passed tools/verify_run.py. Profiles are evidence for local testing; Builderr scores fresh official batches.",
    }
    a.output.with_name(a.output.name.replace(".jsonl.gz", "-manifest.json")).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("profiles", "claims", "evidence_records", "agent_commit")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
