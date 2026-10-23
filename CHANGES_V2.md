# Version 2: what changed after Builderr's audit, and how to verify it

This document explains, for each point in Builderr's audit of version 1:
- what the agent did before (with real examples from the submitted data and the exact old code);
- what the rule is now;
- how the code was changed;
- how you can check it yourself.

| | Version 1 (audited) | Version 2 |
|---|---|---|
| Submission commit | `f49124a` | `15c56b84a066661c65b69e62a7e9576be793d1c7` (or later docs-only commits) |
| Agent code commit | `afc3f0ab3858b86889a07b7deff73bc1685edc21` | `a96e0f1d38e1db2c2323be8494de1f790ac855ab` |
| Code changed | | `signalpost/website.py`, `signalpost/jobs.py` (plus 7 new tests in `tests/test_agent.py`) |

See every code change at once:

```bash
git diff afc3f0a a96e0f1 -- signalpost/
```

## Builderr's audit (as received)

> - Check that the website is the company's own, not a parent group or brand site. If the registry lists a group domain, look for this company's org number or exact name on it before using its social links, news or jobs.
> - Check social links. Footer links often belong to the parent group, the web agency or the website theme, so only publish an account whose handle matches this company.
> - Check that news items are real, dated posts. Menu labels like "See more news" and product pages aren't news, and a "modified" or feed "updated" date isn't a publish date.
> - Check that jobs are single ads for this company, not a careers landing page, a NAV search link or the parent's vacancies.

## Summary

| # | Audit point | Problems in v1 dataset | In v2 dataset | Main code change |
|---|---|---|---|---|
| 1 | Website is the company's own | 14 | 0 | `assess_identity` (declared-site rule), new `section_of_larger_site` |
| 2 | Social handles match the company | 15 | 0 | new `social_handle_matches`; larger `normalize_social` blocklists |
| 3 | News are real, dated posts | 2 | 0 | rewritten `is_news_item`; new `is_publish_date` |
| 4 | Jobs are single ads for this company | 26 | 0 | careers-page claim removed; new `hiring_org_is_company`; new `single_ad_url` |

The problem counts come from `python tools/verify_v2_fixes.py --dataset <file>`, run against the v1 dataset (`f49124a`) and the v2 dataset.
Published claims in the 1,000-profile dataset, v1 → v2:

| Claim | v1 | v2 |
|---|---|---|
| Websites | 142 | 137 |
| Social profiles | 175 | 163 |
| News items | 5 | 3 |
| Careers pages | 26 | 0 |
| NAV job ads | 4 | 7 (new live ads) |

---

## 1. Website must be the company's own, not a parent group or brand site

### Before (v1)

A website listed in Brønnøysund (a "declared" site) was accepted as soon as the company's **brand name** appeared in the page title. It didn't
matter whether the org number or the exact legal name was on the site. Old code in `signalpost/website.py`, `assess_identity()`:

```python
if declared and (name_hit or brand_hit):
    hit = name_hit or brand_hit
    return {"verdict": "exact", "score": 0.92, "reason": f"site declared by ... and its legal/brand name appears on page", **hit}
```

There was also no notion of a company owning only **part** of a site. When the verified page was a section of a larger organisation's site,
the agent harvested social links, news and the careers page from the whole domain, which belonged to the parent.

**Real examples from the v1 submission:**
- **ASK SPEKEHUS AS → `askgard.no`**, accepted on the title "ASK Spekehus" alone. No org number and no "ASK Spekehus AS" on the page; `askgard.no` is the farm's group/brand site.
- **DNT NORD-TRØNDELAG → `dnt.no/nordtrondelag`**: a regional page on the national DNT site. The social account and careers page published for it came from `dnt.no`, the parent.
- In total, 14 sites were accepted on a brand title (the v1 scan lists them, for example City Steinhus, Ragnas Hage, Webstep and Årskogvika Camping).

### The fix (rule now)

- A declared site is accepted only with **the org number** on it, **or the exact legal name** (for example "ASK Spekehus AS"), **or the brand name
  plus the registry's own phone number or address**. A brand title alone is never enough. This is exactly what Builderr asked: "look for this
  company's org number or exact name".
