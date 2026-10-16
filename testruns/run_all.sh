#!/usr/bin/env bash
# 13 verification runs in three lanes. Usage: bash testruns/run_all.sh
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
run() { # id input extra-args...
  id=$1; in=$2; shift 2
  rm -rf testruns/$id
  $PY -W ignore run.py --input "$in" --output testruns/$id/out --state-dir testruns/$id/state --run-id $id "$@" > testruns/$id.log 2>&1
  echo "$id exit=$?" >> testruns/status.txt
}
rm -f testruns/status.txt
echo "commit $(git rev-parse HEAD)" > testruns/status.txt
( run R01 testruns/R01.jsonl
  run R10 testruns/R01.jsonl --previous testruns/R01/out/envelopes.jsonl
  run R02 testruns/R02.txt; run R03 testruns/R03.json ) &
( run R05 testruns/R05.jsonl; run R06 testruns/R06.jsonl; run R07 testruns/R07.jsonl; run R04 testruns/R04.jsonl.gz ) &
( run R11 testruns/R11.jsonl; run R12 testruns/R12.jsonl; run R13 testruns/R13.jsonl
  run R08 testruns/R08.jsonl --max-requests 300; run R09 testruns/R09.jsonl --deadline-minutes 3 ) &
wait; echo ALL_DONE >> testruns/status.txt
