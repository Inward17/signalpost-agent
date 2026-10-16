#!/usr/bin/env python3
"""Verify the 10 test runs (tools/verify_run.py per run + run-specific expectations) and write testruns/RESULTS.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "testruns"
RUNS = {  # id: (input, purpose, verifier args)
    "R01": ("R01.jsonl", "random 100, JSONL universe rows", []),
    "R02": ("R02.txt", "random 100, plain-text input", []),
    "R03": ("R03.json", "random 100, JSON list input", []),
    "R04": ("R04.jsonl.gz", "random 100, gzipped JSONL", []),
    "R05": ("R05.jsonl", "random 100 + 2 duplicate rows + 2 invalid numbers", []),
    "R06": ("R06.jsonl", "100 companies with >=5 employees (website/jobs stress)", []),
    "R07": ("R07.jsonl", "4 known companies + 96 with registry website", []),
    "R08": ("R08.jsonl", "budget stress: --max-requests 300", ["--max-requests", "300"]),
    "R09": ("R09.jsonl", "deadline stress: --deadline-minutes 3", ["--max-minutes", "3"]),
    "R10": ("R01.jsonl", "refresh of R01 with --previous (idempotency / change detection)", []),
    "R11": ("R11.jsonl", "random 100, companies not used in any earlier run", []),
    "R12": ("R12.jsonl", "random 100, companies not used in any earlier run", []),
    "R13": ("R13.jsonl", "random 100, companies not used in any earlier run", []),
}


def envs(run: str) -> list[dict]:
    return [json.loads(l) for l in (T / run / "out" / "envelopes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    results = {}
    for run, (inp, purpose, extra) in RUNS.items():
        out = T / run / "out"
        if not (out / "envelopes.jsonl").exists():
            results[run] = {"purpose": purpose, "passed": False, "failures": ["no output produced"]}
            continue
        proc = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools" / "verify_run.py"), "--input", str(T / inp),
                               "--output", str(out), "--spot-check", "5", *extra], capture_output=True, text=True, encoding="utf-8")
        v = json.loads((out / "verification.json").read_text(encoding="utf-8"))
        extra_fail = []
        e = envs(run)
        if run == "R05":
            failed_inputs = [x for x in e if x["state"] == "failed" and x["errors"] and x["errors"][0]["stage"] == "input"]
            if len(e) != 102 or len(failed_inputs) != 2:
                extra_fail.append(f"expected 100 unique + 2 invalid envelopes, got {len(e)} / {len(failed_inputs)} invalid")
        if run == "R08":
            blocked = sum(1 for x in e for s in x["sections"].values() if s["state"] == "blocked" and "budget" in s["reason"])
            v["budget_blocked_sections"] = blocked
            if blocked == 0:
                extra_fail.append("budget cap of 300 never triggered blocked states")
        if run == "R09":
            blocked = sum(1 for x in e for s in x["sections"].values() if s["state"] == "blocked")
            v["deadline_blocked_sections"] = blocked
        if run == "R10":
            prev = {x["organisation_number"]: x for x in envs("R01")}
            real, false = [], []
            for x in e:
                for ch in x["changes"]:
                    (real if ch["old_value"] != ch["new_value"] else false).append(f"{x['organisation_number']} {ch['change_type']}")
            if false:
                extra_fail.append(f"false changes (value identical): {false[:5]}")
            if any(not x["refresh"].get("previous_run_id") for x in e if x["organisation_number"] in prev):
                extra_fail.append("refresh did not pick up the previous snapshot")
            v["real_changes"] = real[:30]
        v["purpose"] = purpose
        v["failures"] = v["failures"] + extra_fail
        v["passed"] = v["passed"] and not extra_fail
        results[run] = v
    (T / "RESULTS.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for run, v in results.items():
        print(f"{run} {'PASS' if v['passed'] else 'FAIL'} env={v.get('envelopes')} claims={v.get('claims')} web={v.get('websites_published')} "
              f"jobs={v.get('jobs_published')} req={v.get('requests')} t={v.get('runtime_s')}s changes={v.get('changes')} | {v['purpose']}")
        for f in v["failures"][:8]:
            print("    -", f)
    return 0 if all(v["passed"] for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