- If the verified site is a **section of a larger site** (a path such as `/nordtrondelag`, as opposed to the site root or a language/home
  path like `/no` or `/home`), its URL is still published, but **no social links, news or jobs** are taken from that domain, because they belong to the site's owner.

### How it was made

`signalpost/website.py`, `assess_identity()`:

```python
# A declared domain can still be a group or brand site: require the exact legal name (or the brand plus the registry's own
# phone/address), never a brand title alone.
if declared and (name_hit or (brand_hit and contact_hit)):
    ...
```

`name_hit` is the exact legal name with its legal-form suffix in capitals; `contact_hit` is the registry's own phone number or street address and
postcode found on the page.

New function `section_of_larger_site(homepage)`. It returns True when the homepage URL has a first path segment that isn't a site-root or
language segment (`no`, `en`, `home`, `forside`, …). `extract_site()` checks it first:

```python
section = section_of_larger_site(verdict["homepage"])
...
if section:
    d.section("social_profiles", "not_available", "company's site is a section of a larger site; accounts linked there belong to the site owner")
    ...
    return          # no socials, news or jobs from the parent's domain
```

**Effect:** six declared sites that only showed a brand title are now withheld as `ambiguous` (ASK Spekehus, City Steinhus, Velklang, Ragnas Hage,
Webstep, Årskogvika Camping). Eight declared sites stay published because the brand name **and** the company's registered phone or address
appear on them. DNT Nord-Trøndelag keeps its page URL but gets no social accounts or jobs from `dnt.no`.

**Tests:** `test_declared_brand_site_needs_org_number_or_exact_name`, `test_section_of_larger_site_detection`,
`test_section_site_publishes_no_parent_socials_news_or_jobs`.

---

## 2. Social links must have a handle matching this company

### Before (v1)

A social link from the verified site was published when **any** of these held:
- the handle matched the company name;
- the handle matched the **website's domain name** (a brand);
- the link appeared in the site's JSON-LD `sameAs` list.

Old code in `extract_site()`:

```python
if url in same_as or (core and (core in handle or handle in core and len(handle) >= 4)) or (label and len(label) >= 4 and label in handle):
    ... publish
```

`label` is the website's domain name, so on a brand site every brand account passed. `normalize_social()` also didn't block Instagram's
`accounts` path, so the login link was published as a profile.

**Real examples from the v1 submission:**
- **NORDIC TOY TEAM AS**: `facebook.com/Ringobamsen`, `youtube.com/user/Ringokjeden`, `instagram.com/ringo_leker`, the accounts of its brand *Ringo*, and the junk link `instagram.com/accounts`.
- **PARASOLLFIX AS**: `facebook.com/Smartfootoriginals` and `instagram.com/smartfootoriginals`, named after the website.
- **WALL-IT AS**: `youtube.com/channel/UCRSZiaTAF2LY9RWUv4Qe-PA`, a channel ID that names nobody.
- 15 of 175 published accounts failed the rule in total.

### The fix (rule now)

An account is published only if it is linked from the verified site **and its handle contains the company's distinctive name**:
- the joined name (for example `sandneselektriske`);
- or, for a one-word name, that word (4+ letters);
- or at least two of the name's distinctive words.

Generic words (`holding`, `invest`, `eiendom`, `stiftelsen`, …) don't count. Domain-name matches and `sameAs` alone are no longer enough.
Platform paths are rejected outright: Instagram `accounts`, `direct`, `about`, `explore`; Facebook `login`, `hashtag`, `pages`, `watch`, `search`;
X `hashtag`, `login`.

### How it was made

New function `social_handle_matches(legal_name, url)` in `signalpost/website.py`:

```python
handle = re.sub(r"[^a-z0-9]", "", ascii_fold(urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]))
words = [t for t in core_tokens(legal_name) if t not in GENERIC and t not in {"stiftelsen", "stiftelse", "co"} and len(t) >= 3]
if "".join(words) in handle:
    return True
if len(words) == 1:
    return len(words[0]) >= 4 and words[0] in handle
return sum(1 for w in words if w in handle) >= 2
```

`extract_site()` now publishes a social account only when `social_handle_matches(...)` is True. The `same_as` and `label` shortcuts were deleted.
The blocklists in `normalize_social()` were extended.

