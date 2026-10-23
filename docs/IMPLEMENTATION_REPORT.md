# Signalpost Agent: Implementation Report

Evidence-backed research of Norwegian companies from an organisation number

| | |
|---|---|
| Challenge | Signalpost (Builderr): build an agent that finds company information |
| Agent code version | commit `70cfcf091640d4742684a036f988d08624d1d69d` (version 2.2, after Builderr's audit of version 1, a second review and the residual-risk review; all results in this report were produced at this commit) |
| Report date | 16 October 2026 |
| Code size | about 2,100 lines of agent code, 500 lines of tooling and an 840-line offline test suite in the repository; an 82-line run harness was used for validation |
| Third-party cost per run | $0.00 (no LLM, no paid API in the default configuration) |

## 1. Executive summary

The Signalpost agent takes a batch of Norwegian organisation numbers and returns exactly one evidence-backed profile per number. Each profile covers legal
identity, filed annual accounts, leadership, registered workplaces, a verified official website, company-linked social profiles, contact points, open
jobs and dated public activity.

Every published fact (a *claim*) carries its source URL, retrieval time, a SHA-256 hash of the response it came from, the exact supporting text,
and its reporting period where relevant. Each information family reports one of the six contract states (`available`, `not_available`, `blocked`,
`not_applicable`, `ambiguous`, `failed`). Each run is compared with the previous one, producing typed, evidence-preserving change records.

The design rests on one principle taken from the competition rules: **it is better to miss information than to publish it under the wrong company.**
The organisation number is the only identity anchor, and a website is published only when its ownership is proven.

**Headline results at the frozen commit:**

- 13 of 13 verification runs (1,302 company results) pass all 14 contract rule groups.
- 1,400 published financial values, re-fetched live from Regnskapsregisteret, match the official filing exactly (field, statement type, period, currency, value).
- 137 published websites and 113 social accounts, all audited by hand: zero wrong-company publications.
- A 100-company run uses about 820–890 of the 2,000-request budget and takes 7–8 minutes, against a 45-minute limit.
- The refresh is idempotent: rerunning on an unchanged snapshot produces zero changes.
- 56 offline regression tests pass, including the network-security boundary cases and the cases from Builderr's audit and both reviews.
- A deduplicated dataset of 1,000 company profiles (46,780 claims) is built from the verified runs.

## 2. The challenge and its requirements

The official sources were downloaded and read before any code was written: the challenge page, the evaluation contract, the participant brief, the
source policy, the agent playbook, the learning harness, the starter kit and the 411,160-company universe file. These requirements shaped the design:

| Requirement | Source | How the agent meets it |
|---|---|---|
| One terminal result per input company, in six distinct states | evaluation contract | per-company exception boundary; fallback envelope builder; `failed` envelopes for invalid input |
| A material wrong-company publication blocks qualification | challenge page, contract | organisation-number anchor; ownership-proof identity gate; `ambiguous` instead of guessing |
| Source, retrieval time and reporting period on every claim | contract | claim and evidence model (section 6) |
| Missing values never converted to zero | contract | absent fields stay absent; verified by a check in every run |
| Idempotent refresh that preserves earlier evidence | contract | content-hashed claim IDs; append-only history; stale carry on failure |
| 45 minutes, 2,000 outbound requests, $10 per run | Unstop listing | budgets enforced inside the HTTP client, not merely reported |
| Search results are candidates, never evidence | source policy | search (optional) only proposes domains; every site is re-fetched and verified |
| No scraping of LinkedIn, Meta, Indeed or Google result pages | source policy | only official APIs, company-owned sites and permitted feeds |
| Pinned dependencies and one run command on a clean machine | contract | `requirements.txt`; clean-clone check performed |
| Scoring: 50 recall/coverage, 30 precision/evidence, 12 synthesis, 8 UX | contract | breadth-first coverage, evidence model, cited summaries, HTML viewer |

## 3. Methodology

The work followed six principles.

1. **Contract first.** The scoring rules and output contract were read before the first line of code. Live probes of every candidate source came
   before integration. They caught that Brønnøysund's announcement pages are disallowed by `robots.txt`, and that NAV's vacancy feed exposes the
   employer's organisation number.
2. **Evidence first.** Facts are stored individually with provenance, never as one generated paragraph. The summary is assembled from verified
   claims, and every sentence cites the claim IDs it uses.
3. **Identity before enrichment.** The official registry record anchors every profile. External material is attached only when it can be tied
   back to that exact organisation number.
4. **Breadth before depth.** Each phase runs across the whole batch before the next starts, so every company gets the official baseline before
   optional enrichment spends the budget.
5. **Deterministic over generative.** Extraction and matching are rule-based and testable. No language model decides identity or produces facts,
   which removes hallucination and prompt-injection risk and keeps the run cost at zero.
6. **Verification-driven iteration.** A contract verifier, a multi-run test suite, manual identity audits and three external review rounds were
   used as a control loop. Each defect found became a regression test before the fix was accepted, and the full suite was rerun on the exact
   commit being submitted.

## 4. Architecture

The pipeline runs in seven breadth-first phases:

| Phase | What happens | Requests (100 companies) |
|---|---|---|
| 1. Identity | live Brønnøysund entity by exact organisation number; falls back to snapshot fields in the input row if the API fails | 100 |
| 2. Accounts | all filed periods from Regnskapsregisteret, company and group statements kept separate | 100 |
| 3. Roles | board, CEO, auditor and other registered roles | 100 |
| 4. Workplaces | registered subunits with addresses | 100 |
| 5. Change log | dated, field-level official register changes over 24 months | 100 |
| 6. Jobs | one shared walk of the NAV vacancy feed, then orgnr-verified matching | about 95 + candidates |
| 7. Website | candidate discovery, identity gate, extraction of company-owned facts | about 220–330 |

Modules:

| Module | Lines | Responsibility |
|---|---|---|
| `run.py` | 248 | command line, input parsing, phase orchestration, output writing, run report, source-yield metrics |
| `signalpost/http.py` | 298 | the only outbound HTTP path: budgets, deadline reserve, SSRF guard, IP pinning, hop-by-hop redirects, robots.txt |
| `signalpost/dossier.py` | 109 | per-company store of claims, evidence and section states |
| `signalpost/registry.py` | 268 | Brønnøysund collectors: entity, accounts, roles, subunits, change log |
| `signalpost/jobs.py` | 155 | NAV vacancy feed index and orgnr-verified job matching |
| `signalpost/website.py` | 786 | website discovery, identity gate, company-owned fact extraction |
| `signalpost/envelope.py` | 229 | envelope assembly, refresh comparison, cited synthesis |
| `signalpost/report.py` | 79 | self-contained HTML viewer |
| `tools/verify_run.py` | 201 | contract verifier (14 rule groups) with live financial spot-checks |
| `tools/purge.py` | 78 | erasure, correction and retention operations |
| `tools/verify_v2_fixes.py` | 179 | replays Builderr's audit cases; scans a dataset for the four audit problems |
| `tools/build_dataset.py` | 69 | deduplicated 1,000-profile dataset from verified runs |
| `tests/test_agent.py` | 835 | 56 offline regression tests |

## 5. Technology stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.10+ (developed and tested on 3.13.7) | standard for data work; runs on any evaluator machine |
| HTTP | Python standard library `urllib.request` and `http.client` with custom connection, redirect and proxy handlers | full control over every hop for budget and security; no heavy client dependency |
| Concurrency | `concurrent.futures.ThreadPoolExecutor` (16 workers) with per-host semaphores | I/O-bound workload; simple, no event loop |
| HTML parsing | `beautifulsoup4` 4.15.0 with the standard-library `html.parser` | robust on malformed HTML; no compiled parser dependency |
| Domain handling | `tldextract` 5.4.0 with its bundled public-suffix list (no network fetch) | correct registered-domain comparison (for example `.no` second-level domains) |
| Robots | standard-library `urllib.robotparser` | honours site access rules |
| Storage | JSON and JSONL files: `state/<org>.json`, `state/history/<org>.jsonl` | reproducible, inspectable, no database server |
| Viewer | one self-contained HTML file with inline vanilla JavaScript | opens offline on desktop and mobile; nothing to install |
| Tests | plain `assert` tests runnable directly or with pytest; network stand-ins | no test framework required on the evaluator machine |
| AI / LLM | none | no hallucination or prompt-injection risk, no model cost; identity decisions are deterministic |
| Optional search | Brave Search API, off unless `BRAVE_API_KEY` is set | candidate discovery only; cost-capped |
| Version control | git; exact commit recorded by the test harness | ties every result to the code that produced it |

All dependencies are pinned in `requirements.txt`. The transitive packages (`requests`, `urllib3`, `idna`, `certifi`, `filelock`, `requests-file`,
`soupsieve`, `charset-normalizer`, `typing_extensions`) are pulled in by `tldextract` and `beautifulsoup4`; the agent calls none of them directly.

## 6. Data sources

| Source | Access | Used for | Licence / terms | Identity link |
|---|---|---|---|---|
| Brønnøysund Enhetsregisteret entity API | open REST API | legal identity, form, status, addresses, industry, employees, founding date, registry website and phone, capital, historical names | NLOD 2.0 | response must echo the requested organisation number |
| Regnskapsregisteret accounts API | open REST API (described by Brønnøysund as a temporary "preview" service) | revenue, operating result, profit before tax, net result, assets, equity, debt, payroll, audit flags, per period and statement | NLOD 2.0 | exact organisation number |
| Enhetsregisteret roles API | open REST API | registered roles | NLOD 2.0 | exact organisation number |
| Enhetsregisteret subunits API | open REST API | registered workplaces | NLOD 2.0 | parent organisation number |
| Enhetsregisteret updates API | open REST API (`includeChanges=true`) | dated, field-level official changes | NLOD 2.0 | exact organisation number |
| NAV Arbeidsplassen vacancy feed | official feed; public token fetched at run time | active job postings | NAV public feed terms | `employer.orgnr` equals the company or one of its subunits |
| Company-owned websites | plain HTTP GET, robots.txt honoured | website, description, brand, company-named social links, contact points, dated news posts, JobPosting markup naming the company | company-published content; only short spans stored | identity gate (section 8) |
| Brave Search API (optional, off by default) | licensed API | candidate domains only; never evidence | Brave API terms | candidate must pass the identity gate |

**Deliberately not used:** LinkedIn, Meta, Glassdoor and Indeed scraping; Google or Bing result pages; Proff, Purehelp and 1881 page scraping; Brønnøysund
announcement pages (disallowed by robots.txt); and authorised role endpoints that expose national identity numbers.

## 7. Fact, evidence and envelope model

**Evidence record:** source URL, requested URL, source class, retrieval time (UTC), HTTP status, SHA-256 of the response body, a claim span (the
exact field and value, or a text excerpt) and the extraction method.

**Claim:** field, section, value, evidence IDs, confidence, reporting period, effective date, first and last observed times, and extraction method.
The `claim_key` is the stable identity of a fact (for example `revenue|selskap|2025-12-31` or `job|<uuid>`), and `claim_id = hash(org, key, value)`.
The same fact therefore always gets the same ID, which is what makes the refresh idempotent.

**Envelope** (one per input): schema version, organisation number, envelope state, run metadata, legal identity, public brand, nine section states
with reasons, a cited summary, claims, evidence, source snapshots, refresh metadata, typed changes, errors and per-company operations.

| State | Meaning in this agent |
|---|---|
| `available` | found, with evidence |
| `not_available` | the source was checked and has nothing |
| `blocked` | the source refused (robots.txt, HTTP 403/429), or the run's budget or deadline was reached before it was queried |
| `not_applicable` | does not apply (for example a filing-exempt legal form) |
| `ambiguous` | a candidate exists but its identity is unproven, so nothing is published |
| `failed` | a processing or transient error for this company (for example a verified site timing out) |

## 8. Identity verification

Wrong-company publication is the one failure that disqualifies an entry, so this is the most heavily tested component.

**Website candidates**, in order of trust:
1. The website registered in Brønnøysund.
2. The employer homepage from a NAV ad whose orgnr is the company.
3. The domain of a NAV contact e-mail (discovery only; it may be a recruiter's).
4. Domains derived from the legal name, checked by DNS before any HTTP request.
5. Optional search results.

At most six domains are tried per company.

**Identity gate, in priority order:**

1. The organisation number counts as proof (score 1.0) only when the domain's ownership is shown:
   - either the company **declared** the site to an official source (Brønnøysund `hjemmeside`, or the employer homepage of an orgnr-matched NAV ad),
   - or the number sits in the site's **own identity block**: footer or address element, a contact or about page, or its JSON-LD Organization.
2. A different labelled organisation number or VAT ID on the site → **rejected**: a parent, sister or unrelated entity.
3. The company's number listed among other companies' numbers (a group, chain or portfolio page) → **ambiguous**, unless the company declared
   that site to an official source and its domain matches the company's name.
4. A parked, for-sale or placeholder page → **rejected**.
5. The exact legal name, with the legal-form suffix in capitals, plus the registry's own phone number or street address and postcode, on a
   name-matching or declared domain → exact (0.97).
6. A declared site whose page carries the company's exact legal name, or its brand name plus the registry's own phone or address → exact (0.92).
   A brand title alone is not enough (a declared domain can be a group or brand site), and neither is a matching phone number alone.
7. Anything weaker → **ambiguous**, recorded with the candidates checked, and nothing published.

Additional safeguards:
- A domain that merely matches the company name proves nothing, because same-name companies exist.
- A NAV contact e-mail domain is never treated as declared.
- A declared candidate that redirects to a different registered domain loses its declared status.
- Social profiles are published only when linked from the verified site and the handle is the company's name: every distinctive word must be in
  it and anything left over may only be a harmless affix (`as`, `no`, `norge`), another legal-name word or a page ID, so sister, parent,
  subsidiary, group and other-company accounts that share a word are rejected; platform paths and opaque channel IDs are rejected.
  The company must also present the account as its own: site chrome, its contact or about page, repeated on two or more of its pages, or
  the `sameAs` of its own structured-data record. A link inside an article or another organisation's markup is withheld.
- When the company's site is a section of a larger site (for example `dnt.no/nordtrondelag`), the URL is published but no social accounts, news
  or jobs are taken from that domain.
- A subsidiary can be declared with its parent's root domain, where no path shows the difference. Site content (description, brand, social
  accounts, contacts, news, jobs) is taken only when the site is shown to be the company's own: the domain matches the company name, the org
  number or exact legal name is in the site's own footer/address block with no other organisation's number, or the site's structured data
  is this company. Otherwise only the URL is published, with the reason.

**Real wrong-company cases found during testing and closed:**

| Company | What went wrong | Fix |
|---|---|---|
| ASTRA HOLDING AS (Osterøy) | matched a British "Astra Holding" site: the English word "as" satisfied the "AS" suffix | legal-form suffix must appear in capitals |
| VESTGÅRD INVEST AS | matched a related company's registry-declared site through a shared phone number | declared sites need the entity's own name |
| SHARK AS (Sandefjord, freight) | matched `shark.no`, which belongs to a different "Shark AS" (Kolbotn, property) | name-only rule removed |
| NORLANDIA RATVIKA BARNEHAGE AS | matched the chain homepage, whose script data listed every member kindergarten's number | hidden-markup and listing pages are ambiguous |

Three further latent cases were raised by external review and closed with tests:
- a third-party article that mentions the number;
- a name-matching domain where the number appears only in an article;
- a recruiter's e-mail domain.

## 9. Other components

**Financials.** Every filed period is published, with company (`selskap`) and group (`konsern`) statements kept separate. Each value carries its period and currency. A field
missing from the filing stays absent and is never zero-filled. A 404 for filing-exempt forms is `not_applicable`.

**Jobs.** The NAV feed is walked once per run from `If-Modified-Since = now − 45 days`: about 95 pages and 30,000 entries, shared by the whole batch. Candidates
match the legal name, a subunit name or a department-style name. Each candidate ad is re-fetched and published only if `employer.orgnr` is the company or one of
its subunits. If the ad carries no orgnr, the employer name must equal the registered legal name exactly.

**Company-owned facts.** From a verified site the agent extracts:
- the description (meta tag or first substantive paragraph, labelled as company copy) and the brand name;
- linked social profiles whose handle is the company's name (see section 8);
- generic mailboxes on the company's own domain and phone numbers from `tel:` links;
- dated news posts: the JSON-LD article node's own `datePublished`, or a `<time>` on the news page only when its container holds exactly one
  date and links to exactly one article; dates must be plausible and never "modified"/"updated". Contact, product and shop pages, menu
  labels and demo posts are rejected. A generic `Article` needs a post-like URL; explicit news types and structured list entries may use any URL;
- current (unexpired) JobPosting markup whose employer carries this org number or the exact legal name including the legal form (a similar
  name, another legal form or another org number is rejected). Careers landing pages are not published.

**Refresh.** Unchanged claims keep their first-observed time.
- **Changed values** produce typed changes (for example `changed_registered_employees`, `changed_description`), with the previous evidence embedded.
- **New facts** produce `new_job`, `new_role`, `new_location` or `new_filing`.
- **Disappearances** produce `closed_job`, `removed_role` and similar, but only where disappearing is meaningful. Dated feeds simply roll out of their window.
- **Source unavailable:** if the source is blocked or failed, the last value is kept and flagged `stale` instead of being deleted. Site facts follow the
  website's own state, so an HTTP 429 never deletes them.

**Synthesis.** A deterministic template builds the headline and summary points from published claims, each citing its claim IDs. It covers identity, what
the company does, employees, the latest accounts with a labelled calculated revenue change, leadership, workplaces, the verified website, hiring and recent
activity. It is followed by the changes since the previous run and an explicit list of unknowns (every non-available section with its state and reason).

**User experience.** `report.html` is a single self-contained file. It offers search by name, organisation number or municipality; filters (verified website,
hiring, social profiles, changed, ambiguous); and colour indicators for the nine sections. A detail view shows key figures, the cited summary, changes,
unknowns, and every claim with an expandable evidence span, source link and retrieval time. It switches to a single-column layout on mobile, supports dark
mode, and HTML-escapes all source values.

## 10. Security

| Risk | Handling |
|---|---|
| Server-side request forgery (SSRF) | only `http`/`https` on ports 80 and 443; localhost and `.local`/`.internal` names rejected; every resolved address must be globally routable (loopback, private, link-local and cloud-metadata ranges blocked) |
| DNS rebinding | custom connection classes resolve once, validate every address, and connect to that exact IP; TLS still verifies the real hostname (SNI); environment proxies are ignored |
| Unsafe redirects | redirects are followed by the client hop by hop (at most 5), never silently by urllib; every hop is re-validated, robots-checked where applicable, counted against the budget and limited by the destination host's concurrency |
| Credential leakage | `Authorization`, `Cookie`, `X-Subscription-Token` and `X-API-Key` are dropped on any change of origin (scheme, host or port); NAV pagination and entry URLs must be `https://pam-stilling-feed.nav.no` on the default port with no embedded credentials, otherwise the walk stops |
| Malicious or oversized content | 2 MB per page (8 MB per feed page); 15-second timeouts; HTML only for site pages; scripts are stripped and never executed |
| Prompt injection | no LLM in the loop; page text is data, matched only by deterministic rules (tested with an instruction-bearing page) |
| Secrets | none required; the optional `BRAVE_API_KEY` and `NAV_FEED_TOKEN` are read only from environment variables and never logged or written to output |
| Runaway runs | `--max-requests` (default 2000) and `--deadline-minutes` (default 42) are enforced inside the client; the final 90 seconds are reserved for writing output, and no request may start in that window |
| Runaway spend | `--max-cost-usd` (default 10): a paid call reserves its cost before the request and is refused if it would cross the ceiling |
| Politeness | at most 6 concurrent requests to brreg.no and 2 to any other host; robots.txt honoured; identifying User-Agent |

## 11. Privacy and data protection

This section is an engineering description, not a legal opinion.

| Topic | Practice |
|---|---|
| Purpose | company research; personal data appears only as part of company facts |
| Data published | names and roles of registered role holders, as in the public register; NAV ad titles and locations |
| Data minimisation | birth dates discarded on fetch; no national ID numbers; no sole-trader phone numbers; only generic company mailboxes on the company's own domain |
| Legal basis (assumed) | legitimate interest in company due diligence, for data the law requires to be public. NLOD 2.0 covers reuse of the dataset but does not by itself grant a basis for processing personal data |
| Not done | no profiles of individuals, no cross-company linking of persons, no sensitive inference, no personal data sent to third parties |
| Retention | `state/` keeps the latest snapshot; the append-only history is pruned with `tools/purge.py --older-than-days 365` |
| Erasure and objection | `tools/purge.py --person "Name"` removes a person's claims, evidence and change records from state and history, and adds them to a suppression list that later runs honour, so the public register cannot re-add them; `--org` removes a company's baseline and history |

## 12. Testing methodology

Testing used five layers.

**1. Offline regression tests (56).** These cover the identity gate (19), discovery and extraction (19), network security (9), budgets and states (4),
refresh (3), and input and data rules (2), as listed in Appendix A. Network tests use stand-ins for DNS and HTTP, so they run anywhere without network access. The test that guards
credential stripping was mutation-checked: disabling the protection makes it fail.

**2. Contract verifier.** `tools/verify_run.py` checks every envelope of a run against 14 rule groups:

| ID | Rule | Check |
|---|---|---|
| R1 | one result per company | count equals input rows; no duplicates; same organisation-number set; viewer present |
| R2 | complete envelope | all required keys, including in failed envelopes |
| R3 | valid states | envelope and all nine sections have a valid state and a reason |
| R4 | evidence | every claim's evidence resolves; evidence has URL, timestamp, hash and span |
| R5 | honest states | no published claim under a section that is not available (stale carry excepted) |
| R6 | financial periods | every financial claim has a period, currency and numeric amount |
| R7 | exact company | jobs carry orgnr proof; websites carry a method and a score of at least 0.9 |
| R8 | cited synthesis | every summary sentence cites existing claims |
| R9 | identity anchored | every available envelope has a legal-name claim |
| R10 | personal data | no birth dates; no sole-trader phone numbers |
| R11 | refresh provenance | every changed claim carries its old evidence |
| R12 | limits | requests, runtime and cost within the run's limits |
| R14 | Builderr audit rules | social handles name the company; news items are dated posts; no careers landing pages; NAV jobs link to a single ad; no claim from a site not shown to be the company's own |
| R13 | no fabricated financials | 5 companies per run re-fetched live; each value must equal the live record for the same field, statement, period end and currency (a 1 NOK corruption is detected) |

**3. Thirteen-run suite.** Thirteen batches of 100 companies each, chosen to stress different rules:

| Run | Scenario |
|---|---|
| R01 | random 100, JSONL universe rows |
| R02 | random 100, plain-text input |
| R03 | random 100, JSON list input |
| R04 | random 100, gzipped JSONL |
| R05 | random 100 plus 2 duplicate rows and 2 invalid numbers |
| R06 | 100 companies with at least 5 employees (website and jobs stress) |
| R07 | DIPS, Equinor, two hiring companies, and 96 companies with a registered website |
| R08 | budget stress: `--max-requests 300` |
| R09 | deadline stress: `--deadline-minutes 3` |
| R10 | refresh of R01 against R01's output (idempotency and change detection) |
| R11–R13 | 300 random companies not used in any earlier run |

**4. Manual identity audit.** After every suite, all published websites were listed by proof type and inspected by hand. This audit found the SHARK AS and
NORLANDIA cases, which no automated rule had flagged.

**5. External review and Builderr's audit.** Four independent review rounds of the source code were checked finding by finding, with each claim reproduced before fixing.
They led to the IP pinning, hop-by-hop redirects, credential stripping, HTTPS pinning for NAV, the ownership-proof rule, the stricter financial verifier,
the enforced cost cap and the input-parsing fixes.

A clean-clone check (new folder, empty virtual environment, only the declared install step, then the run command) was also performed.

## 13. Results at the frozen commit

| Run | Envelopes | Claims | Websites | Jobs | Requests | Runtime | Result |
|---|---|---|---|---|---|---|---|
| R01 | 100 | 4,367 | 8 | 0 | 827 | 473 s | pass |
| R02 | 100 | 4,561 | 7 | 1 | 890 | 417 s | pass |
| R03 | 100 | 4,410 | 8 | 0 | 862 | 444 s | pass |
| R04 | 100 | 4,539 | 11 | 0 | 812 | 414 s | pass |
| R05 | 102 | 4,490 | 12 | 2 | 883 | 410 s | pass (2 invalid inputs get failed envelopes) |
| R06 | 100 | 5,498 | 32 | 1 | 917 | 516 s | pass |
| R07 | 100 | 5,487 | 40 | 4 | 1,046 | 428 s | pass |
| R08 | 100 | 4,189 | 0 | 0 | 300 | 41 s | pass (cap held exactly; 300 sections blocked with reason) |
| R09 | 100 | 4,305 | 0 | 0 | 525 | 136 s | pass (finished within the 180 s limit) |
| R10 | 100 | 4,367 | 8 | 0 | 829 | 477 s | pass (0 false changes) |
| R11 | 100 | 4,451 | 5 | 0 | 877 | 424 s | pass |
| R12 | 100 | 4,581 | 7 | 0 | 895 | 472 s | pass |
| R13 | 100 | 4,396 | 7 | 0 | 815 | 456 s | pass |

Coverage per section across the seven random batches, as the number of companies (out of 100) with `available`:

| Section | Range |
|---|---|
| Identity | 100 |
| Financials | 99–100 |
| Leadership | 99–100 |
| Locations | 98–100 |
| Public activity | 100 |
| Contact | 28–39 |
| Website | 5–11 |
| Social profiles | 2–4 |
| Jobs | 0–1 |

On employer-heavy and website-heavy batches, website coverage rises to 31–40 per 100.

**Source yield** (smoke run): Brønnøysund 501 requests → 4,339 claims; company websites 233 requests → 28 claims; NAV feed 93 requests → 0 claims in that batch.

**Identity audit:** 137 unique websites were published across the suite:
- 31 with the organisation number on sites the company declared to an official source;
- 36 with the number in the site's own identity block;
- 55 with the exact legal name plus the registry's own phone or address;
- 7 declared sites carrying the exact legal name;
- 8 declared sites carrying the brand name plus the registry's own phone or address.

Site ownership: 129 are shown to be the company's own site; 8 are published as URL only (one, `vif-fotball.no`, is shared by two registry
entities). All 113 published social accounts were also checked by hand: each is the company's exact name, optionally with `as`, `no`, `norge`,
a country word or a page number, and each is presented by the company itself.

