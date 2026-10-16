# Verification report

**Code tested: commit `3202c93c0b40c69d54405af20057bb19f7ded33b`** (recorded by the harness in `testruns/status.txt`; every run below
executed at exactly this commit, with the pinned dependencies in `requirements.txt`). This is the code freeze: later commits change
documentation and data artifacts only.

History note: commit messages were rewritten to remove tool-attribution trailers. This changed commit hashes only; the tested code's file tree is unchanged (tree `44c2418874205e490041323c910cc8854c364428`, originally committed as `e123b93`).

Reproduce: `bash testruns/run_all.sh && python testruns/verify_all.py` · Machine-readable: `testruns/RESULTS.json` · Offline tests: `python tests/test_agent.py` (38 pass)

**Result: 13/13 runs pass every contract check. Zero wrong-company publications in the tested code; the identity and security problems found
over three review rounds are fixed and covered by regression tests.**

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
| R13 | No fabricated financial values (qualification) | 5 companies per run re-fetched live from Regnskapsregisteret; each published value must equal the live record's value for the **same field, statement type (company/group), period end and currency**. A 1 NOK corruption is detected. |

`testruns/verify_all.py` adds run-specific expectations (marked * below).

## Results at `3202c93`

| Run | Purpose | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|---|
| R01 | random 100, JSONL universe rows | 100 | 4,376 | 9 | 0 | 824 | 474 s | PASS |
| R02 | random 100, plain-text input | 100 | 4,569 | 8 | 1 | 890 | 412 s | PASS |
| R03 | random 100, JSON list input | 100 | 4,417 | 8 | 0 | 865 | 428 s | PASS |
| R04 | random 100, gzipped JSONL | 100 | 4,546 | 11 | 0 | 815 | 420 s | PASS |
| R05 | random 100 + 2 duplicate rows + 2 invalid numbers | 102* | 4,507 | 12 | 0 | 881 | 411 s | PASS |
| R06 | 100 companies with ≥ 5 employees | 100 | 5,512 | 31 | 0 | 922 | 510 s | PASS |
| R07 | DIPS, Equinor, 2 hiring companies + 96 with registry website | 100 | 5,533 | 43 | 2 | 1,056 | 429 s | PASS |
| R08 | budget stress `--max-requests 300` | 100 | 4,189 | 0 | 0 | 300* | 39 s | PASS |
| R09 | deadline stress `--deadline-minutes 3` | 100 | 4,306 | 0 | 0 | 524 | **137 s*** | PASS |
| R10 | refresh of R01 with `--previous` | 100 | 4,376 | 9 | 0 | 831 | 474 s | PASS, 0 false changes* |
| R11 | random 100, companies never used before | 100 | 4,451 | 5 | 1 | 892 | 419 s | PASS |
| R12 | random 100, companies never used before | 100 | 4,589 | 8 | 0 | 898 | 464 s | PASS |
| R13 | random 100, companies never used before | 100 | 4,402 | 7 | 0 | 821 | 444 s | PASS |

\* R05: duplicates collapse to one envelope, and each invalid number gets a contract-complete `failed` envelope (100 + 2).
R08: the cap holds at exactly 300 requests; all 100 envelopes are still written, and 300 sections are marked `blocked` with "budget" as the reason.
R09: strict limit ≤ 180 s. The HTTP client refuses new requests inside the final output reserve.
R10: no change whose old and new values are identical.

**Financial check (R13):** 65 companies and **1,400 individual financial values** re-fetched live and compared by exact field, statement,
period and currency. All match.

**Coverage per section** (companies with `available`), 7 random batches (R01–R04, R11–R13): identity 100, financials 99–100, leadership 99–100,
locations 98–100, public activity 100, website 5–11, social profiles 3–7, contact 28–39, jobs 0–1.

**Source yield** (smoke run R01, `source_yield` in each run report): Brønnøysund 501 requests → 4,337 claims (8.7 per request) for 100 companies;
company websites 228 requests → 39 claims (0.17 per request) for 9 companies; NAV feed 95 requests → 0 claims in this batch.

## Identity audit (manual)

All **142 unique websites** published across the 13 runs were listed and reviewed by proof type:

- 31: the organisation number on a site the company declared to an official source (Brønnøysund `hjemmeside`, or the employer homepage of an orgnr-matched NAV ad)
- 35: the organisation number in the site's own identity block (footer/address, contact or about page, its JSON-LD Organization)
- 55: exact legal name (legal-form suffix in capitals) plus the registry's own phone or address, on a name-matching or declared domain
- 21: a declared site with the company's legal or brand name on the page

None rests on a name-matching domain alone, a recruiter's e-mail domain, a chain or group page, a third-party mention, or trust inherited across a redirect.

**What the final gate gave up:** compared with the previous code (148 sites), 8 were withheld as `ambiguous` and 2 others gained (run-to-run variance).
- 3 declared domains redirect to a different registered domain (for example, Bulk Data Centers → the group site `bulkinfrastructure.com`).
- 1 was proven only by a NAV contact e-mail domain.
- 4 have the org number in body text or script data rather than an identity block.

Some of these are probably genuine, but proof of ownership is missing, so they aren't published.

## 1,000-profile dataset

