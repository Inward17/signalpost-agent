# Verification report

**Code tested: commit `70cfcf091640d4742684a036f988d08624d1d69d`** (version 2.2; recorded by the test harness, and every run below executed at exactly this commit,
with the pinned dependencies in `requirements.txt`). Version 2.0 addressed Builderr's audit of version 1 (`f49124a`); version 2.1 addresses a
second review of version 2.0; version 2.2 closes two residual risks raised after that (parent root domains,
attributable social accounts). Later commits change documentation, data artifacts and the verification tools only.

Offline tests: `python tests/test_agent.py` (56 tests, included). The 13-run test harness was used for validation and is kept outside this
repository; its results are recorded here. The contract verifier `tools/verify_run.py` and the audit replay `tools/verify_v2_fixes.py` are included.

**Result: 13/13 runs pass every contract check (R1–R14). Zero wrong-company publications.**

Before/after detail for every change, with old and new code and step-by-step verification: [CHANGES_V2.md](CHANGES_V2.md).

## What changed since version 1

| Finding | Version 1 | Now |
|---|---|---|
| Website must be the company's own (Builderr audit) | declared sites accepted on a brand title; parent-domain facts harvested for section sites | declared sites need the org number, exact legal name, or brand plus registry contact; section sites yield no socials, news or jobs |
| Social handles must belong to this company (Builderr audit + second review) | brand, website-name and opaque accounts published; in v2.0 also sister, parent, subsidiary and group accounts whose handle shared words with the company | every distinctive word of the legal name must be in the handle; leftovers only harmless affixes (`as`, `no`, `norge`, …), legal-name words or a page ID |
| News must be real, dated posts (Builderr audit + second review) | contact pages and demo posts counted; in v2.0 a date shared by several articles could be pinned to the first, and legitimate news with unusual URLs was dropped | site pages, products, menu labels and demo posts rejected; a date is used only when it belongs to exactly one article; dates must be plausible; explicit news types and structured list entries may use any URL |
| Site content only from the company's own site (residual-risk review) | a subsidiary declared with its parent's root domain got the parent's description, accounts, news and jobs | only the URL is published unless the site is shown to be the company's own |
| Social accounts must be attributable (residual-risk review) | any matching-name link on any page, including article text and another organisation's `sameAs` | only accounts the company presents as its own: site chrome, contact/about page, repeated across its pages, or its own structured data |
| Jobs must be single ads for this company (Builderr audit + second review) | careers landing pages published; in v2.0 a similar employer name (brand without legal form, other legal form) could pass | careers pages dropped; employer must carry this org number or the exact legal name including legal form; NAV jobs link to the single ad |

Applying the current rules to each version's published dataset: **v1 89 problems, v2.0 38 (social handles), v2.1 0, v2.2 0.**
Published claims, v1 → v2.0 → v2.1 → v2.2: websites 142 → 137 → 136 → 137, social profiles 175 → 163 → 124 → 113, news 5 → 3 → 3 → 3,
careers pages 26 → 0 → 0 → 0, NAV job ads 4 → 7 → 8 → 8 (live data changes daily).

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
| R14 | Builderr audit rules | every social handle belongs to the company; every news item is a real post; no careers landing pages; every NAV job links to a single ad; no claim taken from a site not shown to be the company's own |

The run harness adds run-specific expectations (marked * below).

## Results at `70cfcf0`

