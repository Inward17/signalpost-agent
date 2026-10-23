# Sources, rights, identity gates and security

## Source registry

| Source | Access method | Used for | Licence / terms | Identity link | Requests |
|---|---|---|---|---|---|
| Brønnøysund Enhetsregisteret `api/enheter/{org}` | Open REST API, no key | Legal identity, form, status, addresses, industry, employees, founding date, registry website, phone, capital, historical names | [NLOD 2.0](https://data.norge.no/nlod/en/2.0) — attribution kept in every evidence record | Exact organisation number (response must echo it) | 1 / company |
| Regnskapsregisteret `regnskap/{org}` | Open REST API, described by Brønnøysund as a temporary "preview" research API without service guarantees; outages are reported as `blocked`/`failed`, never as missing figures | Filed annual accounts: revenue, operating result, profit before tax, net result, assets, equity, debt, payroll, audit flags — per reporting period, currency and company/group statement | NLOD 2.0 | Exact organisation number | 1 / company |
| Enhetsregisteret `enheter/{org}/roller` | Open REST API | Board, CEO, auditor and other registered roles | NLOD 2.0 | Exact organisation number | 1 / company |
| Enhetsregisteret `underenheter?overordnetEnhet={org}` | Open REST API | Registered workplaces (subunits) and their addresses | NLOD 2.0 | Parent organisation number | 1 / company |
| Enhetsregisteret `oppdateringer/enheter?organisasjonsnummer={org}&includeChanges=true` | Open REST API | Dated official change log (address, name, website, employees, filings, …) | NLOD 2.0 | Exact organisation number | 1 / company |
| NAV Arbeidsplassen job-vacancy feed `pam-stilling-feed.nav.no` | Official public feed, public token from `/api/publicToken` (or `NAV_FEED_TOKEN`) | Active job postings | NAV public feed terms; ads are public job advertisements | `employer.orgnr` must equal the company or one of its registered subunits; without orgnr only an exact registered-legal-name match is accepted | ~100 shared pages per run + 1 per candidate ad |
| Company-owned website | Plain HTTP GET, robots.txt honoured, ≤ ~8 pages per site | Official website, description, brand, company-linked social profiles, generic contact points, dated news posts, JobPosting markup naming the company | Company-published content; only short spans are stored as evidence | See identity gate below | ≤ 8 / candidate |
| DNS | System resolver | Checks whether a name-derived domain exists before any HTTP request | — | Candidate generation only | not HTTP |
| Brave Search API (optional, off unless `BRAVE_API_KEY` is set) | Licensed API | Candidate domains only — results are never evidence and are not stored | Brave API terms | Candidate must pass the same identity gate | 1 / company |

Not used: LinkedIn/Meta/Glassdoor/Indeed scraping, Google/Bing result pages, Proff/Purehelp/1881 page scraping,
Brønnøysund `w2.brreg.no/kunngjoring` pages (disallowed by robots.txt — the agent detects this and reports `blocked`),
authorised role endpoints exposing national identity numbers.

## Identity gate (wrong-company prevention)

The organisation number is the only identity anchor. Every website candidate (registry `hjemmeside`, NAV employer homepage
or contact-email domain for an orgnr-matched ad, name-derived domain, optional search candidate) is fetched and assessed:

1. **Exact (score 1.0)** — the organisation number (any of `810034882`, `810 034 882`, `810.034.882`, `NO 810 034 882 MVA`) appears on the homepage, contact or about page — unless that page also lists other organisation numbers on a non-matching domain (group/portfolio page → `ambiguous`). Outside sites the company declared to an official source (registry `hjemmeside`; employer homepage of an orgnr-matched NAV ad), the number must sit in the site's own identity block (footer/address, contact or about page, its JSON-LD Organization). A domain merely matching the name, or a NAV contact e-mail domain (possibly a recruiter's), is not proof of ownership; an article or client list mentioning the number is `ambiguous`; a declared candidate that redirects to another registered domain loses its declared status. A number found only in hidden markup (script data, attributes) counts only on a declared domain or inside the site's JSON-LD Organization, and never when the HTML lists ≥ 3 other valid (MOD11) organisation numbers: chain sites embed every member's number.
2. **Rejected** — the site states a *different* labelled organisation number / VAT id → parent, sister, franchise or unrelated entity. This overrides every name signal.
3. **Rejected** — parked / for-sale / placeholder page.
4. **Exact (0.97)** — full registered legal name (legal-form suffix in capitals) *and* the registry phone number or registered street address + postcode appear on the site, on a name-matching or officially declared domain.
5. **Exact (0.92)** — the site was declared by an official source (registry `hjemmeside`, or the employer homepage of a NAV ad whose `employer.orgnr` equals the company; not a contact e-mail domain) *and* the exact legal name appears on the page, or the brand name plus the registry's own phone or address. A declared domain can be a group or brand site, so a brand title alone is never enough. A matching phone alone is not enough (shared phones point to related companies).
6. Anything else with a name hit → `ambiguous`, recorded with the reason, **not published**.

