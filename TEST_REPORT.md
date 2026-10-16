# Verification report: 10 test runs

Date: 16 October 2026 · Code: commit `ba9e6e6` (the runs) plus one follow-up refinement, validated separately (see "After the runs") ·
Reproduce: `bash testruns/run_all.sh && python testruns/verify_all.py` · Machine-readable results: `testruns/RESULTS.json`

**Result: 10/10 runs pass all contract checks.** Zero wrong-company publications in the final code; three found and fixed during testing.

## How each run is checked

`tools/verify_run.py` checks every envelope of a run against the hackathon rules:

| ID | Rule (source) | Check |
|---|---|---|
| R1 | One result per company, none missing (challenge page, contract) | envelope count = input rows, no duplicates, same org set; `report.html` present |
| R2 | Envelope contains legal identity, claims, evidence, states, snapshots, refresh metadata, errors (contract) | all required keys in every envelope, including failed ones |
| R3 | Distinct `available / not_available / blocked / not_applicable / ambiguous / failed` (contract) | envelope and all 9 sections have a valid state and a reason |
| R4 | Every claim has source, retrieval time and evidence (contract, source policy) | every claim's evidence IDs resolve; evidence has URL, timestamp, SHA-256, span |
| R5 | Honest availability states | no published claim in a section that is not `available` (stale carry excepted) |
| R6 | Reporting period where relevant; never zero for missing (contract) | every financial claim has a period, currency and numeric amount |
| R7 | Exact company match (qualification) | NAV jobs carry `employer.orgnr` proof; websites ≥ 0.9 with a stated method |
| R8 | Synthesis with sources for conclusions (scoring) | every summary sentence cites existing claim IDs |
| R9 | Legal identity anchored | every `available` envelope has a legal-name claim |
| R10 | Safe source handling / personal data (contract) | no birth dates; no sole-trader phone numbers |
| R11 | Refresh keeps prior evidence (contract) | every changed claim carries its old evidence |
| R12 | 45 min, 2,000 requests, $10 (Unstop limits) | measured requests, runtime and cost within limits |
| R13 | No fabricated financial values (qualification) | 5 companies per run re-fetched live from Regnskapsregisteret; every published amount must appear in the filing |

`testruns/verify_all.py` adds run-specific expectations (marked * below).

## Results

| Run | Purpose | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|---|
| R01 | random 100, JSONL universe rows | 100 | 4,376 | 9 | 0 | 781 | 474 s | PASS |
| R02 | random 100, plain-text input | 100 | 4,571 | 9 | 1 | 823 | 443 s | PASS |
| R03 | random 100, JSON list input | 100 | 4,417 | 8 | 0 | 826 | 491 s | PASS |
| R04 | random 100, gzipped JSONL | 100 | 4,551 | 13 | 0 | 775 | 438 s | PASS |
| R05 | random 100 + 2 duplicate rows + 2 invalid numbers | 102* | 4,511 | 13 | 0 | 821 | 447 s | PASS |
| R06 | 100 companies with ≥ 5 employees | 100 | 5,512 | 31 | 0 | 860 | 507 s | PASS |
| R07 | DIPS, Equinor, 2 hiring companies + 96 with registry website | 100 | 5,541 | 44 | 2 | 943 | 470 s | PASS |
| R08 | budget stress `--max-requests 300` | 100 | 4,189 | 0 | 0 | 300* | 40 s | PASS |
| R09 | deadline stress `--deadline-minutes 3` | 100 | 4,306 | 0 | 0 | 539 | 183 s* | PASS |
| R10 | refresh of R01 with `--previous` | 100 | 4,376 | 8 (+1 stale) | 0 | 784 | 471 s | PASS, 0 false changes* |

