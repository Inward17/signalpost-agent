# Implementation walkthrough

This document explains what was built, how each part works, why it was designed that way, and which checks from the original
plan are done, partly done, or still open.

## 1. Starting point: the real contract

Before writing code, the official Builderr material was downloaded and read. It turned out to be more authoritative than the plan:
the challenge page, the evaluation contract (`signalpost-evaluation-harness.md`), the participant brief, the source policy, the agent playbook,
the learning harness, the starter kit, the 411,160-company universe and the 100-profile sample site. Findings that shaped the design:

| Finding | Consequence |
|---|---|
| Scoring v2 is 50 recall / 30 precision / 12 synthesis / 8 UX; recall is 70 % company coverage + 30 % fact count per *external* field family | Cover many companies thinly before covering a few deeply → breadth-first phases |
| A material wrong-company publication blocks the run from becoming official | The identity gate is the most heavily tested component; uncertain matches become `ambiguous` |
| Exactly one terminal envelope per input with the six states | A per-company exception boundary, a fallback envelope builder, and a `failed` envelope for invalid inputs |
| Refresh must be idempotent and keep prior evidence | Stable content-hashed claim IDs, a state directory, and an append-only history |
| Search results are candidates, never evidence; LinkedIn/Meta/Indeed scraping isn't allowed | No search-page scraping; the optional search API only proposes domains |
| Only ~11 % of the universe has a registry website, and ~85 % has no registered employees | Website discovery beyond the registry and a cheap, exact jobs source matter most |
| The starter kit already had safe-URL and social-link helpers but used non-contract states and a registry-website-only crawl | Its proven ideas were reused (SSRF guard, social normalisation, parked markers); the pipeline and envelope were rewritten to the contract |

Sources were probed live before integrating. Two outcomes changed the design:

- **Brreg announcement pages** (`w2.brreg.no/kunngjoring`) are disallowed in `robots.txt`. The agent detected this on its first run and returned
  `blocked`. That source was replaced by the official **registry change-log API** (`oppdateringer/enheter?includeChanges=true`), which gives dated
  field-level changes and is allowed.
- **NAV's job feed** has a public token endpoint and an `If-Modified-Since` jump-in. Ads carry `employer.orgnr`, so jobs can be matched by
  organisation number with zero name guessing.

## 2. Repository layout

```
run.py                     CLI + breadth-first orchestrator, output writing, run report
signalpost/http.py         the only outbound HTTP path: budget, deadline, SSRF guard, robots, size limits
signalpost/dossier.py      per-company fact store: claims, evidence, section states
signalpost/registry.py     Brønnøysund: entity, accounts, roles, subunits, change log
signalpost/jobs.py         NAV vacancy feed index + orgnr-verified matching
signalpost/website.py      website discovery, identity gate, company-owned extraction
signalpost/envelope.py     envelope assembly, refresh diff, cited synthesis
signalpost/report.py       self-contained HTML viewer
tests/test_agent.py        34 offline tests (identity gate, refresh, SSRF/redirects/rebinding, credentials, budgets, input formats, no-zero-fill)
smoke/                     100-company batch, first run (out/), refresh run (out-refresh/), logs
README.md  SOURCES_AND_SECURITY.md  SUBMISSION.md  WALKTHROUGH.md
```

About 1,900 lines of Python. Dependencies: `beautifulsoup4` (using the stdlib `html.parser`) and `tldextract` (using its bundled suffix list,
so no network call), plus their pinned transitive packages in `requirements.txt`. There's no framework, database server or LLM.

## 3. Pipeline, step by step

`python run.py --input companies.jsonl --output out`

### 3.1 Input (`run.py: read_inputs`)
The input can be a JSON list or object (compact or pretty-printed: the whole file is tried as JSON first), JSONL rows (the universe format), or a plain text list (one per line, or comma-separated), optionally gzipped. Each row is normalised to 9 digits.
Duplicates collapse to one envelope, and invalid values get their own `failed` envelope, so no input row ever disappears.
Snapshot fields in the input row (name, website, municipality) are kept as a fallback identity if the live registry fails.