None is a wrong-company match.

**Dataset:** `profiles/profiles.jsonl.gz` holds 1,000 unique companies (46,780 claims and as many evidence records), merged only from runs that passed verification.
The manifest records the commit and the content SHA-256. The agent never reads this dataset when researching a batch.

## 14. Defects found and fixed

| # | Defect | Severity | Found by |
|---|---|---|---|
| 1–4 | four real wrong-company matches (Astra, Vestgård, Shark, Norlandia) | disqualifying | smoke and suite audits |
| 5–7 | latent wrong-company paths: third-party mention, name-matching domain, recruiter e-mail domain, redirect trust and undeclared group pages | disqualifying (latent) | external review |
| 8 | credentials forwarded on cross-host redirects | security | external review |
| 9 | NAV token could leave the feed host or travel over plain HTTP | security | external review |
| 10 | DNS-rebinding window between check and connect | security | external review |
| 11 | redirect hops bypassed the budget and per-host limits | contract | external review |
| 12 | pretty-printed JSON or a single-number input crashed the run with zero output | contract (whole batch) | external review and own retest |
| 13 | deadline run took 183 s on a 180 s limit | contract | external review |
| 14 | financial verifier matched numbers anywhere in the response | test rigour | external review |
| 15 | cost ceiling only reported, not enforced | contract | external review |
| 16 | HTTP 429 caused a false removal; refusals mislabelled | false change / state | refresh run and audits |
| 17 | inconsistent section states, incomplete fallback envelopes, junk news, mislabelled fallback evidence | contract / quality | verifier |
| 18 | brand-only proof for declared group/brand sites; parent-domain socials, news and jobs; brand-named social handles; contact pages and demo posts as news; careers landing pages as jobs | wrong company (facts) | **Builderr audit of version 1** |
| 19 | social handles shared by sister/parent/subsidiary/group accounts; a date shared by several articles pinned to the first; similar employer names accepted for website jobs | wrong company (facts) | **second review of version 2.0** |
| 20 | a subsidiary declared with its parent's root domain got the parent's site content; full-name social links in article text or another organisation's structured data were published | wrong company (facts) | **residual-risk review of version 2.1** |

