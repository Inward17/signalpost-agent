# Signalpost agent

Give it Norwegian organisation numbers; it returns one evidence-backed company profile per number — legal identity,
filed accounts, leadership, workplaces, verified website, company-linked social profiles, contact points, open jobs and dated
public activity — with a source, retrieval time, content hash and reporting period on every claim, honest availability states,
and a refresh diff against the previous run.

Registry-anchored and deterministic: no LLM, no paid API, $0 third-party cost.

## Install and run (one command)

Python 3.10+ (tested on 3.13).

Linux / macOS:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py --input companies.jsonl --output out
```

Windows (PowerShell or cmd):

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py --input companies.jsonl --output out
```

`--input` accepts a JSONL file (one object per line with `organisation_number`, e.g. rows of the public universe file), a JSON list,
or a plain text file with one organisation number per line. Gzipped input is fine.

Outputs:

| File | Content |
|---|---|
| `out/envelopes.jsonl` | exactly one terminal envelope per input organisation number (invalid inputs get a `failed` envelope) |
| `out/run-report.json` | counts per section state, claims, changes, requests, bytes, p50/p95 latency, runtime, third-party cost |
| `out/report.html` | self-contained viewer: search/filter/compare companies, open every claim's evidence and source link (desktop + mobile) |
| `state/<org>.json`, `state/history/<org>.jsonl` | refresh baseline and append-only evidence/change log |

Useful flags: `--state-dir` (refresh baseline, default `state/`), `--previous envelopes.jsonl` (explicit previous snapshot),
`--max-requests 2000`, `--deadline-minutes 42`, `--max-cost-usd 10`, `--workers 16`, `--jobs-window-days 45`, `--no-domain-guessing`, `--run-id`.

Offline tests: `python tests/test_agent.py` (38 tests; also runs under pytest).

## Envelope

```jsonc
{
  "schema_version": "signalpost-envelope/1.0",
  "organisation_number": "810034882",
  "state": "available",                       // envelope-level terminal state
  "run": {"run_id", "agent_version", "started_at", "completed_at", "terminal_status": "completed"},
  "legal_identity": {"legal_name", "legal_form", "status", "registered_address", "municipality", "industry", "registry_url"},
  "public_brand": {"brand_names", "official_website", "social_profiles", "relationship": "exact_entity"},
  "sections": {                               // one availability state per information family
    "identity" | "financials" | "leadership" | "locations" | "website" | "social_profiles" | "contact" | "jobs" | "public_activity":
      {"state": "available|not_available|blocked|not_applicable|ambiguous|failed", "reason": "...", "candidates_checked": [...]}
  },
  "summary": {"headline", "points": [{"text", "claim_ids"}], "changes", "unknowns", "method"},
  "claims": [{"claim_id", "claim_key", "field", "section", "value", "availability", "confidence", "evidence_ids",
              "reporting_period", "effective_date", "first_observed_at", "last_observed_at", "extraction_method", "stale?"}],
  "evidence": [{"id", "source_url", "requested_url", "source_class", "retrieved_at", "http_status", "content_sha256", "claim_span", "extraction_method"}],
  "source_snapshots": [{"url", "content_sha256", "retrieved_at", "source_class", "http_status"}],
  "refresh": {"is_first_run", "previous_run_id", "previous_completed_at", "unchanged_claims", "changed_or_added", "removed", "retained_stale_claims"},
  "changes": [{"change_id", "change_type", "field", "material", "old_value", "new_value", "old_evidence", "new_evidence_ids", "detected_at"}],
  "errors": [{"stage", "message", "at"}],
  "operations": {"requests", "third_party_cost_usd"}
}
```

States: `available` = found with evidence · `not_available` = looked, nothing there · `blocked` = source refused (robots, 403/429, or
run budget reached before the source was queried) · `not_applicable` = does not apply (e.g. filing-exempt legal form) · `ambiguous` =
candidate found but exact identity unproven, so nothing published · `failed` = processing error for this company. Missing values are
never zero-filled; a financial field absent from the filing is simply absent.