\* R05: duplicates collapse to one envelope, and each invalid number gets a contract-complete `failed` envelope (100 + 2).
R08: the cap holds at exactly 300 requests; all 100 envelopes are still written, and 300 sections are marked `blocked` with "budget" as the reason.
R09: the run stops within the deadline; 200 sections are marked `blocked`, and every envelope is written.
R10: no change whose old and new values are identical. One site answered HTTP 429; its 4 facts were kept as `stale` instead of being deleted.

Fabrication spot-check (R13): 50 companies re-fetched across the runs. Every published financial amount matched the live filing.

Coverage per section (number of companies with `available`), random runs R01–R04: identity 100, financials 99–100, leadership 99–100,
locations 99–100, public activity 100, website 8–13, social profiles 3–7, contact 28–39, jobs 0–1.

## Identity audit (manual, all runs)

All **127 unique websites** published across the 10 runs were listed and reviewed by proof type:

- 61: the organisation number appears on the company's own page
- 45: exact legal name (legal-form suffix in capitals) plus the registry's own phone or address, on a name-matching or officially declared domain
- 21: a site the company declared to Brønnøysund itself, with its legal or brand name on the page

None rests on a name alone.

## Defects found by these runs, and fixes

| # | Defect | Severity | Found in | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | **SHARK AS** (Sandefjord, freight) published with `shark.no`, which belongs to a different "Shark AS" (Kolbotn, property) | wrong company: disqualifying | R02 audit | name-only rule removed; exact name now also needs an org number or registry contact | `test_same_name_other_company_on_matching_domain_is_not_exact` |
| 2 | HTTP 429 on a verified site was read as "site gone", so the refresh reported `removed_official_website` | false change | R10 | 429/403/5xx/timeout on a declared or previously verified site → `blocked`/`failed`, and the last site facts are carried as `stale` | `test_rate_limited_site_keeps_site_facts_stale_not_removed` |
| 3 | Invalid-input envelopes lacked `legal_identity` and `summary` | contract | R05 | one contract-complete fallback builder for all failure paths | R05 rerun |
| 4 | `careers_page` published under `jobs` while jobs said `not_available` | inconsistent state | first smoke run | moved to `website` | verifier R5 |
| 5 | Registered address published under `locations` while it said `blocked` (budget stopped the subunit lookup) | inconsistent state | R08 | address marks locations available; later gaps are appended to the reason ("partial – blocked: …") | R08 rerun |
| 6 | Site pages ("Hjem", "Kontakt") with Article markup published as news | junk facts | R10 | `is_news_item` filter (title length, nav words, slug) | `test_site_pages_are_not_news` |
| 7 | Employer-name normalisation dropped letters like ö and é | missed matches | jobs investigation | unicode-aware normalisation | — |

Earlier, before these runs: "ASTRA HOLDING AS" matched a British site through the English word "as", and "VESTGÅRD INVEST AS" matched a related company's site through
a shared phone number. Both were fixed earlier and have regression tests.

## After the runs

One refinement came after the 10 runs: a timeout on a *guessed* domain no longer marks the website section `failed`. Only declared or previously verified
sites count as "could not check". It was validated on the affected companies against R01's baseline: guessed `alfas.com` → `not_available`;
registry-declared `brathwait.com` (timed out) → `failed`; previously verified Gjøvik Tannlegekontor → `available`, 0 changes.
18/18 offline tests pass.

## What these runs do not show

- **Jobs recall is low (0–2 per 100).** This was investigated. The NAV feed held 9,147 active ads from 5,593 employer names, and only 1,256 of those names carry the legal
  "AS" suffix (the rest are brands, departments or public bodies). Widening name matching found just one extra candidate, which the orgnr check would reject anyway. Most random
  companies simply have no NAV ad in a 45-day window. The matcher works: both known hiring companies in R07 were matched by orgnr.
- **Website recall is 8–13 % on random batches** (31–44 % on employer- or website-heavy batches). That's the cost of publishing only proven matches; 30–40 candidates per run are
  withheld as `ambiguous`.
- A 1,000-company batch was not run. R08 shows the behaviour under a binding budget: all envelopes are written, and the baseline is complete.
