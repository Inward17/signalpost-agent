# Version 2: what changed after Builderr's audit, and how to verify it

This document explains every change made after Builderr audited version 1. It covers three rounds:

- **Version 2.0**: Builderr's audit (websites, social links, news, jobs).
- **Version 2.1**: a second review of version 2.0 (social handles shared by similar names, news dates and unusual URLs, jobs matched by employer name).
- **Version 2.2**: two residual risks raised after version 2.1 (a subsidiary using its parent's root domain, social accounts not clearly attributable).

For each point it shows:
- what the agent did before (with real examples and the exact old code);
- what the rule is now;
- how the code was changed;
- how you can check it yourself.

| | Version 1 (audited) | Version 2.0 | Version 2.1 | Version 2.2 (current) |
|---|---|---|---|---|
| Agent code commit | `afc3f0ab3858b86889a07b7deff73bc1685edc21` | `a96e0f1d38e1db2c2323be8494de1f790ac855ab` | `1f2ad26cfdbbd270c252cc4fc15f01c3154cb0eb` | `70cfcf091640d4742684a036f988d08624d1d69d` |
| Submission commit | `f49124a` | `7a3ade2` | `4c79c38` | `3f5cd76` (or a later documentation-only commit) |
| Offline tests | 40 | 47 | 51 | 56 |

See every code change since version 1:

```bash
git diff afc3f0a 70cfcf0 -- signalpost/
```

Only `signalpost/website.py` and `signalpost/jobs.py` changed (plus tests and the verification tools).

## Summary

The counts below come from `python tools/verify_v2_fixes.py --dataset <file>`, which applies the **current** rules to each version's published
1,000-profile dataset:

| # | Point | v1 dataset | v2.0 dataset | v2.1 dataset | v2.2 dataset |
|---|---|---|---|---|---|
| 1 | Website is the company's own | 14 | 0 | 0 | 0 |
| 2 | Social handles belong to this company | 47 | 38 | 0 | 0 |
| 3 | News are real, dated posts | 2 | 0 | 0 | 0 |
| 4 | Jobs are single ads for this company | 26 | 0 | 0 | 0 |
| | **Total** | **89** | **38** | **0** | **0** |

Published claims in the dataset:

| Claim | v1 | v2.0 | v2.1 | v2.2 |
|---|---|---|---|---|
| Websites | 142 | 137 | 136 | 137 (8 as URL only) |
| Social profiles | 175 | 163 | 124 | 113 |
| News items | 5 | 3 | 3 | 3 |
| Careers pages | 26 | 0 | 0 | 0 |
| NAV job ads | 4 | 7 | 8 | 8 (live ads change daily) |

---

# Part 1: version 2.0 (Builderr's audit)

> - Check that the website is the company's own, not a parent group or brand site. If the registry lists a group domain, look for this company's org number or exact name on it before using its social links, news or jobs.
> - Check social links. Footer links often belong to the parent group, the web agency or the website theme, so only publish an account whose handle matches this company.
> - Check that news items are real, dated posts. Menu labels like "See more news" and product pages aren't news, and a "modified" or feed "updated" date isn't a publish date.
> - Check that jobs are single ads for this company, not a careers landing page, a NAV search link or the parent's vacancies.

## 1. Website must be the company's own, not a parent group or brand site

### Before (v1)

A website listed in Brønnøysund (a "declared" site) was accepted as soon as the company's **brand name** appeared in the page title. Old code in
`assess_identity()`:

```python
if declared and (name_hit or brand_hit):
    hit = name_hit or brand_hit
    return {"verdict": "exact", "score": 0.92, "reason": f"site declared by ... and its legal/brand name appears on page", **hit}
```

There was also no notion of a company owning only **part** of a site, so social links, news and the careers page were harvested from a parent's whole domain.

**Real examples:**
- **ASK SPEKEHUS AS → `askgard.no`**, accepted on the title "ASK Spekehus" alone. No org number and no exact legal name on the site.
- **DNT NORD-TRØNDELAG → `dnt.no/nordtrondelag`**: a regional page on the national DNT site. Its social account and careers page came from the parent.
- 14 sites in total were accepted on a brand title.

### The fix

- A declared site needs **the org number**, **the exact legal name** (for example "ASK Spekehus AS"), or **the brand name plus the registry's own
  phone or address**. A brand title alone is never enough.
- If the verified site is a **section of a larger site** (a path such as `/nordtrondelag`, not the root or a `/no` or `/home` landing path), its URL
  is published but **no social links, news or jobs** are taken from that domain.
- Version 2.2 extends this to a subsidiary declared with its parent's **root** domain, where there is no path to detect (Part 3, point E).

### How it was made

`assess_identity()` now reads:

```python
if declared and (name_hit or (brand_hit and contact_hit)):
    ...
```

The new `section_of_larger_site(homepage)` is checked at the start of `extract_site()`, which then stops before collecting socials, news and jobs.

**Tests:** `test_declared_brand_site_needs_org_number_or_exact_name`, `test_section_of_larger_site_detection`, `test_section_site_publishes_no_parent_socials_news_or_jobs`.

## 2. Social links must belong to this company

### Before (v1)

A social link from the verified site was published when **any** of these held:
- the handle matched the company name;
- the handle matched the **website's domain name** (a brand);
- the link was listed in the site's JSON-LD `sameAs`.

Old code:

```python
if url in same_as or (core and (core in handle or handle in core and len(handle) >= 4)) or (label and len(label) >= 4 and label in handle):
```

**Real examples:**
- **NORDIC TOY TEAM AS**: `Ringobamsen`, `Ringokjeden`, `ringo_leker` (its brand *Ringo*), and the junk link `instagram.com/accounts`.
- **PARASOLLFIX AS**: `Smartfootoriginals`, named after the website.
- **WALL-IT AS**: an opaque YouTube channel ID.

### The fix (v2.0, tightened in v2.1 and v2.2; see Parts 2 and 3)

Only an account whose **handle belongs to this company** is published. Domain-name and `sameAs` shortcuts are gone. Platform paths are rejected
(Instagram `accounts`, `direct`, `explore`; Facebook `login`, `hashtag`, `pages`; X `hashtag`, `login`).
Since v2.2 the company must also present the account as its own (Part 3, point F).

**Tests:** `test_social_handle_must_name_the_company`, `test_social_normalisation_rejects_share_links`.

## 3. News must be real, dated posts

### Before (v1)

Any page with Article markup and a 15+ character title counted as news, unless its last URL segment was exactly a page name like `kontakt`, so
`kontakt-oss` passed. Old code:

```python
return not any(last == t or last.startswith(t + ".") for terms in PAGE_KINDS.values() for t in terms) and last.count("-") >= 1
```

**Real examples:** WALL-IT's "Kontakt oss | WALL-IT" at `/kontakt-oss/`, and FISHTECH HYGENA's demo post `/2018/08/30/blog-test-1/`.

### The fix

- Contact, about and careers pages, product, shop, category and tag pages, menu labels ("Se flere nyheter", "Les mer", "See more news") and
  demo posts are rejected.
- A `<time>` marked "modified", "updated", "oppdatert" or "endret" is never used as a publish date (`is_publish_date`).
- JSON-LD uses only `datePublished`.

The URL rule was refined in v2.1 (Part 2, point C).

**Tests:** `test_news_must_be_a_real_dated_post`, `test_modified_dates_are_not_publish_dates`, `test_site_pages_are_not_news`.

## 4. Jobs must be single ads for this company

### Before (v1)

The careers page was fetched and published as a fact (`careers_page`). Its link was found from menu text, so it was sometimes not a careers page at all.
JobPosting markup wasn't checked against the employer. Old code:

```python
careers = next((p for p in pages if p.kind == "careers"), None)
if careers:
    d.claim("careers_page", "website", careers.resp.final_url, [ev])
```

**Real examples (26 careers pages):** landing pages such as `framkompetanse.no/jobb-hos-oss`; pages that weren't careers pages at all, such as
`sakki.no/products/fodt` and `atlaseiendom.no/omoss`; and parent organisations' pages, such as `thon.no/karriere/` for Thon Holding and `dnt.no/om-dnt/...`.

### The fix

- Careers landing pages are no longer fetched or published.
- A website JobPosting must have its own URL, be current, and name **this company** as `hiringOrganization`. The employer test was tightened in v2.1 (Part 2, point D).
- A NAV job always links to the **single ad** (`single_ad_url`). NAV matching already required `employer.orgnr` to be the company or one of its own subunits.

**Tests:** `test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs`.

---

# Part 2: version 2.1 (second review of version 2.0)

## B. Social handles shared by similar names and subsidiaries

### Before (v2.0)

`social_handle_matches()` accepted a handle that contained the joined name, a company's single distinctive word, or **any two** of its distinctive words:

```python
if "".join(words) in handle:
    return True
if len(words) == 1:
    return len(words[0]) >= 4 and words[0] in handle
return sum(1 for w in words if w in handle) >= 2
```

That was too loose. Checked directly:

| Company | Handle linked from its site | v2.0 | Should be |
|---|---|---|---|
| SANDNES ELEKTRISKE SERVICE AS | `sandneselektriske` (sister or parent) | published | withheld |
| AKER AS | `akerbp` (a different company) | published | withheld |
| DIPS AS | `dipsfront` (a subsidiary) | published | withheld |
| NORDIC TOY TEAM AS | `nordictoyteamgroup` (the group) | published | withheld |

Re-checking the v2.0 dataset this way found 38 accounts that don't strictly belong to the company. Examples:
- `MaskegruppenNO` for MASKE AS (the group);
- `dentalianydalen` for DENTALIA AS (a branch or sister clinic);
- `EnviroBil` for ENVIRO BIL NESBRU AS (the chain);
- `akofs-offshore` for AKOFS OFFSHORE OPERATIONS AS (likely its parent).

### The fix

The handle must **be** the company's name:
- **every** distinctive word of the legal name must appear in it. A word may be shortened to its first 6+ letters, so `advokat` matches `advokatene`.
- Whatever is left over may only be harmless affixes (`as`, `asa`, `no`, `norge`, `norway`, `official`, `hq`), other words of the legal name, or
  a numeric page ID.
- Norwegian letters may be spelled several ways (`å` = `aa`, `ø` = `oe`, `æ` = `ae`), and a very short name (such as ETA NORGE AS) requires the whole legal name.

**Accepted:** `dips_as`, `sodvin.as`, `storkasnorge`, `wallitnorway`, `VaalerengaFotballElite`, `eta-norge-as`, `Krypton-Film-116363225096942`.

**Rejected:** `sandneselektriske` for a "…Service AS", `akerbp`, `dipsfront`, `nordictoyteamgroup`, `MaskegruppenNO`, `dentalianydalen`.

### How it was made

`social_handle_matches()` in `signalpost/website.py` was rewritten. Each required word, or its 6+ letter stem, is removed from the handle; the
remainder must parse completely into allowed words (`_strip_affixes`, a small dynamic-programming check), after page-ID digits are removed:

```python
for w in words:
    match = next((w[:n] for n in range(len(w), min(len(w), 6) - 1, -1) if w[:n] in rest), None)
    if match is None:
        return False
    rest = rest.replace(match, "", 1)
rest = re.sub(r"\d+", "", rest)
return _strip_affixes(rest, HANDLE_AFFIXES | set(all_words))
```

**Trade-off, stated plainly:** accounts that add a descriptive word not in the legal name are now withheld, even when they're probably the
company's own. Examples: `perrioppussing` for PERRI AS, `danvikfhs` for STIFTELSEN DANVIK. Published social profiles went from 163 to 124. This
follows Builderr's instruction to publish only an account whose handle matches this company.

**Tests:** `test_social_handle_must_name_the_company` (23 cases, including all of the above).

## C. News dates and unusual URLs

### Before (v2.0)

- **Date attached to the wrong article.** For a `<time>` on the news page, the agent took the nearest container and its **first** link. When a block
  held several articles and one date, that date was pinned to the first article. Checked directly: a `<div>` with two article links and one
  `<time datetime="2026-10-01">` produced "Første sak …" dated 2026-10-01.
- **No sanity check on dates.** Future or ancient dates were accepted.
- **Legitimate news with unusual URLs was dropped.** Every news item needed a post-like URL, so `x.no/p/12345` or `x.no/ny-avtale-statens-vegvesen`
  was rejected even when the site explicitly marked it as a `NewsArticle`.

### The fix

- A `<time>` date is used only when its nearest item container holds **exactly one date and links to exactly one article** (`news_list_item`).
  A date shared by a block of articles, or a page-level date, is never assigned to any of them.
- A date must be **plausible**: between 1995 and tomorrow (`plausible_publish_date`).
- JSON-LD dates come from the **article node's own `datePublished`**, never `dateModified` or a date elsewhere on the page.
- **Unusual URLs:** an explicit `NewsArticle`, `BlogPosting` or `PressRelease`, or a structured news-list entry (one date, one link), is accepted with
  any URL pattern. A generic `Article` (CMSs add it to ordinary pages) still needs a post-like URL. Site pages, products, menu labels and demo posts
  are always rejected.

### How it was made

New functions `news_list_item()` and `plausible_publish_date()`. `is_news_item()` gained `require_post_url`. In `extract_site()`:

```python
explicit = bool(set(kinds) & {"NewsArticle", "BlogPosting", "PressRelease"})
if plausible_publish_date(date, today) and ... and is_news_item(title, url, page.resp.final_url, require_post_url=not explicit):
...
item = news_list_item(t, page.resp.final_url, domain)   # None unless one date and one article
```

**Tests:** `test_news_date_must_belong_to_one_article`, `test_explicit_news_types_accept_unusual_urls_but_generic_articles_do_not`.

## D. Jobs matched by employer name

### Before (v2.0)

A website JobPosting was accepted when its `hiringOrganization` had the org number **or the same distinctive words** as the legal name, with the
legal form ignored:

```python
return bool(name) and set(core_tokens(str(name))) == set(core_tokens(legal)) and bool(core_tokens(legal))
```

Checked directly for SANDNES ELEKTRISKE AS:
- "Sandnes Elektriske" (no legal form, which could be the group's brand) was **accepted**;
- "Sandnes Elektriske DA" (a different legal entity) was **accepted**;
- a posting with the exact name but another organisation's number was **accepted**.

### The fix

- The employer must carry **this organisation number**, or match the **exact registered legal name including the legal form**.
- Any other 9-digit organisation number in the employer data rejects the posting outright.
- So "Sandnes Elektriske", "… DA", "… Service AS" (sister) and "… Holding AS" (parent) are all withheld.
- NAV ads (the source of all published jobs so far) were already strict: `employer.orgnr` must be the company or one of its subunits, and an ad
  without an orgnr needs the exact full legal name. A new test confirms that a sister company's ad and a brand-name ad without an orgnr are not published.

### How it was made

`hiring_org_is_company()` in `signalpost/website.py`:

```python
numbers = set(re.findall(r"(?<!\d)(\d{9})(?!\d)", ...))
if d.org in numbers:
    return True
if numbers:
    return False                                  # another organisation's number
return bool(name) and bool(legal) and tokens(str(name)) == tokens(legal)   # exact legal name incl. legal form
```

**Tests:** `test_website_job_needs_exact_employer_not_a_similar_name`, `test_nav_job_with_similar_employer_name_is_not_published`.

---

# Part 3: version 2.2 (residual risks raised after version 2.1)

> 1. Root-level parent websites. A subsidiary could use a parent domain without having a distinct URL path. Test that case explicitly.
> 2. Social handles can still be ambiguous. If the account is not clearly attributable to the company, withholding it is safer.

Both were raised as risks to test, not confirmed defects. Testing showed both were real gaps in version 2.1, so both are now fixed.

## E. A subsidiary declared with its parent's root domain

### Before (v2.1)

Parent sites were only caught when the company's URL was a **section** of a larger site (`section_of_larger_site`, for example
`dnt.no/nordtrondelag`). A subsidiary registered with its parent's **root** domain has no path to detect.

Tested directly on the v2.1 code: Brønnøysund declares `https://elgruppen.no/` for SANDNES ELEKTRISKE SERVICE AS, and the parent's page lists
"Sandnes Elektriske Service AS (org.nr 912 345 674)" in its body text. The identity gate accepts it, which is correct: it is the company's
declared site and carries its number. But `extract_site` then took everything on the parent's site as the subsidiary's own:
- the description;
- the `og:site_name` brand;
- footer social links;
- contact e-mails and phones;
- the parent's news;
- JobPosting markup.

```python
section = section_of_larger_site(verdict["homepage"])   # v2.1: only a URL path could mark a shared site
```

### The fix

There are now two separate questions:
- **Is this the company's website?** This is the URL claim. It works as before.
- **Is the site the company's own?** This decides whether the site's content is the company's.

Site content is taken only when the site is shown to be the company's own:
- the domain matches the company name; or
- the org number is in the site's own footer, address or colophon block, or on its contact or about page, and **no other organisation's number**
  is in that block (a group footer listing several companies proves nothing); or
- the exact legal name, with its legal form, is in the site's own footer block, and no other organisation's number is there; or
- the site's JSON-LD `Organization` record is this company (its org number, or its exact legal name).

Otherwise only the URL is published. The website claim records why in `site_owner`: "site not shown to belong to this company (shared,
parent or brand site): only its URL is published". The following are all withheld:
- description and brand;
- social accounts;
- contacts from the site;
- news;
- jobs.