## How it works

Breadth-first phases so every company gets the high-value official baseline before optional enrichment spends budget:

1. **Identity** — live Brønnøysund entity by exact organisation number (falls back to snapshot fields in the input row if the API fails).
2. **Accounts** — all filed periods from Regnskapsregisteret, company and group statements kept separate, each value with its period and currency.
3. **Roles** and **registered workplaces**.
4. **Official change log** — dated, field-level registry changes (address, name, website, employees, filings…).
5. **Jobs** — one walk of the NAV vacancy feed (changes in the last 45 days, ~100 pages shared by the whole batch), indexed by employer
   name; each candidate ad is re-fetched and published only if `employer.orgnr` is the company or one of its subunits.
6. **Website** — candidates from the registry, NAV ads and name-derived domains (DNS-checked first), each passed through the identity
   gate in [SOURCES_AND_SECURITY.md](SOURCES_AND_SECURITY.md). Only an exact match is crawled for description, brand, social profiles,
   contact points, dated news (JSON-LD articles, `<time>` on the news page), careers page and JobPosting markup.
7. **Envelope** — claims get stable IDs (`hash(org, claim key, value)`), so re-running an unchanged snapshot produces zero changes;
   changed values emit typed changes (`new_job`, `closed_job`, `new_role`, `new_location`, `new_filing`, `changed_description`, `changed_<field>`)
   with the previous evidence attached; a source that fails on refresh keeps its last value marked `stale` instead of being deleted.
   The summary is a deterministic template where every sentence cites the claim IDs it is built from.

## Models, APIs and costs

| Item | Detail | Cost |
|---|---|---|
| LLM | none | $0 |
| Brønnøysund APIs | open data, NLOD 2.0, no key | $0 |
| NAV job feed | public token, fetched at run time | $0 |
| Company websites | direct HTTP | $0 |
| Brave Search API | optional; only used if `BRAVE_API_KEY` is set (default off) | ~$0.005/company if enabled |

**Expected cost per official run: $0.00** (default configuration). Request use: ~6 registry requests per company + ~100 shared NAV feed
pages + ~0–8 website requests per company. Measured: 100 companies use 775–943 of the 2,000-request budget and take 7–8.5 minutes; the budget/deadline caps are enforced so larger batches degrade by marking optional sources `blocked`, never by dropping rows.

## Smoke test, verification and 1,000 profiles

- `smoke/`: 100-company smoke batch, envelopes, run report, HTML viewer, `verification.json`. 100/100 envelopes, 4,376 claims,
  824 requests, 474 s, $0. `smoke/out-refresh/` is a second run against the first run's output: 0 false changes.
- `profiles/profiles.jsonl.gz`: **1,000 unique company profiles** (46,902 claims, each with evidence) merged from verified runs; see the manifest.
- 13 verification runs (input formats, duplicates and invalid numbers, employer-heavy batches, 300 never-seen companies, budget and deadline
  stress, refresh) all pass the 13 contract rule groups in `tools/verify_run.py` at commit `e123b93`. See [TEST_REPORT.md](TEST_REPORT.md).
- Privacy operations: `python tools/purge.py --person "Name" | --org <number> | --older-than-days 365` (see SOURCES_AND_SECURITY.md).

## Limitations

- Website discovery without a search API relies on the registry website, NAV employer data and name-derived domains; companies whose
  brand differs from the legal name are often reported `not_available` (or `ambiguous`) rather than guessed.
- Jobs cover ads published on NAV Arbeidsplassen (plus JobPosting markup on verified sites); ads only on other boards are not seen.
- News extraction is structural (JSON-LD / `<time>` elements); sites without dated markup yield no news items.
- Annual-account PDFs are not parsed; financials come from the normalised Regnskapsregisteret API.