Social profiles are published only when linked from the verified site *and* the handle is the company's name: every distinctive word of the legal
name must be in it, and anything left over may only be a harmless affix (`as`, `no`, `norge`, `official`), another legal-name word or a page ID.
Footer links often belong to a parent group, a sister or subsidiary, a brand, the web agency or the theme, so a shared word is never enough. Platform paths (`accounts`, `login`, `hashtag`, `pages`) and opaque channel IDs are rejected.
When the company's site is only a section of a larger site (for example a regional page on a national organisation's domain), no social accounts,
news or jobs are taken from that domain. News must be a real post with its own publication date: the date must belong to exactly one article (never a date shared by a
list or found elsewhere on the page), be plausible, and never be a "modified"/"updated" date; contact, product and shop pages, menu labels
and demo posts are never news. Careers landing pages are not published; website JobPosting
markup counts only when its employer carries this org number or the exact legal name including the legal form (a similar name never does), and NAV jobs always link to the single ad.

## Personal data

This is an engineering description, not a legal opinion; a production deployment in Norway should be reviewed by a privacy professional.

| Topic | Practice |
|---|---|
| Purpose | Company research: who leads a company, where it operates, whether it is hiring. Personal data appears only as part of company facts. |
| Data published | Names and roles of registered role holders (CEO, board, auditor) exactly as in Enhetsregisteret; NAV ad titles and locations. No birth dates (discarded on fetch), no national ID numbers (authorised endpoints never called), no sole-trader (ENK) phone numbers, no personal e-mail addresses (only generic company mailboxes on the company's own domain). |
| Legal basis (assumed) | Legitimate interest in company due diligence, for data the law requires to be public in the register. NLOD 2.0 covers reuse of the dataset but **does not by itself grant a basis for processing personal data**; that basis has to be assessed for the actual deployment. |
| Not done | No profiles of individuals, no linking a person across companies, no inference of sensitive characteristics, no personal data sent to third parties (there is no LLM or external model). |
| Retention | `state/<org>.json` holds the latest snapshot only. `state/history/` is append-only for the agent so evidence survives refreshes; the operator prunes it with `python tools/purge.py --older-than-days 365` (suggested retention: 12 months, run periodically). |
| Corrections and erasure / objection | `python tools/purge.py --person "Name"` removes that person's role claims, evidence and change records from the state and history, and adds them to `state/suppressed_persons.txt`, which every later run honours, so the public register does not re-add them. `--org <number>` removes a company's baseline and history. Registry data is re-fetched each run, so a correction made at Brønnøysund appears on the next refresh. |
| Logs | Run logs contain counts and URLs, never personal data or secrets. |

## Security

- **Single HTTP path** (`signalpost/http.py`): every request passes the budget/deadline check, the SSRF guard and size limits.
- **SSRF guard**: only `http(s)` on ports 80/443; hostnames must resolve exclusively to globally-routable IPs (loopback, RFC1918, link-local,
  metadata addresses blocked); every redirect hop is re-validated; max 5 redirects; environment proxies are ignored.
- **Redirects**: followed by the client hop by hop (max 5), never by urllib. Each hop is validated, budget-counted, rate-limited per destination
  host and robots-checked where applicable. Credentials (`Authorization`, `Cookie`, `X-Subscription-Token`, `X-API-Key`) are dropped on any
  change of origin, and the NAV feed's pagination and entry URLs must be `https://pam-stilling-feed.nav.no` (exact host, default port,
  no embedded credentials) or the walk stops, so the bearer token is never sent elsewhere or over plain HTTP.
- **DNS-rebinding protection**: validation and connection use the *same* resolution. The custom HTTP(S) connection classes resolve once,
  check every returned address, and open the socket to that checked IP (TLS still verifies the real hostname via SNI), so a second DNS
  answer cannot steer the connection to an internal address.
- **Response limits**: 2 MB per page (8 MB per NAV feed page), 15 s timeout, HTML only for site pages; scripts are never executed (static parsing).
- **Prompt injection**: there is no LLM in the loop; fetched text is data, matched only by deterministic rules.
- **Secrets**: none required. Optional `BRAVE_API_KEY` / `NAV_FEED_TOKEN` are read from environment variables only and never logged or written to output.
- **Cost ceiling**: `--max-cost-usd` (default $10). Paid calls reserve their cost before the request and are refused past the ceiling (default spend is $0).
- **Budgets enforced, not reported**: `--max-requests` (default 2000) and `--deadline-minutes` (default 42 of the 45 allowed). The HTTP client
  itself refuses to start any request in the final reserve (90 s, or a quarter of very short deadlines), so no phase can eat the time kept for
  writing output. When budget or time runs out, remaining sources are marked `blocked` with the reason and every envelope is still written.
- **Politeness**: ≤ 6 concurrent requests to brreg.no, ≤ 2 per other host, robots.txt honoured for all non-API pages, identifying User-Agent.

A name alone is never enough, even an exact "Name AS" on a domain equal to the name: verification runs found
`shark.no` showing "Shark AS" (a Kolbotn property firm) while the requested SHARK AS is a Sandefjord freight company.