| Run | Purpose | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|---|
| R01 | random 100, JSONL universe rows | 100 | 4,367 | 8 | 0 | 827 | 473 s | PASS |
| R02 | random 100, plain-text input | 100 | 4,561 | 7 | 1 | 890 | 417 s | PASS |
| R03 | random 100, JSON list input | 100 | 4,410 | 8 | 0 | 862 | 444 s | PASS |
| R04 | random 100, gzipped JSONL | 100 | 4,539 | 11 | 0 | 812 | 414 s | PASS |
| R05 | random 100 + 2 duplicate rows + 2 invalid numbers | 102* | 4,490 | 12 | 2 | 883 | 410 s | PASS |
| R06 | 100 companies with >=5 employees (website/jobs stress) | 100 | 5,498 | 32 | 1 | 917 | 516 s | PASS |
| R07 | 4 known companies + 96 with registry website | 100 | 5,487 | 40 | 4 | 1,046 | 428 s | PASS |
| R08 | budget stress: --max-requests 300 | 100 | 4,189 | 0 | 0 | 300* | 41 s | PASS |
| R09 | deadline stress: --deadline-minutes 3 | 100 | 4,305 | 0 | 0 | 525 | **136 s*** | PASS |
| R10 | refresh of R01 with --previous (idempotency / change detection) | 100 | 4,367 | 8 | 0 | 829 | 477 s | PASS, 0 false changes* |
| R11 | random 100, companies not used in any earlier run | 100 | 4,451 | 5 | 0 | 877 | 424 s | PASS |
| R12 | random 100, companies not used in any earlier run | 100 | 4,581 | 7 | 0 | 895 | 472 s | PASS |
| R13 | random 100, companies not used in any earlier run | 100 | 4,396 | 7 | 0 | 815 | 456 s | PASS |

\* R05: duplicates collapse to one envelope, and each invalid number gets a contract-complete `failed` envelope (100 + 2).
R08: the cap holds at exactly 300 requests; all 100 envelopes are still written, and 300 sections are marked `blocked` with "budget" as the reason.
R09: strict limit ≤ 180 s. The HTTP client refuses new requests inside the final output reserve.
R10: no change whose old and new values are identical.

**Financial check (R13):** 65 companies and **1,400 individual financial values** re-fetched live and compared by exact field, statement,
period and currency. All match.

**Coverage per section** (companies with `available`), 7 random batches (R01–R04, R11–R13): identity 100, financials 99–100, leadership 99–100,
locations 98–100, public activity 100, website 5–11, social profiles 2–4, contact 28–39, jobs 0–1. On employer- and website-heavy batches
(R06, R07), 31 and 40 companies have a verified website.

**Source yield** (smoke run R01): Brønnøysund 501 requests → 4,339 claims for 100 companies;
company websites 233 requests → 28 claims; NAV feed 93 requests → 0 claims in this batch.

## Identity and social audit (manual)

All **137 unique websites** published across the 13 runs were listed and reviewed by proof type:

- 31: the organisation number on a site the company declared to an official source (Brønnøysund `hjemmeside`, or the employer homepage of an orgnr-matched NAV ad)
- 36: the organisation number in the site's own identity block (footer/address, contact or about page, its JSON-LD Organization)
- 55: exact legal name (legal-form suffix in capitals) plus the registry's own phone or address, on a name-matching or declared domain
- 7: a declared site carrying the exact legal name
- 8: a declared site carrying the brand name plus the registry's own phone or address

Site ownership (version 2.2): for 105 the domain matches the company name, 14 carry the org number and 10 the exact legal name in the site's
own footer or contact block, and **8 are published as URL only** because the site isn't shown to be the company's own. One of those 8,
`vif-fotball.no`, is a genuinely shared site (the club Vålerenga Fotball and the separate entity Vålerenga Fotball Elite). The other 7 look like
the companies' own sites but carry neither the org number nor the exact legal name in their footer, so their site facts are withheld.

None rests on a brand title alone, a name-matching domain alone, a recruiter's e-mail domain, a chain or group page, a third-party mention, or trust
inherited across a redirect.

All 113 published social accounts were also checked by hand. Every handle that isn't simply the company's exact name is that name plus
only `as`, `asa`, `no`, `norge`, a country word or a number (for example `dips_as`, `sodvin.as`, `storkasnorge`, `eta-norge-as`). None belongs to a
sister, parent, branch or other company, and each is presented by the company itself (site chrome, contact page, repeated
across its pages or its own structured data). Compared with version 2.1, 11 accounts are withheld: 6 on the 8 URL-only sites (including
`linkedin.com/company/oslo-og-omegn-boligforvaltning-as` for a BBL, the handle of a different legal entity) and 5 linked only in the body of
a single page.

