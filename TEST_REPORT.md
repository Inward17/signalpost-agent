# Verification report

**Code tested: commit `f0b3f58cac90da449f41df3ff1683e3787d0a124`** (recorded by the harness in `testruns/status.txt`; every run below
executed at exactly this commit). Commits after it change documentation and data artifacts only, not agent code.

Reproduce: `bash testruns/run_all.sh && python testruns/verify_all.py` · Machine-readable: `testruns/RESULTS.json` · Offline tests: `python tests/test_agent.py` (26 pass)

**Result: 13/13 runs pass every contract check. Zero wrong-company publications in the tested code; four were found and fixed during testing.**

## How each run is checked

`tools/verify_run.py` checks every envelope of a run against the hackathon rules:

| ID | Rule (source) | Check |
|---|---|---|
| R1 | One result per company, none missing (challenge page, contract) | envelope count = input rows, no duplicates, same org set; `report.html` present |
| R2 | Envelope contains legal identity, claims, evidence, states, snapshots, refresh metadata, errors (contract) | all required keys in every envelope, including failed ones |
| R3 | Distinct `available / not_available / blocked / not_applicable / ambiguous / failed` (contract) | envelope and all 9 sections have a valid state and a reason |
| R4 | Every claim has source, retrieval time and evidence (contract, source policy) | evidence IDs resolve; evidence has URL, timestamp, SHA-256, span |
| R5 | Honest availability states | no published claim in a section that is not `available` (stale carry excepted) |
| R6 | Reporting period where relevant; never zero for missing (contract) | every financial claim has a period, currency and numeric amount |
| R7 | Exact company match (qualification) | NAV jobs carry `employer.orgnr` proof; websites ≥ 0.9 with a stated method |
| R8 | Synthesis with sources (scoring) | every summary sentence cites existing claim IDs |
| R9 | Legal identity anchored | every `available` envelope has a legal-name claim |
| R10 | Personal data minimised (contract) | no birth dates; no sole-trader phone numbers |
| R11 | Refresh keeps prior evidence (contract) | every changed claim carries its old evidence |
| R12 | 45 min, 2,000 requests, $10 (Unstop limits) | measured requests, runtime and cost within the run's limits |
| R13 | No fabricated financial values (qualification) | 5 companies per run re-fetched live from Regnskapsregisteret; every published amount must appear in the filing |

`testruns/verify_all.py` adds run-specific expectations (marked * below).

## Results at `f0b3f58`

| Run | Purpose | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|---|
| R01 | random 100, JSONL universe rows | 100 | 4,376 | 9 | 0 | 780 | 450 s | PASS |
| R02 | random 100, plain-text input | 100 | 4,571 | 9 | 1 | 821 | 410 s | PASS |
| R03 | random 100, JSON list input | 100 | 4,417 | 8 | 0 | 822 | 448 s | PASS |
| R04 | random 100, gzipped JSONL | 100 | 4,548 | 12 | 0 | 775 | 407 s | PASS |
| R05 | random 100 + 2 duplicate rows + 2 invalid numbers | 102* | 4,511 | 13 | 0 | 819 | 390 s | PASS |
| R06 | 100 companies with ≥ 5 employees | 100 | 5,509 | 30 | 0 | 864 | 498 s | PASS |
| R07 | DIPS, Equinor, 2 hiring companies + 96 with registry website | 100 | 5,541 | 44 | 2 | 942 | 417 s | PASS |
| R08 | budget stress `--max-requests 300` | 100 | 4,189 | 0 | 0 | 300* | 39 s | PASS |
| R09 | deadline stress `--deadline-minutes 3` | 100 | 4,306 | 0 | 0 | 524 | **135 s*** | PASS |
| R10 | refresh of R01 with `--previous` | 100 | 4,376 | 9 | 0 | 781 | 477 s | PASS, 0 false changes* |
| R11 | random 100, companies never used before | 100 | 4,457 | 6 | 1 | 831 | 415 s | PASS |
| R12 | random 100, companies never used before | 100 | 4,597 | 10 | 0 | 839 | 465 s | PASS |
| R13 | random 100, companies never used before | 100 | 4,402 | 7 | 0 | 767 | 435 s | PASS |

\* R05: duplicates collapse to one envelope, and each invalid number gets a contract-complete `failed` envelope (100 + 2).
R08: the cap holds at exactly 300 requests; all 100 envelopes are still written, and 300 sections are marked `blocked` with "budget" as the reason.
R09: the verifier now checks the strict limit (≤ 180 s). The run finishes in 135 s because the HTTP client refuses new requests inside the
final reserve; the earlier version took 183 s because the job-feed walk used up the margin.
R10: no change whose old and new values are identical.

**Financial fabrication spot-check (R13):** 65 companies re-fetched live across the 13 runs. Every published amount matched the filing.