**Effect:** the brand, website-name and opaque accounts above are withheld. Company-named accounts stay (for example `dips_as`, `SodvinAS`,
`danvikfhs`, `advokatchristianwiig`). Known trade-off: a genuine account that uses only one word of a multi-word name, such as
`facebook.com/sollifjellet` for SOLLIFJELLET ALPINSENTER SA, is also withheld under this strict rule.

**Tests:** `test_social_handle_must_name_the_company` (built from the real accounts above).

---

## 3. News must be real, dated posts

### Before (v1)

Any page with JSON-LD `Article` markup and a 15+ character title counted as news, as long as its last URL segment wasn't exactly a page name
like `kontakt`. Old `is_news_item()`:

```python
if len(title.strip()) < 15 or title.strip().casefold() in NAV_WORDS or not path:
    return False
last = ascii_fold(path.split("/")[-1])
return not any(last == t or last.startswith(t + ".") for terms in PAGE_KINDS.values() for t in terms) and last.count("-") >= 1
```

`kontakt-oss` is not exactly `kontakt`, so contact pages passed. There was no requirement that the URL look like a post, and dates read from
`<time>` tags on the news page weren't checked for "modified" or "updated" labels.

**Real examples from the v1 submission:**
- **WALL-IT AS**: "Kontakt oss | WALL-IT" at `wall-it.no/kontakt-oss/`, dated 2017. A contact page, not news.
- **FISHTECH HYGENA AS**: a post at `/2018/08/30/blog-test-1/`, a theme demo slug.

### The fix (rule now)

A news item must:
- have a URL that **looks like a post**: a `/YYYY/MM/` date path, or a parent path segment that is a news, blog, article, press or post section
  (`nyheter`, `aktuelt`, `artikler`, `blogg`, `presse`, `news`, …);
- not be a site page (slug starting with `kontakt-`, `om-oss`, `karriere-`, …), a product, shop, category or tag page, a menu label
  ("Se flere nyheter", "Les mer", "See more news", …) or a demo post (`test`, `sample`, `demo`, `hello-world`, `lorem`);
- carry a **publish** date. A `<time>` element marked "modified", "updated", "oppdatert", "endret" or "sist endret" is skipped. JSON-LD
  continues to use only `datePublished`, never `dateModified`.

### How it was made

`is_news_item()` was rewritten (in `signalpost/website.py`). The new checks are `MENU_TITLE`, `NOT_POST_SEGMENTS`, the site-page and demo-slug
checks, and the post-like-URL requirement:

```python
dated = re.search(r"(^|/)(19|20)\d{2}/\d{1,2}(/|$)", path) is not None
in_section = any(seg.startswith(POST_SECTIONS) for seg in segments[:-1])
return (dated or in_section) and last.count("-") >= 1
```

New function `is_publish_date(time_tag)` rejects modified/updated dates by looking at the tag's `itemprop`, `class` and surrounding text.
`extract_site()` calls it before using a `<time>` date.

**Effect:** the contact page and the demo post are gone. Real posts stay (Equinor `/news/...`, IDEX `/news/...`, Sodvin `/artikler/...`).

**Tests:** `test_news_must_be_a_real_dated_post`, `test_modified_dates_are_not_publish_dates`, `test_site_pages_are_not_news`.

---

## 4. Jobs must be single ads for this company

### Before (v1)

The agent fetched the site's careers page and published its URL as a fact (`careers_page`). The careers link was found from menu text, so it
was sometimes not a careers page at all. JobPosting markup on a website was published without checking that it named this company as
employer. Old code in `extract_site()`:

```python
careers = next((p for p in pages if p.kind == "careers"), None)
if careers:
    d.claim("careers_page", "website", careers.resp.final_url, [ev])
```

**Real examples from the v1 submission (26 careers pages):**
- landing pages such as `framkompetanse.no/jobb-hos-oss` and `maske.no/ledige-stillinger`;
- pages that aren't careers pages at all: `sakki.no/products/fodt`, `bikeriet.no/sykler/elsykler/el-hybrid`, `atlaseiendom.no/omoss`, `kunstsilo.no/no/utstillinger`;
- the parent organisation's pages: `thon.no/karriere/` for Thon Holding, `dnt.no/om-dnt/dnts-arbeid/` for DNT Nord-Trøndelag.

