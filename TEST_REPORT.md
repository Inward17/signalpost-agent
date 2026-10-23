# Verification report

**Code tested: commit `a96e0f1d38e1db2c2323be8494de1f790ac855ab`** (version 2; recorded by the test harness, and every run below executed at exactly this commit,
with the pinned dependencies in `requirements.txt`). Version 2 addresses Builderr's audit of version 1 (`f49124a`). Later commits change
documentation, data artifacts and the verifier only.

Offline tests: `python tests/test_agent.py` (47 tests, included). The 13-run test harness was used for validation and is kept outside this
repository; its results are recorded here. The contract verifier `tools/verify_run.py` is included and can check any output folder.

**Result: 13/13 runs pass every contract check, including the four audit rules added for version 2. Zero wrong-company publications.**

## What changed in version 2 (Builderr audit)

Full before/after detail, old and new code, and step-by-step verification: [CHANGES_V2.md](CHANGES_V2.md).

| Builderr's finding | What version 1 did | Version 2 |
|---|---|---|
| Website must be the company's own, not a parent group or brand site | a site declared to Brønnøysund was accepted when its brand title appeared (for example ASK Spekehus AS → `askgard.no`); facts were harvested from a whole domain even when the company only owns a section of it (DNT Nord-Trøndelag on `dnt.no`) | a declared site needs the org number or the exact legal name (or brand plus the registry's own phone or address); a company site that is a section of a larger site yields no social accounts, news or jobs from that domain |
| Social links must name this company | 17 of 175 published accounts named a brand, the website or nothing (`Ringobamsen` for Nordic Toy Team AS, `instagram.com/accounts`, a YouTube channel ID) | an account is published only when its handle contains the company's distinctive name; platform paths (`accounts`, `login`, `hashtag`, `pages`) are rejected |
| News must be real, dated posts | 1 of 5 items was a contact page with article markup ("Kontakt oss"), 1 a theme demo post (`blog-test-1`) | a news item needs a post-like URL (date path or news/blog/press section), not a contact, product or shop page, menu label or demo slug; "modified"/"updated" dates are never used as publish dates |
| Jobs must be single ads for this company | 26 careers landing pages were published (some not careers pages at all) | careers pages are no longer published; JobPosting markup must name this company as employer; NAV jobs always link to the single ad |

Effect on published claims (dataset, version 1 → version 2): websites 142 → 137, social profiles 175 → 163, news 5 → 3, careers pages 26 → 0,
NAV job ads 4 → 7 (new live ads). Run against the version 1 dataset, the new checks report 43 violations; against version 2, none.

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
| R14 | Builderr audit rules (version 2) | every social handle names the company; every news item is a dated post; no careers landing pages; every NAV job links to a single ad |

`testruns/verify_all.py` (in the local harness) adds run-specific expectations (marked * below).

## Results at `a96e0f1`

| Run | Purpose | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|---|
| R01 | random 100, JSONL universe rows | 100 | 4,376 | 8 | 0 | 832 | 470 s | PASS |
| R02 | random 100, plain-text input | 100 | 4,563 | 7 | 1 | 892 | 407 s | PASS |
| R03 | random 100, JSON list input | 100 | 4,416 | 8 | 0 | 867 | 429 s | PASS |
| R04 | random 100, gzipped JSONL | 100 | 4,541 | 11 | 0 | 815 | 405 s | PASS |
| R05 | random 100 + 2 duplicate rows + 2 invalid numbers | 102* | 4,500 | 12 | 1 | 883 | 413 s | PASS |
| R06 | 100 companies with >=5 employees (website/jobs stress) | 100 | 5,512 | 32 | 1 | 925 | 508 s | PASS |
| R07 | 4 known companies + 96 with registry website | 100 | 5,505 | 40 | 4 | 1,045 | 422 s | PASS |
| R08 | budget stress: --max-requests 300 | 100 | 4,189 | 0 | 0 | 300* | 40 s | PASS |
| R09 | deadline stress: --deadline-minutes 3 | 100 | 4,305 | 0 | 0 | 523 | **135 s*** | PASS |
| R10 | refresh of R01 with --previous (idempotency / change detection) | 100 | 4,376 | 8 | 0 | 831 | 463 s | PASS, 0 false changes* |
| R11 | random 100, companies not used in any earlier run | 100 | 4,451 | 5 | 0 | 885 | 426 s | PASS |
| R12 | random 100, companies not used in any earlier run | 100 | 4,583 | 7 | 0 | 899 | 457 s | PASS |
| R13 | random 100, companies not used in any earlier run | 100 | 4,401 | 7 | 0 | 819 | 441 s | PASS |