Every defect has a regression test or a dedicated suite run.

## 15. Limitations and future work

- **Site facts are withheld for 8 of 137 published websites** whose footer shows neither the org number nor the exact legal name. One is a
  genuinely shared club site; most of the others are probably the company's own. Withholding is the safer error.
- **Website coverage (5–11 % on random batches)** is the price of publishing only proven matches. Most unpublished candidates are brand names, sites
  without an org number in an identity block, or redirecting domains. The optional search connector is the next lever, but it needs a key the evaluator
  can reproduce and an A/B test before use.
- **Job coverage is low (0–2 per 100).** Most random companies have no NAV ad in a 45-day window, and only about 1,250 of 5,600 employer names carry a
  legal suffix. The matcher is precise (orgnr-verified) and works on hiring companies.
- **The accounts API is a preview service** without service guarantees. Outages are reported honestly, but a fallback such as filed PDF copies is not implemented.
- **One batch of 1,000 companies under a 2,000-request cap** would exhaust the budget at about 8.7 requests per company. The agent still returns every
  envelope with the registry baseline and marks later sources `blocked`, as the budget stress run demonstrates.
- **Network-security tests use stand-ins** rather than a live hostile server.

## 16. Reproduction and submission

Version 2 changes are documented before/after, with the old and new code and verification steps, in `CHANGES_V2.md`. To check them:

```bash
python tools/verify_v2_fixes.py
python tools/verify_v2_fixes.py --dataset profiles/profiles.jsonl.gz
```

Expected: 29/29 audit cases pass, and 0 audit problems in the current dataset (version 1's dataset shows 89 and version 2.0's 38 under the current rules).


Install and run (Linux/macOS):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py --input companies.jsonl --output out
```

Windows:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py --input companies.jsonl --output out
```

Checking a run's output against the contract (the verifier is included in the repository):

```bash
python tools/verify_run.py --input companies.jsonl --output out
```

Offline tests (included in the repository):

```bash
python tests/test_agent.py
```

The 13-run test harness was used for validation and is kept outside the submitted repository; its results are reported in sections 12 and 13 and in `TEST_REPORT.md`.

**What gets submitted:** the git repository (agent code, docs, the smoke test with its refresh run, the 1,000-profile dataset, the offline tests and the
tools, including the contract verifier). The run harness, raw run outputs, the local virtual environment and development scratch files are excluded. The agent code (version 2) is at `70cfcf0`;
later commits change documentation and data only.

## Appendix A: Offline test inventory

These tests are in `tests/test_agent.py` and were run against the frozen code.

| Area | Tests |
|---|---|
| Identity gate | `test_orgnr_on_page_is_exact`, `test_conflicting_orgnr_rejected_even_with_name`, `test_parked_domain_rejected`, `test_name_only_on_unrelated_domain_is_not_published`, `test_name_plus_phone_is_exact`, `test_brand_without_corroboration_on_guessed_domain_is_ambiguous`, `test_english_as_does_not_satisfy_legal_suffix`, `test_same_name_other_company_on_matching_domain_is_not_exact`, `test_shared_phone_on_registry_site_is_not_exact`, `test_orgnr_on_group_listing_page_is_ambiguous`, `test_orgnr_only_in_hidden_chain_data_is_not_exact`, `test_orgnr_validity`, `test_orgnr_on_third_party_page_is_not_official_website`, `test_orgnr_in_own_footer_on_brand_domain_is_exact`, `test_name_matching_domain_with_orgnr_only_in_article_is_ambiguous`, `test_recruiter_email_domain_is_not_declared_website`, `test_group_page_on_undeclared_name_matching_domain_is_ambiguous`, `test_group_page_declared_by_the_company_on_its_name_domain_is_exact`, `test_declared_brand_site_needs_org_number_or_exact_name` |
| Discovery and extraction | `test_declared_site_redirecting_to_other_domain_loses_trust`, `test_domain_guesses_skip_generic_names`, `test_social_normalisation_rejects_share_links`, `test_site_pages_are_not_news`, `test_section_of_larger_site_detection`, `test_section_site_publishes_no_parent_socials_news_or_jobs`, `test_social_handle_must_name_the_company`, `test_news_must_be_a_real_dated_post`, `test_modified_dates_are_not_publish_dates`, `test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs`, `test_website_job_needs_exact_employer_not_a_similar_name`, `test_nav_job_with_similar_employer_name_is_not_published`, `test_news_date_must_belong_to_one_article`, `test_explicit_news_types_accept_unusual_urls_but_generic_articles_do_not`, `test_subsidiary_declared_with_parent_root_domain_gets_no_parent_facts`, `test_subsidiarys_own_root_site_keeps_its_facts`, `test_footer_listing_several_companies_does_not_prove_site_owner`, `test_social_account_must_be_attributable_not_just_name_matching`, `test_social_link_repeated_across_site_pages_counts_as_site_chrome` |
| Network security | `test_ssrf_guard`, `test_redirect_to_loopback_metadata_or_private_host_blocked`, `test_credentials_never_cross_origin_on_redirect`, `test_nav_pagination_https_downgrade_rejected`, `test_redirect_chain_is_bounded`, `test_nav_pagination_never_leaves_feed_host`, `test_dns_rebinding_cannot_reach_private_address`, `test_oversized_response_not_accepted`, `test_page_text_is_data_not_instructions` |
| Budgets and states | `test_deadline_reserve_blocks_new_requests`, `test_cost_ceiling_enforced_before_paid_call`, `test_site_refusing_requests_is_blocked_not_absent`, `test_unrelated_dotcom_bot_wall_is_not_reported_as_blocked` |
| Refresh | `test_refresh_idempotent_change_and_stale_carry`, `test_rate_limited_site_keeps_site_facts_stale_not_removed`, `test_registry_change_summary_drops_housekeeping` |
| Input and data rules | `test_input_formats`, `test_missing_financials_never_zero` |