### 3.2 Breadth-first phases (`run.py: phase`)
Each phase runs over **all** companies (16 worker threads) before the next one starts:

1. identity → 2. accounts → 3. roles → 4. subunits → 5. registry change log → 6. NAV feed walk + job matching → 7. website.

If the request budget or deadline runs out partway, every company already has the official baseline, and the remaining sources are
marked `blocked` with the reason. Every per-company call is wrapped in a try/except boundary: an exception marks only that section
`failed` and records the traceback in `errors`; the batch continues. A `wait(timeout=…)` cuts off stragglers before the deadline, and
`Dossier.frozen` stops late threads from changing an envelope while it's being written.

### 3.3 HTTP layer (`http.py`)
- `Client.get` is the only way out. Every call reserves a request from `--max-requests` (default 2000) and checks `--deadline-minutes`
  (default 42 of the 45 allowed). Going over raises `BudgetExhausted`, so the limits are enforced, not just reported.
- **SSRF guard**: http(s) only, ports 80/443 only, no localhost/`.local`; every resolved IP must be globally routable. Connections open to the
  exact IP that passed the check (no second DNS lookup, so no rebinding window); environment proxies are ignored.
- **Redirects** are followed by `Client.get` itself, not by urllib: at most 5 hops, and each hop is validated, robots-checked when the caller asked
  for robots, counted against the request budget and limited by the *destination* host's concurrency. On any change of origin (scheme, host
  or port) `Authorization`, `Cookie`, `X-Subscription-Token` and similar headers are dropped, so a credential never reaches another host.
  The NAV feed's `next_url` and entry URLs must stay on the feed host.
- **Cost ceiling**: `--max-cost-usd` (default 10). A paid call reserves its cost before the request and is refused if it would cross the ceiling.
- Limits: 2 MB per page (8 MB per feed page), 15 s timeout, at most one retry on 429/5xx. At most 6 concurrent requests to brreg.no and 2 to any other host.
- `robots.txt` is fetched once per host and honoured for all non-API pages. A 401/403 on robots means disallow-all.
- Requests are attributed per company through a thread-local, so each envelope reports its own request count.

### 3.4 Fact model (`dossier.py`)
- **Evidence** records: source URL, requested URL, source class, retrieval time, HTTP status, SHA-256 of the response body, a short
  claim span (the exact field/value or text excerpt), and the extraction method. The ID is a hash of URL + content hash + span.
- **Claims**: field, section, value, evidence IDs, confidence, reporting period, effective date, and method. `claim_key` is the stable identity of
  the fact (for example `revenue|selskap|2025-12-31` or `job|<uuid>`). `claim_id = hash(org, key, value)`, so the same fact always gets the same ID.
- **Sections** (9 families: identity, financials, leadership, locations, website, social_profiles, contact, jobs, public_activity) each carry
  one of the six contract states plus a human-readable reason. An `available` section is never downgraded by a later, weaker source;
  two `available` sources merge their reasons.

### 3.5 Official registry (`registry.py`)
- **Entity** (`/enheter/{org}`): the response must echo the requested org number. Claims include legal name, form, status (active, bankrupt, liquidating,
  forced dissolution), addresses, municipality, industries, registered employees with their effective date, founding/registration dates, registry
  website, phone (not published for sole traders: personal data), VAT, group flag, share capital, registered activity, historical names
  and latest filed year. The registry website becomes the first website candidate.
- **Accounts** (`regnskap/{org}`): every filed period, with company and group statements kept separate. Eight fields per period, each a claim with
  `reporting_period` and currency. A field missing from the filing is **absent, never 0**. A 404 for exempt forms (ENK/ANS/DA) → `not_applicable`.
- **Roles**: active, non-deceased holders only. Birth dates are dropped. Organisation holders (for example auditors) keep their org number.
- **Subunits**: registered workplaces with address, industry and employees. Their org numbers and names feed the job matcher.
- **Change log**: field-level dated changes over the last 24 months. Housekeeping timestamps are filtered out, and only meaningful fields are kept
  (name, address, website, employees, filings, capital…).