The 4 NAV job ads were already correct: each is one ad, verified by the employer's org number.

### The fix (rule now)

- **Careers landing pages are not published**, and the careers page is no longer fetched.
- A website JobPosting is published only if it has its own URL, is not expired, and its `hiringOrganization` is **this company**: the org
  number, or the same distinctive name. A parent's or sister's vacancy on a shared site is withheld.
- A NAV job always links to the **single ad** (`arbeidsplassen.nav.no/stillinger/stilling/<id>`). If the ad data carries any other link,
  such as a search page, it is replaced.
- NAV matching is unchanged: an ad is published only when `employer.orgnr` is the company or one of its own registered subunits, so a
  parent's vacancies are never matched.

### How it was made

In `signalpost/website.py`, the careers-page claim was deleted, and the JobPosting loop now requires:

```python
if not title or not url or (expires and expires < page.resp.retrieved_at[:10]) or not hiring_org_is_company(node, d):
    continue
```

New function `hiring_org_is_company(node, d)`: True if the org number appears in `hiringOrganization`, or its name has the same distinctive
words as the legal name. In `signalpost/jobs.py`, new function `single_ad_url(ad)` keeps the ad's own link only if it matches the single-ad URL
pattern, and otherwise builds it from the ad's ID.

**Effect:** 26 careers pages → 0. NAV ads: 7 in v2, all single-ad links verified by org number. The count rose from 4 because new ads went live.

**Tests:** `test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs`.

---

## The checks are now automatic

The contract verifier `tools/verify_run.py` gained rule group **R14**, applied to every run:
- every social handle names the company;
- every news item is a dated post;
- no careers landing pages;
- every NAV job links to a single ad.

All 13 verification runs at `a96e0f1` pass R1–R14 (see [TEST_REPORT.md](TEST_REPORT.md)).

## How to verify it yourself

From the repository folder, with the virtual environment set up as in the README (on Windows, use `.venv\Scripts\python.exe` for `python`):

**1. See the exact code changes**

```bash
git diff afc3f0a a96e0f1 -- signalpost/
```

**2. Run the tests**, including the 7 new ones from the audit cases

```bash
python tests/test_agent.py
```

Expected: `47 passed`.

**3. Replay the audited cases against the current code**

```bash
python tools/verify_v2_fixes.py
```

Expected: `17/17 audit cases behave as Builderr asked.`

**4. Count the four problems in the v1 dataset and the v2 dataset**

```bash
git show f49124a:profiles/profiles.jsonl.gz > v1.jsonl.gz
python tools/verify_v2_fixes.py --dataset v1.jsonl.gz
python tools/verify_v2_fixes.py --dataset profiles/profiles.jsonl.gz
```

Expected: v1 shows 57 problems (website 14, socials 15, news 2, jobs 26); v2 shows 0.

**5. Run the agent on the audited companies and look at the result**

```bash
python run.py --input audited.txt --output out_check
```

Put these organisation numbers in `audited.txt`, one per line. They are ASK Spekehus, DNT Nord-Trøndelag, Nordic Toy Team, Parasollfix and WALL-IT:

```bash
python -c "import gzip,json; [print(json.loads(l)['organisation_number']) for l in gzip.open('profiles/profiles.jsonl.gz','rt',encoding='utf-8') if json.loads(l)['legal_identity']['legal_name'] in ('ASK SPEKEHUS AS','DNT NORD-TRØNDELAG','NORDIC TOY TEAM AS','PARASOLLFIX AS','WALL-IT AS')]"
```

Then open `out_check/report.html` and check:
- ASK Spekehus's website is `ambiguous`;
- DNT Nord-Trøndelag shows its page but no social accounts;
- Nordic Toy Team and Parasollfix have no brand-named accounts;
- WALL-IT has no "Kontakt oss" news item;
- no company shows a careers page.

**6. Check one claim by hand.** In `out_check/envelopes.jsonl`, every claim lists `evidence_ids`. The matching evidence record holds the source URL,
retrieval time, content hash and the exact text span that supports the claim.