\* R05: duplicates collapse to one envelope, and each invalid number gets a contract-complete `failed` envelope (100 + 2).
R08: the cap holds at exactly 300 requests; all 100 envelopes are still written, and 300 sections are marked `blocked` with "budget" as the reason.
R09: strict limit ≤ 180 s. The HTTP client refuses new requests inside the final output reserve.
R10: no change whose old and new values are identical.

**Financial check (R13):** 65 companies and **1,400 individual financial values** re-fetched live and compared by exact field, statement,
period and currency. All match.

**Coverage per section** (companies with `available`), 7 random batches (R01–R04, R11–R13): identity 100, financials 99–100, leadership 99–100,
locations 98–100, public activity 100, website 5–11, social profiles 3–6, contact 28–39, jobs 0–1. On employer- and website-heavy batches
(R06, R07), 32 and 40 companies have a verified website.

**Source yield** (smoke run R01): Brønnøysund 501 requests → 4,339 claims for 100 companies;
company websites 237 requests → 37 claims; NAV feed 94 requests → 0 claims in this batch.

## Identity audit (manual)

All **137 unique websites** published across the 13 runs were listed and reviewed by proof type:

- 30: the organisation number on a site the company declared to an official source (Brønnøysund `hjemmeside`, or the employer homepage of an orgnr-matched NAV ad)
- 36: the organisation number in the site's own identity block (footer/address, contact or about page, its JSON-LD Organization)
- 56: exact legal name (legal-form suffix in capitals) plus the registry's own phone or address, on a name-matching or declared domain
- 7: a declared site carrying the exact legal name
- 8: a declared site carrying the brand name plus the registry's own phone or address

None rests on a brand title alone, a name-matching domain alone, a recruiter's e-mail domain, a chain or group page, a third-party mention, or trust
inherited across a redirect. Compared with version 1, six declared sites that showed only a brand title (for example ASK Spekehus → `askgard.no`,
Webstep → `webstep.no`) are now withheld as `ambiguous`: some are probably genuine, but the proof Builderr asks for (org number or exact name) is missing.

## 1,000-profile dataset

`profiles/profiles.jsonl.gz` holds **1,000 unique companies**, one envelope each, with 46,848 claims and 46,848 evidence records.
It is merged from R01–R07, R10 and R11–R13. All passed verification (R1–R14) at `a96e0f1`; the builder refuses any run that didn't. Constrained runs
(R08, R09) are excluded. `profiles/profiles-manifest.json` records the commit, content SHA-256, source runs and section counts.

This dataset is a separate deliverable from the runtime evaluation. The agent never reads it: `run.py` researches whatever companies it's
given, and the only earlier data it reads is the previous run's snapshot, for the refresh comparison.

## Defects found by testing, reviews and Builderr's audit, and fixes