## 1,000-profile dataset

`profiles/profiles.jsonl.gz` holds **1,000 unique companies**, one envelope each, with 46,780 claims and 46,780 evidence records.
It is merged from R01–R07, R10 and R11–R13. All passed verification (R1–R14) at `70cfcf0`; the builder refuses any run that didn't. Constrained runs
(R08, R09) are excluded. `profiles/profiles-manifest.json` records the commit, content SHA-256, source runs and section counts.

This dataset is a separate deliverable from the runtime evaluation. The agent never reads it: `run.py` researches whatever companies it's
given, and the only earlier data it reads is the previous run's snapshot, for the refresh comparison.

## Defects found by testing, reviews and Builderr's audit, and fixes

| # | Defect | Severity | Found by | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | ASTRA HOLDING AS matched a British site through the English word "as" | wrong company | smoke audit | legal-form suffix must appear in capitals | `test_english_as_does_not_satisfy_legal_suffix` |
| 2 | VESTGÅRD INVEST AS matched a related company's site through a shared phone | wrong company | smoke audit | declared sites need the entity's own name | `test_shared_phone_on_registry_site_is_not_exact` |
| 3 | SHARK AS matched `shark.no`, a different "Shark AS" | wrong company | 10-run audit | name-only rule removed | `test_same_name_other_company_on_matching_domain_is_not_exact` |
| 4 | NORLANDIA RATVIKA BARNEHAGE AS matched the chain homepage | wrong company | 13-run audit | hidden-markup and listing pages are `ambiguous` | `test_orgnr_only_in_hidden_chain_data_is_not_exact` |
| 5 | Any page mentioning the org number could prove an unrelated domain | wrong company (latent) | review | number must be on a declared site or in the site's own identity block | `test_orgnr_on_third_party_page_is_not_official_website` |
| 6 | A name-matching domain counted as ownership | wrong company (latent) | review | name-matching no longer counts as ownership | `test_name_matching_domain_with_orgnr_only_in_article_is_ambiguous` |
| 7 | Recruiter e-mail domains counted as declared; trust survived redirects | wrong company (latent) | review | e-mail domains are discovery only; redirects lose declared status | `test_recruiter_email_domain_is_not_declared_website`, `test_declared_site_redirecting_to_other_domain_loses_trust` |
| 8 | Group pages on undeclared name-matching domains accepted | wrong company (latent) | review | group pages need a declared, name-matching site | `test_group_page_on_undeclared_name_matching_domain_is_ambiguous` |
| 9 | Declared group/brand site accepted on its brand title alone | wrong company | **Builderr audit** | org number or exact legal name (or brand plus registry contact) | `test_declared_brand_site_needs_org_number_or_exact_name` |
| 10 | Socials, news and jobs taken from a parent's domain for section sites | wrong company (facts) | **Builderr audit** | section sites yield no socials, news or jobs | `test_section_site_publishes_no_parent_socials_news_or_jobs` |
| 11 | Brand, website-name and opaque social accounts published | wrong company (facts) | **Builderr audit** | handle must name the company; platform paths rejected | `test_social_handle_must_name_the_company` |
| 12 | Contact pages and demo posts as news; modified dates usable | false facts | **Builderr audit** | site pages, menu labels, demo slugs and modified dates rejected | `test_news_must_be_a_real_dated_post`, `test_modified_dates_are_not_publish_dates` |
| 13 | Careers landing pages published; site JobPostings not tied to the company | false facts | **Builderr audit** | careers pages dropped; JobPosting must name this company; NAV single-ad links | `test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs` |
| 14 | Sister, parent, subsidiary, group and other-company accounts accepted because the handle shared words with the company | wrong company (facts) | **second review of v2.0** | every distinctive word required; leftovers only harmless affixes | `test_social_handle_must_name_the_company` (23 cases) |
| 15 | One date shared by several articles pinned to the first; implausible dates accepted; news with unusual URLs dropped | false facts / recall | **second review of v2.0** | date bound to exactly one article; plausible dates only; explicit news types and list entries may use any URL | `test_news_date_must_belong_to_one_article`, `test_explicit_news_types_accept_unusual_urls_but_generic_articles_do_not` |
| 16 | Website job accepted for a similar employer name (brand without legal form, other legal form, other org number) | wrong company (facts) | **second review of v2.0** | this org number or exact legal name including legal form | `test_website_job_needs_exact_employer_not_a_similar_name`, `test_nav_job_with_similar_employer_name_is_not_published` |
| 17 | Credentials forwarded on cross-host redirects | security | review | hop-by-hop redirects; credentials dropped on origin change | `test_credentials_never_cross_origin_on_redirect` |
| 18 | NAV token could leave the feed host or travel over plain HTTP | security | review | pagination and entry URLs must be `https://pam-stilling-feed.nav.no` | `test_nav_pagination_https_downgrade_rejected` |
| 19 | DNS-rebinding window between check and connect | security | review | connections open to the exact validated IP | `test_dns_rebinding_cannot_reach_private_address` |
| 20 | Redirect hops bypassed the request budget | contract | review | every hop reserves budget and the destination host's slot | `test_credentials_never_cross_origin_on_redirect` (counts) |
| 21 | Pretty-printed JSON or a single-number input crashed the run | contract (whole batch) | review / own retest | whole-file JSON first, then JSONL, then text | `test_input_formats` |
| 22 | Deadline run took 183 s with a 180 s limit | contract | review | client refuses requests inside the output reserve | `test_deadline_reserve_blocks_new_requests` |
| 23 | Financial verifier matched numbers anywhere in the response | test rigour | review | exact tuple comparison | mutation check (1 NOK) |
| 24 | Cost ceiling only reported, not enforced | contract | review | paid calls reserve cost first | `test_cost_ceiling_enforced_before_paid_call` |
| 26 | A subsidiary declared with its parent's root domain (no path to detect) got the parent's description, accounts, news and jobs | wrong company (facts) | **residual-risk review** | content only when the site is shown to be the company's own; otherwise URL only | `test_subsidiary_declared_with_parent_root_domain_gets_no_parent_facts`, `test_subsidiarys_own_root_site_keeps_its_facts`, `test_footer_listing_several_companies_does_not_prove_site_owner` |
| 27 | A full-name account linked only in article text, or in another organisation's `sameAs`, was published | wrong company (facts) | **residual-risk review** | only accounts the company presents as its own | `test_social_account_must_be_attributable_not_just_name_matching`, `test_social_link_repeated_across_site_pages_counts_as_site_chrome` |
| 25 | HTTP 429 on a verified site produced a false removal; refusals mislabelled | false change / state | refresh run, audits | outages keep facts `stale`; plausible-site refusals → `blocked` | `test_rate_limited_site_keeps_site_facts_stale_not_removed` |

## What these runs do not show

- **Jobs recall is low (0–1 per 100 random companies).** Most random companies have no NAV ad in 45 days; the matcher is precise (orgnr-verified).
- **Website recall is 5–11 % on random batches** (31–40 % on employer- or website-heavy batches): the price of publishing only proven matches.
- **Site facts are withheld for 8 of 137 websites** whose footer shows neither the org number nor the exact legal name; most of these are
  probably the company's own sites. Withholding is the safer error.
- **Social recall is deliberately conservative (2–4 per 100).** Accounts that add a descriptive word not in the legal name are withheld even
  when they're probably the company's own (for example `perrioppussing`, `danvikfhs`).
- The optional Brave search connector (off by default; it needs a key Builderr can reproduce) has not been A/B-tested.
- **The accounts API is a Brønnøysund "preview" service** without service guarantees. Outages are reported as `blocked`/`failed`, never as figures.
- **One batch of 1,000 companies was not run.** At about 8.7 requests per company it would exceed a 2,000-request cap; R08 shows the behaviour.
- Network-security tests use stand-ins for the network, not a live hostile server.