`profiles/profiles.jsonl.gz` holds **1,000 unique companies**, one envelope each, with 46,902 claims and 46,902 evidence records.
It is merged from R01–R07, R10 and R11–R13. All passed verification at `3202c93`; the builder refuses any run that didn't. Constrained runs
(R08, R09) are excluded. `profiles/profiles-manifest.json` records the commit, content SHA-256, source runs and section counts.

This dataset is a separate deliverable from the runtime evaluation. The agent never reads it: `run.py` researches whatever companies it's
given, and the only earlier data it reads is the previous run's snapshot, for the refresh comparison.

## Defects found by testing and three review rounds, and fixes

| # | Defect | Severity | Found by | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | ASTRA HOLDING AS matched a British site through the English word "as" | wrong company | smoke audit | legal-form suffix must appear in capitals | `test_english_as_does_not_satisfy_legal_suffix` |
| 2 | VESTGÅRD INVEST AS matched a related company's site through a shared phone | wrong company | smoke audit | declared sites need the entity's own name | `test_shared_phone_on_registry_site_is_not_exact` |
| 3 | SHARK AS matched `shark.no`, a different "Shark AS" | wrong company | 10-run audit | name-only rule removed | `test_same_name_other_company_on_matching_domain_is_not_exact` |
| 4 | NORLANDIA RATVIKA BARNEHAGE AS matched the chain homepage, whose script data listed every member's org number | wrong company | 13-run audit | hidden-markup and listing pages are `ambiguous` | `test_orgnr_only_in_hidden_chain_data_is_not_exact` |
| 5 | Any page mentioning the org number could prove an unrelated domain | wrong company (latent) | review 2 | number must be on a declared site or in the site's own identity block | `test_orgnr_on_third_party_page_is_not_official_website` |
| 6 | A name-matching domain counted as ownership, so an article there proved the site | wrong company (latent) | review 3 | name-matching no longer counts as ownership | `test_name_matching_domain_with_orgnr_only_in_article_is_ambiguous` |
| 7 | A NAV contact e-mail domain (possibly a recruiter's) counted as a declared site; trust survived cross-domain redirects | wrong company (latent) | review 3 | e-mail domains are discovery only; redirects to another registered domain lose declared status | `test_recruiter_email_domain_is_not_declared_website`, `test_declared_site_redirecting_to_other_domain_loses_trust` |
| 8 | Credentials forwarded on cross-host redirects | security | review 2 | client follows redirects hop by hop and drops credentials on origin change | `test_credentials_never_cross_origin_on_redirect` |
| 9 | NAV pagination could send the bearer token to another host or over plain HTTP | security | reviews 2–3 | pagination and entry URLs must be `https://pam-stilling-feed.nav.no`, default port, no credentials | `test_nav_pagination_never_leaves_feed_host`, `test_nav_pagination_https_downgrade_rejected` |
| 10 | SSRF check and connection resolved DNS separately (rebinding window) | security | review 1 | connections open to the exact validated IP | `test_dns_rebinding_cannot_reach_private_address` |
| 11 | Redirect hops bypassed the request budget and per-host limits | contract | review 2 | every hop reserves budget and the destination host's slot | `test_credentials_never_cross_origin_on_redirect` (counts) |
| 12 | Pretty-printed JSON input, or a single-number file, crashed the run with zero output | contract (whole batch) | review 2 / own retest | whole-file JSON first (lists/objects only), then JSONL, then text | `test_input_formats` |
| 13 | Deadline run took 183 s with a 180 s limit | contract | review 1 | client refuses requests inside the output reserve | `test_deadline_reserve_blocks_new_requests`, R09 |
| 14 | Financial verifier matched numbers anywhere in the response | test rigour | review 2 | exact tuple comparison | mutation check (1 NOK) |
| 15 | Cost ceiling only reported, not enforced | contract | review 2 | paid calls reserve cost first and are refused past `--max-cost-usd` | `test_cost_ceiling_enforced_before_paid_call` |
| 16 | HTTP 429 on a verified site produced a false removal; refusals mislabelled | false change / state | R10, audits | outages on declared or previously verified sites keep facts `stale`; refusals from plausible company sites → `blocked`; random `.com` bot walls ignored | `test_rate_limited_site_keeps_site_facts_stale_not_removed`, `test_site_refusing_requests_is_blocked_not_absent`, `test_unrelated_dotcom_bot_wall_is_not_reported_as_blocked` |
| 17 | Inconsistent states, invalid-input envelopes missing keys, junk news, snapshot fallback citing the live API | contract / quality | verifier | fixed individually | R05, R08, `test_site_pages_are_not_news` |

## What these runs do not show

- **Jobs recall is low (0–2 per 100).** The NAV feed holds about 9,100 active ads from about 5,600 employer names; only about 1,250 carry a legal suffix.
  Most random companies have no NAV ad in 45 days. The matcher works: both known hiring companies in R07 were matched by orgnr.
- **Website recall is 5–11 % on random batches** (31–43 % on employer- or website-heavy batches). That's the price of publishing only proven matches.
  The optional Brave search connector (off by default; it needs a key Builderr can reproduce) has not been A/B-tested.
- **The accounts API is a Brønnøysund "preview" service** without service guarantees. Outages are reported as `blocked`/`failed`, never as figures.
- **One batch of 1,000 companies was not run.** At about 8.7 requests per company, it would exceed a 2,000-request cap. R08 shows the behaviour:
  every envelope is written, the registry baseline is complete, and later sources are `blocked`.
- Network-security tests use stand-ins for the network, not a live hostile server.