| # | Defect | Severity | Found by | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | ASTRA HOLDING AS matched a British site through the English word "as" | wrong company | smoke audit | legal-form suffix must appear in capitals | `test_english_as_does_not_satisfy_legal_suffix` |
| 2 | VESTGÅRD INVEST AS matched a related company's site through a shared phone | wrong company | smoke audit | declared sites need the entity's own name | `test_shared_phone_on_registry_site_is_not_exact` |
| 3 | SHARK AS matched `shark.no`, a different "Shark AS" | wrong company | 10-run audit | name-only rule removed | `test_same_name_other_company_on_matching_domain_is_not_exact` |
| 4 | NORLANDIA RATVIKA BARNEHAGE AS matched the chain homepage, whose script data listed every member's org number | wrong company | 13-run audit | hidden-markup and listing pages are `ambiguous` | `test_orgnr_only_in_hidden_chain_data_is_not_exact` |
| 5 | Any page mentioning the org number could prove an unrelated domain | wrong company (latent) | review 2 | number must be on a declared site or in the site's own identity block | `test_orgnr_on_third_party_page_is_not_official_website` |
| 6 | A name-matching domain counted as ownership | wrong company (latent) | review 3 | name-matching no longer counts as ownership | `test_name_matching_domain_with_orgnr_only_in_article_is_ambiguous` |
| 7 | Recruiter e-mail domains counted as declared; trust survived cross-domain redirects | wrong company (latent) | review 3 | e-mail domains are discovery only; redirects lose declared status | `test_recruiter_email_domain_is_not_declared_website`, `test_declared_site_redirecting_to_other_domain_loses_trust` |
| 8 | Group pages on undeclared name-matching domains were accepted | wrong company (latent) | review 4 | group pages need a declared, name-matching site | `test_group_page_on_undeclared_name_matching_domain_is_ambiguous`, `test_group_page_declared_by_the_company_on_its_name_domain_is_exact` |
| 9 | A declared group/brand site was accepted on its brand title alone | wrong company | **Builderr audit** | declared sites need the org number or exact legal name (or brand plus registry contact) | `test_declared_brand_site_needs_org_number_or_exact_name` |
| 10 | Social accounts, news and jobs were taken from a parent's domain when the company only owns a section of it | wrong company (facts) | **Builderr audit** | section sites yield no socials, news or jobs | `test_section_of_larger_site_detection`, `test_section_site_publishes_no_parent_socials_news_or_jobs` |
| 11 | Social accounts published for brand, website or opaque handles | wrong company (facts) | **Builderr audit** | handle must name the company; platform paths rejected | `test_social_handle_must_name_the_company` |
| 12 | Contact pages, menu labels and demo posts published as news; modified dates usable as publish dates | false facts | **Builderr audit** | post-like URL required; site pages, menu labels, demo slugs and modified dates rejected | `test_news_must_be_a_real_dated_post`, `test_modified_dates_are_not_publish_dates` |
| 13 | Careers landing pages published; site JobPostings not tied to the company | false facts | **Builderr audit** | careers pages dropped; JobPosting must name this company; NAV jobs link to the single ad | `test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs` |
| 14 | Credentials forwarded on cross-host redirects | security | review 2 | hop-by-hop redirects; credentials dropped on origin change | `test_credentials_never_cross_origin_on_redirect` |
| 15 | NAV token could leave the feed host or travel over plain HTTP | security | reviews 2–3 | pagination and entry URLs must be `https://pam-stilling-feed.nav.no` | `test_nav_pagination_never_leaves_feed_host`, `test_nav_pagination_https_downgrade_rejected` |
| 16 | SSRF check and connection resolved DNS separately (rebinding window) | security | review 1 | connections open to the exact validated IP | `test_dns_rebinding_cannot_reach_private_address` |
| 17 | Redirect hops bypassed the request budget and per-host limits | contract | review 2 | every hop reserves budget and the destination host's slot | `test_credentials_never_cross_origin_on_redirect` (counts) |
| 18 | Pretty-printed JSON input, or a single-number file, crashed the run with zero output | contract (whole batch) | review 2 / own retest | whole-file JSON first (lists/objects only), then JSONL, then text | `test_input_formats` |
| 19 | Deadline run took 183 s with a 180 s limit | contract | review 1 | client refuses requests inside the output reserve | `test_deadline_reserve_blocks_new_requests`, R09 |
| 20 | Financial verifier matched numbers anywhere in the response | test rigour | review 2 | exact tuple comparison | mutation check (1 NOK) |
| 21 | Cost ceiling only reported, not enforced | contract | review 2 | paid calls reserve cost first and are refused past `--max-cost-usd` | `test_cost_ceiling_enforced_before_paid_call` |
| 22 | HTTP 429 on a verified site produced a false removal; refusals mislabelled | false change / state | R10, audits | outages keep facts `stale`; refusals from plausible company sites → `blocked` | `test_rate_limited_site_keeps_site_facts_stale_not_removed`, `test_site_refusing_requests_is_blocked_not_absent`, `test_unrelated_dotcom_bot_wall_is_not_reported_as_blocked` |
| 23 | Inconsistent states, invalid-input envelopes missing keys, snapshot fallback citing the live API | contract / quality | verifier | fixed individually | R05, R08 |

## What these runs do not show

- **Jobs recall is low (0–1 per 100 random companies).** Most random companies have no NAV ad in 45 days; the matcher is precise (orgnr-verified).
- **Website recall is 5–11 % on random batches** (32–40 % on employer- or website-heavy batches): the price of publishing only proven matches.
  The strict social rule also withholds some genuine accounts whose handle uses only one word of a multi-word name (for example `sollifjellet`).
- The optional Brave search connector (off by default; it needs a key Builderr can reproduce) has not been A/B-tested.
- **The accounts API is a Brønnøysund "preview" service** without service guarantees. Outages are reported as `blocked`/`failed`, never as figures.
- **One batch of 1,000 companies was not run.** At about 8.7 requests per company it would exceed a 2,000-request cap; R08 shows the behaviour.
- Network-security tests use stand-ins for the network, not a live hostile server.
