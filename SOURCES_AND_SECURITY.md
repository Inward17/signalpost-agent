# Sources, rights, identity gates and security

## Source registry

| Source | Access method | Used for | Licence / terms | Identity link | Requests |
|---|---|---|---|---|---|
| Brønnøysund Enhetsregisteret `api/enheter/{org}` | Open REST API, no key | Legal identity, form, status, addresses, industry, employees, founding date, registry website, phone, capital, historical names | [NLOD 2.0](https://data.norge.no/nlod/en/2.0) — attribution kept in every evidence record | Exact organisation number (response must echo it) | 1 / company |
| Regnskapsregisteret `regnskap/{org}` | Open REST API | Filed annual accounts: revenue, operating result, profit before tax, net result, assets, equity, debt, payroll, audit flags — per reporting period, currency and company/group statement | NLOD 2.0 | Exact organisation number | 1 / company |
| Enhetsregisteret `enheter/{org}/roller` | Open REST API | Board, CEO, auditor and other registered roles | NLOD 2.0 | Exact organisation number | 1 / company |
| Enhetsregisteret `underenheter?overordnetEnhet={org}` | Open REST API | Registered workplaces (subunits) and their addresses | NLOD 2.0 | Parent organisation number | 1 / company |
| Enhetsregisteret `oppdateringer/enheter?organisasjonsnummer={org}&includeChanges=true` | Open REST API | Dated official change log (address, name, website, employees, filings, …) | NLOD 2.0 | Exact organisation number | 1 / company |
| NAV Arbeidsplassen job-vacancy feed `pam-stilling-feed.nav.no` | Official public feed, public token from `/api/publicToken` (or `NAV_FEED_TOKEN`) | Active job postings | NAV public feed terms; ads are public job advertisements | `employer.orgnr` must equal the company or one of its registered subunits; without orgnr only an exact registered-legal-name match is accepted | ~100 shared pages per run + 1 per candidate ad |
| Company-owned website | Plain HTTP GET, robots.txt honoured, ≤ ~8 pages per site | Official website, description, brand, company-linked social profiles, generic contact points, dated news, careers page, JobPosting markup | Company-published content; only short spans are stored as evidence | See identity gate below | ≤ 8 / candidate |
| DNS | System resolver | Checks whether a name-derived domain exists before any HTTP request | — | Candidate generation only | not HTTP |
| Brave Search API (optional, off unless `BRAVE_API_KEY` is set) | Licensed API | Candidate domains only — results are never evidence and are not stored | Brave API terms | Candidate must pass the same identity gate | 1 / company |

Not used: LinkedIn/Meta/Glassdoor/Indeed scraping, Google/Bing result pages, Proff/Purehelp/1881 page scraping,
Brønnøysund `w2.brreg.no/kunngjoring` pages (disallowed by robots.txt — the agent detects this and reports `blocked`),
authorised role endpoints exposing national identity numbers.

## Identity gate (wrong-company prevention)

The organisation number is the only identity anchor. Every website candidate (registry `hjemmeside`, NAV employer homepage
or contact-email domain for an orgnr-matched ad, name-derived domain, optional search candidate) is fetched and assessed:

1. **Exact (score 1.0)** — the organisation number (any of `810034882`, `810 034 882`, `810.034.882`, `NO 810 034 882 MVA`) appears on the homepage, contact or about page — unless that page also lists other organisation numbers on a non-matching domain (group/portfolio page → `ambiguous`).
2. **Rejected** — the site states a *different* labelled organisation number / VAT id → parent, sister, franchise or unrelated entity. This overrides every name signal.
3. **Rejected** — parked / for-sale / placeholder page.
4. **Exact (0.97)** — full registered legal name (legal-form suffix in capitals) *and* the registry phone number or registered street address + postcode appear on the site, on a name-matching or officially declared domain.
5. **Exact (0.92)** — the site was declared by an official source (registry `hjemmeside`, or NAV ad whose `employer.orgnr` equals the company) *and* the legal or brand name appears on the page. A matching phone alone is not enough (shared phones point to related companies).
6. Anything else with a name hit → `ambiguous`, recorded with the reason, **not published**.

Social profiles are published only when linked from the verified site *and* the handle matches the legal name/domain or the profile
is listed in the site's own JSON-LD `sameAs`. Unmatched outbound links are counted but withheld (e.g. a franchise linking to the chain).

## Personal data

Registered role holders' names and roles are published as in the public register; birth dates are discarded. Sole-trader (ENK)
phone numbers are not published. Website e-mail addresses are only kept for generic company mailboxes on the company's own domain
(`post@`, `info@`, `kontakt@` …). No personal profiles, no sensitive inference. No personal data is sent to any third-party model (none is used).

## Security

- **Single HTTP path** (`signalpost/http.py`): every request passes the budget/deadline check, the SSRF guard and size limits.
- **SSRF guard**: only `http(s)` on ports 80/443; hostnames must resolve exclusively to globally-routable IPs (loopback, RFC1918, link-local,
  metadata addresses blocked); every redirect hop is re-validated; max 5 redirects.
- **Response limits**: 2 MB per page (8 MB per NAV feed page), 15 s timeout, HTML only for site pages; scripts are never executed (static parsing).
- **Prompt injection**: there is no LLM in the loop; fetched text is data, matched only by deterministic rules.
- **Secrets**: none required. Optional `BRAVE_API_KEY` / `NAV_FEED_TOKEN` are read from environment variables only and never logged or written to output.
- **Budgets enforced, not reported**: `--max-requests` (default 2000) and `--deadline-minutes` (default 42 of the 45 allowed). When either runs
  out, remaining sources are marked `blocked` with the reason and the run still writes one envelope per company.
- **Politeness**: ≤ 6 concurrent requests to brreg.no, ≤ 2 per other host, robots.txt honoured for all non-API pages, identifying User-Agent.

A name alone is never enough, even an exact "Name AS" on a domain equal to the name: verification runs found
`shark.no` showing "Shark AS" (a Kolbotn property firm) while the requested SHARK AS is a Sandefjord freight company.