The registry phone still fills the contact section.

### How it was made

`site_owner_proven()` in `signalpost/website.py` (called from `try_site` for every exact match):

```python
if name_matches_domain(legal, domain):
    return True, "domain matches the company name"
for page in pages:
    texts = [(b.get_text(" ", strip=True), True) for b in page.soup.find_all(["footer", "address"]) + page.soup.select(IDENTITY_BLOCKS)]
    if page.kind in ("contact", "about"):
        texts.append((page.text, False))
    for text, is_block in texts:
        if {re.sub(r"\D", "", f) for f in _ORG_LABELLED.findall(text)} - {d.org} - d.subunit_orgs:
            continue                                   # another organisation is named here: not proof
        if org_re.search(text):
            return True, "organisation number in the site's own footer/contact block"
        if is_block and name_re and name_re.search(text):
            return True, "exact legal name in the site's own footer"
    if any(org_node_is_company(node, d) for node in walk_jsonld(page.jsonld, ORG_TYPES)):
        return True, "the site's own structured data names this company"
return False, "site not shown to belong to this company (shared, parent or brand site): only its URL is published"
```

and in `extract_site`:

```python
shared = section or not verdict.get("owner_proven", True)   # shared, parent or brand site: URL only
```

**Tests:**
- `test_subsidiary_declared_with_parent_root_domain_gets_no_parent_facts` (the case above);
- `test_subsidiarys_own_root_site_keeps_its_facts` (the company's own root site keeps everything);
- `test_footer_listing_several_companies_does_not_prove_site_owner`.

All three fail on the v2.1 code. The verifier (`tools/verify_run.py`, R14) now also fails any run that publishes a claim taken from a site
not shown to be the company's own.

### Effect on real data

137 unique websites were published across the 13 runs:

| Site ownership shown by | Websites |
|---|---|
| domain matches the company name | 105 |
| org number in the site's own footer or contact block | 14 |
| exact legal name in the site's own footer | 10 |
| **not shown: URL only** | **8** |

Of the 8, `vif-fotball.no` (VÅLERENGA FOTBALL ELITE) is a genuinely shared site: the club Vålerenga Fotball and the separate entity Vålerenga
Fotball Elite use it. That is exactly the case the review described.

The other 7 look like the companies' own sites, but their footers carry neither the org number nor the exact legal name: `sollifjellet.no`,
`obf.no`, `aasemontessori.no`, `arealpluss.no`, `hellekhagen.no`, `kndt.no` and `borealisfestival.no`. Withholding their site facts is the
price of the safer rule.

Changes in the dataset compared with v2.1:

| Claim | v2.1 | v2.2 |
|---|---|---|
| Descriptions | 131 | 123 |
| Brands | 57 | 54 |
| Contact e-mails | 64 | 61 |
| Contact phones | 71 | 67 |

## F. Social accounts that cannot be attributed to the company

### Before (v2.1)

Any link on any fetched page was published if its handle matched the company name. That included:
- a link inside article text (for example "follow our partner here");
- the `sameAs` list of **any** `Organization` record in the page's JSON-LD, including another organisation's (a parent's or partner's).

A matching name was treated as proof that the company owns the account.

### The fix

A matching handle is still required, but it is no longer enough. The company must present the account as its own:
- in the site's header, footer, navigation or address block (or an element whose class or id says footer, header or social);
- on its contact or about page;
- as the same link on **two or more of its pages**: site-wide chrome on page builders such as Framer or Wix, whose footers are unlabelled `<div>`s;
- in the `sameAs` of the site's JSON-LD record **for this company** (`org_node_is_company`).

The site must also be the company's own (point E). A link that appears only inside an article on one page, or only in another organisation's
structured data, is withheld.

### How it was made

The social collection loop in `extract_site`:

```python
for node in walk_jsonld(page.jsonld, ORG_TYPES):
    if not org_node_is_company(node, d):
        continue                                      # another organisation's sameAs is not this company's
    ...
for a in page.soup.select("a[href]"):
    s = normalize_social(urllib.parse.urljoin(page.resp.final_url, str(a.get("href"))))
    if not s:
        continue
    if page.kind in ("contact", "about") or in_site_chrome(a):
        socials.setdefault(s["url"], (s, page))
    else:
        repeated.setdefault(s["url"], {})[page.resp.final_url] = (s, page)
for url, seen in repeated.items():                   # the same link on two or more pages is site-wide chrome
    if len(seen) >= 2:
        socials.setdefault(url, next(iter(seen.values())))
```

**Tests:**
- `test_social_account_must_be_attributable_not_just_name_matching`: an article link, another organisation's `sameAs`, and the company's own `sameAs`;
- `test_social_link_repeated_across_site_pages_counts_as_site_chrome`.

### Effect on real data

Social profiles in the dataset went from 124 to **113**. The 11 withheld accounts:

- **6 are on the 8 URL-only sites.** One of them is `linkedin.com/company/oslo-og-omegn-boligforvaltning-as`, listed for a BBL: the "-as" handle
  belongs to a different legal entity.
- **5 were linked only in the body of a single page:** `tindeq`, `stork-as`, `oslovedhandel`, `norskvannskjaering` and `elektrikernbodo`.

All 113 remaining accounts were reviewed by hand. Each is:
- the company's name, optionally with `as`, `no`, `norge`, a country word or a page number;
- presented by the company itself.

---

## The checks are now automatic

The contract verifier `tools/verify_run.py` includes rule group **R14**, applied to every run:
- every social handle belongs to the company;
- every news item is a real post;
- no careers landing pages;
- every NAV job links to a single ad;
- no claim is taken from a site not shown to be the company's own (version 2.2).

All 13 verification runs at `70cfcf0` pass R1–R14, with 1,400 financial values matching the live filings exactly ([TEST_REPORT.md](TEST_REPORT.md)).

## How to verify it yourself

From the repository folder, with the virtual environment set up as in the README (on Windows, use `.venv\Scripts\python.exe` for `python`):

**1. See the code changes**

```bash
git diff afc3f0a a96e0f1 -- signalpost/    # version 2.0
git diff a96e0f1 1f2ad26 -- signalpost/    # version 2.1
git diff 1f2ad26 70cfcf0 -- signalpost/    # version 2.2
```

**2. Run the tests**

```bash
python tests/test_agent.py
```

Expected: `56 passed`.

**3. Replay the audit and review cases against the current code**

```bash
python tools/verify_v2_fixes.py
```

Expected: `29/29 audit cases behave as Builderr asked.` This covers:
- similar-name social handles;
- shared news dates and unusual news URLs;
- sister, parent and brand employers;
- a subsidiary declared with its parent's root domain;
- an account linked only inside an article.

**4. Count the problems in each version's dataset with the current rules**

```bash
git show f49124a:profiles/profiles.jsonl.gz > v1.jsonl.gz
git show 7a3ade2:profiles/profiles.jsonl.gz > v20.jsonl.gz
git show 4c79c38:profiles/profiles.jsonl.gz > v21.jsonl.gz
python tools/verify_v2_fixes.py --dataset v1.jsonl.gz
python tools/verify_v2_fixes.py --dataset v20.jsonl.gz
python tools/verify_v2_fixes.py --dataset v21.jsonl.gz
python tools/verify_v2_fixes.py --dataset profiles/profiles.jsonl.gz
```

Expected: v1 89 problems, v2.0 38 (all social handles), v2.1 0, current 0. The v2.1 dataset predates the `site_owner` field, so the
version 2.2 points are checked by the tests, the replay and verifier rule R14 rather than by this scan.

**5. Run the agent on the audited companies**

```bash
python -c "import gzip,json; [print(json.loads(l)['organisation_number']) for l in gzip.open('profiles/profiles.jsonl.gz','rt',encoding='utf-8') if json.loads(l)['legal_identity']['legal_name'] in ('ASK SPEKEHUS AS','DNT NORD-TRØNDELAG','NORDIC TOY TEAM AS','PARASOLLFIX AS','WALL-IT AS','VÅLERENGA FOTBALL ELITE')]" > audited.txt
python run.py --input audited.txt --output out_check
```

Then open `out_check/report.html` and check:
- ASK Spekehus's website is `ambiguous`;
- DNT Nord-Trøndelag has its page but no social accounts;
- Nordic Toy Team and Parasollfix have no brand-named accounts;
- WALL-IT has no "Kontakt oss" news item;
- no company shows a careers page;
- Vålerenga Fotball Elite shows `vif-fotball.no` as its website but no description, social accounts or news from it. Its `official_website`
  claim in `envelopes.jsonl` gives the reason in `site_owner` (the site is shared with the club Vålerenga Fotball).

**6. Check one claim by hand.** In `out_check/envelopes.jsonl`, each claim lists `evidence_ids`. The matching evidence record gives the source URL,
retrieval time, content hash and the exact text span behind the claim.