**Coverage per section** (companies with `available`), 7 random batches R01–R04, R11–R13: identity 100, financials 99–100, leadership 99–100,
locations 98–100, public activity 100, website 6–12, social profiles 3–7, contact 28–39, jobs 0–1.

**Source yield** (smoke run R01, `source_yield` in each run report): Brønnøysund 501 requests → 4,337 claims (8.7 claims per request) for 100 companies;
company websites 184 requests → 39 claims (0.2 per request) for 9 companies; NAV feed 95 requests → 0 claims in this batch.

## Identity audit (manual)

All **148 unique websites** published across the 13 runs were listed and reviewed by proof type:

- 66: the organisation number appears in visible text on the company's page
- 6: the organisation number appears only in page markup, accepted solely because the domain matches the company name and the page lists no other companies
- 52: exact legal name (legal-form suffix in capitals) plus the registry's own phone or address, on a name-matching or officially declared domain
- 24: a site the company declared to Brønnøysund itself, with its legal or brand name on the page

None rests on a name alone or on a chain page.

## 1,000-profile dataset

`profiles/profiles.jsonl.gz` (5.0 MB) holds **1,000 unique companies**, one envelope each, with 46,929 claims and 46,929 evidence records.
It is merged from R01–R07, R10 and R11–R13. All of these runs passed verification at `f0b3f58`; the builder refuses any run that didn't.
Constrained runs (R08, R09) are excluded. `profiles/profiles-manifest.json` records the commit, content SHA-256, source runs and section counts.
Builderr scores fresh official batches; this dataset satisfies the Unstop listing's "at least 1,000 company profiles" item.

## Defects found by testing, and fixes

| # | Defect | Severity | Found in | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | ASTRA HOLDING AS matched a British site through the English word "as" | wrong company | first smoke audit | legal-form suffix must appear in capitals | `test_english_as_does_not_satisfy_legal_suffix` |
| 2 | VESTGÅRD INVEST AS matched a related company's site through a shared phone | wrong company | first smoke audit | declared sites need the entity's own name | `test_shared_phone_on_registry_site_is_not_exact` |
| 3 | SHARK AS (Sandefjord) matched `shark.no`, a different "Shark AS" (Kolbotn) | wrong company | 10-run audit | name-only rule removed | `test_same_name_other_company_on_matching_domain_is_not_exact` |
| 4 | NORLANDIA RATVIKA BARNEHAGE AS published with the chain homepage: its number sat in script data listing every member kindergarten | wrong company | 13-run audit | hidden-markup hits need a name-matching or declared domain; pages embedding ≥ 3 other valid (MOD11) org numbers are `ambiguous` | `test_orgnr_only_in_hidden_chain_data_is_not_exact` |
| 5 | Deadline run took 183 s with a 180 s limit | contract | external review | the client refuses requests inside the output reserve | `test_deadline_reserve_blocks_new_requests`, R09 |
| 6 | SSRF check and connection resolved DNS separately (rebinding window) | security | external review | connections open to the exact validated IP; env proxies ignored | `test_dns_rebinding_cannot_reach_private_address` |
| 7 | HTTP 429 on a verified site produced a false `removed_official_website` | false change | R10 | outage on a declared or previously verified site → `blocked`/`failed`, site facts kept `stale` | `test_rate_limited_site_keeps_site_facts_stale_not_removed` |
| 8 | Invalid-input envelopes lacked `legal_identity` and `summary` | contract | R05 | one contract-complete fallback builder | R05 |
| 9 | Facts published under sections marked not-available (careers page, budget-cut locations) | inconsistent state | verifier R5 | sections fixed; partial gaps noted in the reason | R08 |
| 10 | Site pages ("Hjem", "Kontakt") with Article markup counted as news | junk facts | R10 | `is_news_item` filter | `test_site_pages_are_not_news` |

Also covered by tests: redirect to loopback, metadata or private addresses blocked; oversized responses rejected; page text treated as data
(no instructions followed, scripts never executed); erasure via `tools/purge.py` stays effective on the next run (verified live).

## What these runs do not show

- **Jobs recall is low (0–2 per 100).** The NAV feed held about 9,100 active ads from about 5,600 employer names, and only about 1,250 of those names
  carry a legal "AS" suffix. Widening name matching added one candidate, which the orgnr check rejects. Most random companies have no NAV ad in 45 days.
  The matcher works: both known hiring companies in R07 were matched by orgnr.
- **Website recall is 6–12 % on random batches** (30–44 % on employer- or website-heavy batches). That's the price of publishing only proven matches.
  The optional Brave search connector (off by default; needs a key Builderr can reproduce) is the next lever and was not A/B-tested.
- **One batch of 1,000 companies was not run.** At about 8 requests per company, 1,000 companies would exceed a 2,000-request cap. R08 shows
  the behaviour when the budget binds: every envelope is written, the registry baseline is complete, and later sources are `blocked`.