### 3.6 Jobs (`jobs.py`)
- One feed walk per run, shared by the whole batch. The public token comes from `/api/publicToken` (or `NAV_FEED_TOKEN`). The walk enters with
  `If-Modified-Since = now − 45 days` and follows `next_url`; it took about 95 pages for 30k entries. The latest status per ad UUID wins.
- Active entries are indexed by normalised employer name. Candidates match the legal name, a subunit name, or `"<legal name> …"` (department names).
- **Publication rule**: each candidate ad is re-fetched, and it's published only if `employer.orgnr` is the company or one of its subunits. If the ad has no
  orgnr, the employer name must equal the registered legal name exactly. Similar names with a different orgnr are dropped.
- From verified ads, the employer homepage and contact-email domains become *declared* website candidates.

### 3.7 Website (`website.py`)
**Candidates**, in order: registry/subunit `hjemmeside`; NAV employer homepage and email domain (only from ads whose orgnr matches the company);
name-derived domains (`sandneselektriske.no`, `sandnes-elektriske.no`, `.com`; generic names like "HOLDING AS" are skipped) that are checked
by DNS first, so no HTTP is spent on non-existent domains; then optional Brave API results. Directory and social sites are never treated as candidates.
At most 6 domains per company.

**Unreachable candidates**: an explicit 403/429 from an officially declared site, the previously verified site, or a name-derived `.no`
domain makes the section `blocked`. A timeout or 5xx on a declared or previously verified site makes it `failed`, and its last facts are
kept `stale`. Errors on random guesses (for example a `.com` bot wall) leave it `not_available`.

**Crawl**: robots check, homepage, then contact/about pages only while proof is still missing. After a match, news and careers pages are fetched too.
At most about 8 requests per site.

**Identity gate** (`assess_identity`), in priority order:

1. The org number (in any separator format) on a page → **exact 1.0**, unless that page also lists other org numbers *and* the domain doesn't match
   the name. That case is a group/portfolio page → `ambiguous`. On a domain that is neither name-matching nor officially declared, the
   number must sit in the site's **own identity block**: footer/address, a contact or about page, or its JSON-LD Organization. A news
   article or a client list naming the company on someone else's domain is `ambiguous`. A number found only in hidden markup needs a
   name-matching or declared domain and a page that does not embed ≥ 3 other valid (MOD11) org numbers (chain sites list every member).
2. A different labelled org number or VAT id on the site → **rejected** (parent, sister or unrelated entity).
3. A parked, for-sale or placeholder page → **rejected**.
4. The exact legal name *with its legal suffix in capitals* (`Sandnes Elektriske AS`, so the English word "as" can't satisfy it) plus the registry phone
   or the registered street and postcode → exact 0.97, but only on a name-matching domain or an officially declared site.
5. An officially declared site plus the legal or brand name on the page → exact 0.92. A contact detail alone is **not** enough, because shared phones point to related companies.
6. Anything weaker → `ambiguous`, recorded with the reason and the candidate list, and nothing published.

**Extraction from an exact site**: the website claim with its identity method and score; the description (meta/og or first paragraph), labelled as
company copy; the brand (`og:site_name`); social profiles linked from the site, kept only if the handle matches the name or domain or the profile is listed in
the site's JSON-LD `sameAs` (other links are counted and withheld); generic mailboxes on the company's own domain; phone numbers from `tel:` links on the home and contact pages;
dated news from JSON-LD articles and `<time>` elements on the news page; the careers page; JSON-LD `JobPosting` entries.

### 3.8 Refresh (`envelope.py: diff`)
The previous snapshot comes from `--previous envelopes.jsonl` or from `state/<org>.json`. For each claim key:
- same `claim_id` → unchanged; `first_observed_at` is carried forward;
- different value → `changed_<field>` / `changed_description`, with the **old evidence embedded** in the change record;
- new key → `new_job`, `new_role`, `new_location`, `new_filing`, `new_social_profile`…;
- missing key while the source was checked successfully → `closed_job`, `removed_role`, `closed_location`… This applies only to fact types where
  disappearing means something; dated feeds (filings, news, change log) just roll out of their window and don't count as removals;
- missing key while the source is `blocked` or `failed` → the last value is **kept and flagged `stale`**, its evidence copied over, and the section notes how many
  claims were retained.
Change IDs hash (org, key, old claim, new claim), so a rerun on an unchanged snapshot produces zero changes.
`state/history/<org>.jsonl` appends every run's evidence and changes and is never overwritten. A broken run never replaces a good baseline.

### 3.9 Synthesis (`envelope.py: synthesize`)
A deterministic template over published claims. Each sentence lists the `claim_ids` it was built from: identity line, what the company does
(website description, else registered purpose), employees, latest accounts with a calculated, labelled revenue change, CEO/chair,
workplaces, verified website, linked profiles, hiring, latest news, and recent register changes. It also produces a `changes` list and an `unknowns` list
(every non-available section with its state and reason). There's no LLM, so nothing can be invented and nothing costs money.

### 3.10 Outputs
- `envelopes.jsonl`: written atomically (temp file + rename).
- `run-report.json`: one-envelope-per-input check, envelope and section state counts, claims, changes, requests, bytes, top hosts,
  p50/p95 latency, runtime, cost, feed pages.
- `report.html`: one self-contained file. You can search by name, org number or municipality, filter (verified website, hiring, social, changed, ambiguous), and
  see colour dots for the 9 sections. The detail view has KPIs, the cited summary, changes and unknowns, every claim with an expandable evidence span, source link and
  retrieval time. It has a responsive single-column layout on mobile, supports dark mode, and escapes all values before rendering (no HTML from sources).

## 4. Bugs found during testing and how they were fixed

| Problem | Found by | Fix |
|---|---|---|
| All envelopes `failed`: build couldn't fill missing sections after `frozen` was set | first 4-company run | sections are defaulted directly in `build` |
| `lxml` tree builder not detected | first run | switched to stdlib `html.parser`, removed the dependency |
| Announcement pages disallowed in robots.txt | the agent itself reported `blocked` | replaced with the official change-log API |
| **Wrong company**: "ASTRA HOLDING AS" (Osterøy) matched a British `astraholding.com` because the English "as" satisfied the "AS" suffix | manual audit of all 16 published sites in the first smoke run | suffix must appear in capitals; the name-plus-domain rule is limited to `.no` |
| **Wrong company**: "VESTGÅRD INVEST AS" matched `xpartner.as` through a shared phone number on a registry-declared site | same audit | declared sites now need the entity's own name; contact-only → `ambiguous` |
| Group pages listing many org numbers could prove any subsidiary | review | multi-org pages count as proof only on a name-matching domain |
| Contact section showed "not reached" even though a registry phone existed | smoke review | the registry phone sets `contact` to available |
| **Wrong company**: SHARK AS (Sandefjord) matched `shark.no`, which shows a different "Shark AS" (Kolbotn) | 10-run audit | name-only rule removed entirely |
| HTTP 429 on a verified site produced a false `removed_official_website` | 10-run refresh (R10) | outage on a declared or previously verified site → `blocked`/`failed`, site facts kept `stale` |
| Further state and contract gaps (invalid-input envelopes, careers page, budget-cut locations, junk news) | `tools/verify_run.py` | see TEST_REPORT.md |
| Field-less "Ukjent" change-log rows showing up as activity | smoke review | only rows with real changes, or new/deleted rows, are kept |

Each of the identity-gate failures has a regression test.

## 5. Results

**13 verification runs at `f0b3f58`** (see [TEST_REPORT.md](TEST_REPORT.md)): all pass the 13 contract rule groups; 148 unique published
websites manually audited by proof type; 65 financial spot-checks against the live filing all matched; 1,000-profile dataset in `profiles/`.

**Earlier smoke test (first code version, before the final gate fixes):** 100/100 envelopes, 4,621 claims, 870 of 2,000 requests, 482 s, $0.
The current `smoke/` folder holds the final-code run (R01): 4,376 claims, 781 requests, 474 s.
- Identity, financials, leadership, locations, public activity: available for 100/100.
- Website: 13 verified, 39 withheld as ambiguous, 46 not available, 2 blocked by robots.txt. After the fixes, every published site is proven by
  org number (9), or by exact legal name plus phone/address on a matching or registry-declared domain (4).
- Social profiles: 5. Contact points: 45. Jobs: 0 in this sample, which has only 16 companies with any employees. The matcher was verified separately on two
  companies with live NAV ads; both got their ad matched by orgnr.

**Refresh run** (`smoke/out-refresh/`, same companies, the first run's state as baseline): 0 changes, so no false changes, and all 4,621 claims
unchanged. Offline tests also cover real change, removal, and stale-carry.

**Reproducibility**: fresh clone at the pinned commit, empty venv, `pip install -r requirements.txt`, run command → 3/3 envelopes (including
one deliberately invalid input) and all offline tests pass (34 in the current suite).

## 6. Plan checklist status

### Done
- Read the official contract, schema, permitted sources and starter kit before building.
- Registry-anchored identity: the org number must match exactly, with a snapshot fallback.
- Official financials with reporting periods and currency, never zero-filled; roles; workplaces; dated official changes.
- A bounded official-website crawl with an evidence-based identity gate and explicit `ambiguous`/`not_available` states.
- Jobs collector (NAV, orgnr-verified) and company-site news/JobPosting extraction.
- A fact/evidence model with source, retrieval time, content hash, span, period and method on every claim.
- Idempotent refresh, typed changes, preserved previous evidence, stale carry on failure, append-only history.
- Central request budget and deadline enforcement, per-host concurrency, robots.txt, SSRF guard, size and time limits.
- One envelope per input, six states, per-company exception boundary, atomic writes.
- Data minimisation (no birth dates, no sole-trader phones, generic mailboxes only), no secrets needed, no LLM (so no prompt-injection exposure).
- Tests: identity resolution, sparse profiles, financial absence, security (SSRF), updates, output contract; clean-clone reproducibility.
- 100-company smoke test plus refresh run; README, sources and licences, security, models/APIs and costs, submission template, this walkthrough.

### Partly done / deviations from the plan
- **Storage**: JSON state files plus a JSONL history instead of SQLite. Same guarantees (baseline, history, idempotency), fewer moving parts.
- **Source registry**: documented as a table in `SOURCES_AND_SECURITY.md` and enforced in code (fixed connectors, robots.txt), rather than a runtime `sources.yaml` gate.
- **Rate-limit handling**: a single retry with backoff on 429/5xx and fixed per-host concurrency. No circuit breaker.
- **Security tests**: covered by unit tests: SSRF (private, loopback, metadata, non-standard ports), redirects to blocked targets, DNS rebinding, credential stripping on cross-origin redirects, bounded redirect chains, NAV pagination host pin, oversized responses, deadline reserve and cost ceiling. Not covered: a live end-to-end test against a hostile server (the network tests use stand-ins).
- **Metrics**: requests, latency, runtime and cost are reported. "Verified facts per request per source" isn't computed separately.

### Not done
- **1,000-company local test** (10 × 100-company verification runs were done instead; see TEST_REPORT.md) (the plan said "if time permits"). Note that at about 8.7 requests per company, a 1,000-company batch would hit the 2,000-request cap.
  The agent would then return all 1,000 envelopes, with the later phases (jobs/website) marked `blocked` for companies the budget didn't reach. That behaviour is designed but hasn't been measured at that scale.
- External news, Doffin tenders, Proffi enrichment and LLM-assisted extraction: left out deliberately (rights, precision risk, or cost). Listed under limitations.
- Account PDFs (annual-report parsing) aren't parsed.
- **Pushing to GitHub, registering on Unstop, and emailing submit@builderr.ai**: these need your accounts. Fill in `SUBMISSION.md` with the repository URL and the
  final commit hash.

## 7. Where recall could improve next
1. Brand-name websites: most `ambiguous` and `not_available` sites are brand names or `.com` sites that lack an org number. A licensed search API
   (Brave, already wired in, off by default) plus the same gate would add candidates without adding risk.
2. Companies with an orgnr but a different brand on NAV ads are already used as declared website candidates; extending the feed window gives more of them.
3. More dated activity: RSS/Atom feeds and sitemaps on verified sites.
