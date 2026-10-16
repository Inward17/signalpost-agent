"""Official-website discovery, exact-entity identity gate and company-owned fact extraction."""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import tldextract
from bs4 import BeautifulSoup

from .dossier import Dossier
from .http import BudgetExhausted, Client, Response, resolves

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())  # bundled public-suffix snapshot: no network call
LEGAL_SUFFIXES = {"as", "asa", "ans", "da", "enk", "sa", "ba", "nuf", "iks", "ks", "sti", "bbl", "brl", "sf", "kf"}
GENERIC = {"og", "and", "the", "i", "&", "norge", "norway", "holding", "invest", "eiendom", "eiendommer", "group", "gruppen"}
DIRECTORY_HOSTS = ("proff.no", "purehelp.no", "gulesider.no", "1881.no", "brreg.no", "finn.no", "facebook.com", "linkedin.com",
                   "instagram.com", "youtube.com", "wikipedia.org", "regnskapstall.no", "forvalt.no", "kompass.com", "bizzdo.no",
                   "allabolag.se", "firmasok.no", "hvaskjer.no", "nav.no", "google.com", "bing.com", "x.com", "twitter.com", "tiktok.com")
PARKED = ("domain is for sale", "domene til salgs", "domenet er til salgs", "this domain may be for sale", "hugedomains", "parked",
          "her flytter snart en ny gjest", "buy this domain", "under construction", "kommer snart", "coming soon", "default web site page",
          "website is under construction", "web hosting", "hosted by one.com", "welcome to nginx", "it works!")
PAGE_KINDS = {
    "contact": ("kontakt", "contact", "finn-oss", "find-us"),
    "about": ("om-oss", "om_oss", "omoss", "about", "om oss", "hvem-er-vi", "selskapet", "company"),
    "news": ("nyheter", "aktuelt", "news", "presse", "press", "blogg", "blog", "artikler", "nyhet"),
    "careers": ("karriere", "career", "jobb", "jobs", "ledige-stillinger", "stillinger", "rekruttering", "jobbe-hos", "work-with-us"),
}
SOCIAL = {"linkedin.com": "linkedin", "facebook.com": "facebook", "instagram.com": "instagram", "x.com": "x", "twitter.com": "x",
          "youtube.com": "youtube", "tiktok.com": "tiktok"}
GENERIC_MAILBOX = re.compile(r"^(post|postmottak|info|kontakt|contact|firmapost|salg|sales|hei|hello|office|kontor|kundeservice|service|support|"
                             r"booking|bestilling|ordre|order|admin|mail|faktura|regnskap|resepsjon|marked|marketing|presse|press|jobb|hr)$")


def ascii_fold(text: str) -> str:
    text = str(text or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", ascii_fold(text))


def core_tokens(name: str) -> list[str]:
    return [t for t in tokens(name) if t not in LEGAL_SUFFIXES]


def registered_domain(url_or_host: str) -> str:
    host = urllib.parse.urlparse(url_or_host if "//" in url_or_host else "//" + url_or_host).hostname or ""
    return _EXTRACT(host).top_domain_under_public_suffix.lower()


def normalize_url(value: str) -> str | None:
    value = str(value or "").strip()
    if not value or " " in value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    return f"{parsed.scheme}://{parsed.hostname}/" if parsed.hostname and "." in parsed.hostname else None


def domain_guesses(name: str) -> list[str]:
    core = core_tokens(name)
    if not core or len("".join(core)) < 4 or all(t in GENERIC for t in core):
        return []
    variants = ["".join(core), "-".join(core)]
    if len(core) > 2:
        distinct = [t for t in core if t not in GENERIC]
        variants += ["".join(distinct), "".join(core[:2])]
    out: list[str] = []
    for v in dict.fromkeys(variants):
        if len(v) >= 4:
            out += [f"{v}.no", f"{v}.com"]
    return out[:6]


# -- identity evidence ------------------------------------------------------------
def _orgnr_regex(org: str) -> re.Pattern[str]:
    sep = r"[\s. \-]?"
    return re.compile(rf"(?<!\d){org[:3]}{sep}{org[3:6]}{sep}{org[6:]}(?!\d)")


_ORG_LABELLED = re.compile(r"(?:org\.?\s*(?:nr|nummer|no)|organisasjons\s*(?:nr|nummer)|foretaksregisteret|vat|mva|business\s*id)"
                           r"[^0-9]{0,25}(?:no\s*)?(\d{3}[\s. ]?\d{3}[\s. ]?\d{3})(?!\d)", re.I)


def valid_orgnr(digits: str) -> bool:
    """Norwegian organisation-number MOD11 check (weights 3,2,7,6,5,4,3,2)."""
    if len(digits) != 9 or not digits.isdigit() or digits[0] not in "89":
        return False
    rest = sum(int(a) * w for a, w in zip(digits[:8], (3, 2, 7, 6, 5, 4, 3, 2))) % 11
    check = 0 if rest == 0 else 11 - rest
    return check != 10 and check == int(digits[8])


def _phone_digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


@dataclass
class Page:
    kind: str
    resp: Response
    soup: BeautifulSoup
    text: str
    jsonld: list[Any] = field(default_factory=list)


def parse_page(kind: str, resp: Response) -> Page:
    raw = resp.text()
    soup = BeautifulSoup(raw, "html.parser")
    jsonld = []
    for node in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            jsonld.append(json.loads(node.string or node.get_text() or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return Page(kind, resp, soup, text, jsonld)


def walk_jsonld(node: Any, types: set[str]) -> list[dict[str, Any]]:
    found = []
    if isinstance(node, dict):
        kind = node.get("@type")
        if set(kind if isinstance(kind, list) else [kind]) & types:
            found.append(node)
        for child in node.values():
            found += walk_jsonld(child, types)
    elif isinstance(node, list):
        for child in node:
            found += walk_jsonld(child, types)
    return found


ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "ProfessionalService", "Store", "Restaurant", "HomeAndConstructionBusiness",
             "AutomotiveBusiness", "LegalService", "AccountingService", "MedicalBusiness", "Dentist", "RealEstateAgent", "FinancialService"}


def assess_identity(d: Dossier, pages: list[Page], origin: str, domain: str) -> dict[str, Any]:
    """Return verdict exact|ambiguous|rejected with the deciding span. Search rank or domain name alone never decides."""
    org = d.org
    legal = d.entity.get("navn") or ""

    core = core_tokens(legal)
    org_re = _orgnr_regex(org)
    phone = _phone_digits(d.entity.get("telefon") or d.entity.get("mobil"))
    addr = d.entity.get("forretningsadresse") or {}
    street = " ".join(tokens(" ".join(addr.get("adresse") or [])))
    postcode = addr.get("postnummer") or ""
    other_orgs: set[str] = set()
    best: dict[str, Any] = {"verdict": "ambiguous", "score": 0.3, "reason": "no exact-entity evidence on captured pages"}
    name_hit = brand_hit = contact_hit = org_hit = None
    name_re = legal_name_regex(legal)
    domain_label = domain.split(".")[0].replace("-", "")
    name_domain = bool(core) and domain_label in {"".join(core), "".join(t for t in core if t not in GENERIC), "".join(core[:2])}
    for page in pages:
        text, low = page.text, ascii_fold(page.text)
        raw_html = page.resp.text()
        if any(marker in low for marker in PARKED) and len(text) < 3000:
            return {"verdict": "rejected", "score": 0.05, "reason": f"parked / placeholder page at {page.resp.final_url}", "page": page.resp.final_url}
        labelled = {re.sub(r"\D", "", f) for f in _ORG_LABELLED.findall(text)}
        page_others = {x for x in labelled if x != org and x not in d.subunit_orgs}
        visible = org_re.search(text)
        m = visible or org_re.search(raw_html)
        owned = ownership_context(page, org_re)  # footer/address text, contact/about page text, or its JSON-LD Organization
        if m and (not org_hit or (owned and not org_hit["owned"])):
            span = (text[max(0, m.start() - 80): m.end() + 40] if visible else m.group(0)).strip()
            # hidden-markup hits (script data, attributes) are weaker: a chain site can embed every member's number
            listed = {x for x in re.findall(r"(?<!\d)(\d{9})(?!\d)", raw_html) if x != org and x not in d.subunit_orgs and valid_orgnr(x)}
            org_hit = {"page": page.resp.final_url, "span": span, "visible": bool(visible), "owned": owned,
                       "group_page": len(page_others) >= 1 or len(listed) >= 3}
        other_orgs |= page_others
        for node in walk_jsonld(page.jsonld, ORG_TYPES):
            for key in ("vatID", "taxID", "identifier", "leiCode"):
                digits = re.sub(r"\D", "", json.dumps(node.get(key, "")))[-9:]
                if len(digits) == 9 and digits != org:
                    other_orgs.add(digits)
        norm_text = " ".join(tokens(text))
        nm = name_re.search(text) if name_re else None
        if nm:
            name_hit = name_hit or {"page": page.resp.final_url, "span": text[max(0, nm.start() - 40): nm.end() + 40]}
        title = " ".join([page.soup.title.get_text(" ") if page.soup.title else "",
                          *[str(m.get("content") or "") for m in page.soup.select('meta[property="og:site_name"], meta[property="og:title"]')]])
        if core and set(core) <= set(tokens(title)):
            brand_hit = brand_hit or {"page": page.resp.final_url, "span": title.strip()[:200]}
        compact = re.sub(r"[\s .\-()]", "", text)
        if phone and re.search(rf"(?<!\d)(?:\+47|0047)?{phone}(?!\d)", compact):
            contact_hit = contact_hit or {"page": page.resp.final_url, "span": f"registry phone {phone} appears on page"}
        elif street and postcode and f" {street} " in f" {norm_text} " and postcode in text:
            contact_hit = contact_hit or {"page": page.resp.final_url, "span": f"registered address '{' '.join(addr.get('adresse') or [])}, {postcode}' appears on page"}
    # Declared = the company itself named this site to an official source (Brønnøysund, or the employer field of an ad whose
    # orgnr is the company). A contact e-mail domain from an ad is NOT declared: it may belong to a recruiter.
    declared = origin in {"official_registry", "nav_employer_homepage"}
    # Two questions: is the page about this company (org number present), and is the DOMAIN the company's own?
    # A domain that merely matches the name does not prove ownership (same-name companies exist), so outside declared sites
    # the number must sit where the site states its OWN identity: footer/address, contact/about page, its JSON-LD Organization.
    org_reason = None
    # A page listing several entities' numbers (group/chain/portfolio) proves nothing about which one owns the site, unless the
    # company itself declared this name-matching site to an official source.
    if org_hit and (not org_hit["group_page"] or (declared and name_domain)):
        if declared:
            return {"verdict": "exact", "score": 1.0, "reason": "organisation number on the site the company declared to an official source" +
                    ("" if org_hit["visible"] else " (in page markup)"), **org_hit}
        if org_hit["owned"]:
            return {"verdict": "exact", "score": 1.0, "reason": "organisation number in the site's own identity block (footer, contact/about page or structured data)", **org_hit}
        org_reason = "organisation number mentioned on the site but outside its own identity block (article, client list or script data)"
    elif org_hit:
        org_reason = "organisation number only in hidden markup or on a page listing several entities (group/chain/portfolio page)"
    if org_reason and other_orgs:  # the company's number among others: a group/listing page, not a different owner
        return {"verdict": "ambiguous", "score": 0.7, "reason": "organisation number listed alongside other entities' numbers (group/portfolio page)", **org_hit}
    if other_orgs:
        return {"verdict": "rejected", "score": 0.1, "page": pages[0].resp.final_url,
                "reason": f"site states a different organisation number ({', '.join(sorted(other_orgs))}): parent, sister or unrelated entity"}
    if name_hit and contact_hit and (name_domain or declared):
        return {"verdict": "exact", "score": 0.97, "reason": "exact legal name plus registry phone/address on site", **contact_hit}
    if declared and (name_hit or brand_hit):
        hit = name_hit or brand_hit
        return {"verdict": "exact", "score": 0.92, "reason": f"site declared by {origin.replace('_', ' ')} and its legal/brand name appears on page", **hit}
    if org_reason:
        return {"verdict": "ambiguous", "score": 0.7, "reason": org_reason, **org_hit}
    if name_hit or brand_hit or contact_hit:
        best = {"verdict": "ambiguous", "score": 0.6, "reason": "name or contact match only: possibly a related, group or same-name entity", **(name_hit or brand_hit or contact_hit)}
    return best


def ownership_context(page: Page, org_re: re.Pattern[str]) -> bool:
    """True when the org number appears where a site states its OWN identity: footer/address block, a contact or
    about page, or the page's JSON-LD Organization node."""
    if page.kind in ("contact", "about"):
        return bool(org_re.search(page.text))
    blocks = page.soup.find_all(["footer", "address"]) + page.soup.select('[class*="footer" i], [id*="footer" i], [class*="colophon" i]')
    if any(org_re.search(b.get_text(" ", strip=True)) for b in blocks):
        return True
    return any(org_re.search(json.dumps(node, ensure_ascii=False)) for node in walk_jsonld(page.jsonld, ORG_TYPES))


def legal_name_regex(legal: str) -> re.Pattern[str] | None:
    """Legal name with its legal-form suffix in capitals ('Astra Holding AS'), so English 'as' never satisfies it."""
    words = re.findall(r"[^\W_]+", legal)
    if not words:
        return None
    suffix = words[-1] if words[-1].lower() in LEGAL_SUFFIXES else None
    body = words[:-1] if suffix else words
    if not body:
        return None
    pattern = r"(?<!\w)(?i:" + r"[\W_]{0,3}".join(map(re.escape, body)) + ")"
    if suffix:
        pattern += r"[\s,.]{1,3}" + re.escape(suffix.upper()) + r"(?!\w)"
    return re.compile(pattern)


# -- crawling -----------------------------------------------------------------
def _pick_links(page: Page, domain: str) -> dict[str, str]:
    chosen: dict[str, str] = {}
    for anchor in page.soup.select("a[href]"):
        url = urllib.parse.urljoin(page.resp.final_url, str(anchor.get("href") or ""))
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or registered_domain(url) != domain:
            continue
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
        if clean.rstrip("/") == page.resp.final_url.split("?")[0].rstrip("/"):
            continue
        hay = ascii_fold(parsed.path + " " + anchor.get_text(" ", strip=True))
        for kind, terms in PAGE_KINDS.items():
            if kind not in chosen and any(t in hay for t in terms):
                chosen[kind] = clean
    return chosen


def fetch_page(client: Client, url: str, kind: str, domain: str) -> Page | None:
    resp = client.get(url, accept="text/html,application/xhtml+xml", check_robots=True)
    if not resp.ok or "html" not in resp.content_type.lower() or registered_domain(resp.final_url) != domain:
        return None
    return parse_page(kind, resp)


def try_site(client: Client, d: Dossier, candidate: dict[str, str]) -> tuple[dict[str, Any], list[Page]] | None:
    url = normalize_url(candidate["url"])
    if not url:
        return None
    domain = registered_domain(url)
    if not domain or any(domain == h or domain.endswith("." + h) for h in DIRECTORY_HOSTS):
        return None
    if not client.robots_allowed(url):
        return {"verdict": "blocked", "reason": f"robots.txt disallows {url}", "page": url}, []
    resp = client.get(url, accept="text/html,application/xhtml+xml")
    if not resp.ok and url.startswith("https://"):
        resp = client.get("http://" + url[8:], accept="text/html,application/xhtml+xml")
    if not resp.ok or "html" not in resp.content_type.lower():
        return {"verdict": "unreachable", "reason": f"{url}: {resp.error or resp.content_type}", "page": url}, []
    final_domain = registered_domain(resp.final_url)  # a cross-domain redirect is assessed on where it lands...
    origin = candidate["origin"] if final_domain == domain else "redirect_target"  # ...and does not inherit the candidate's trust
    home = parse_page("home", resp)
    pages = [home]
    links = _pick_links(home, final_domain)
    verdict = assess_identity(d, pages, origin, final_domain)
    for kind in ("contact", "about"):  # proof pages only while proof is missing
        if verdict["verdict"] == "exact" and verdict["score"] >= 0.97 or verdict["verdict"] == "rejected":
            break
        if kind in links:
            page = fetch_page(client, links[kind], kind, final_domain)
            if page:
                pages.append(page)
                verdict = assess_identity(d, pages, origin, final_domain)
    verdict["domain"] = final_domain
    verdict["homepage"] = resp.final_url
    verdict["links"] = links
    return verdict, pages


def brave_candidates(client: Client, d: Dossier) -> list[dict[str, str]]:
    key = os.environ.get("BRAVE_API_KEY")
    if not key or not d.entity.get("navn"):
        return []
    cost = float(os.environ.get("BRAVE_COST_PER_QUERY", "0.005"))
    try:
        client.reserve_cost(cost)  # refused before the request if it would exceed the run's cost ceiling
    except BudgetExhausted:
        return []
    d.cost_usd += cost
    q = urllib.parse.quote(f'"{d.entity["navn"]}"')
    resp = client.get(f"https://api.search.brave.com/res/v1/web/search?q={q}&country=no&count=10",
                      headers={"X-Subscription-Token": key}, accept="application/json")
    if not resp.ok:
        return []
    # search results are candidates only; nothing from the result snippet is stored or published
    urls = [r.get("url", "") for r in (resp.json().get("web") or {}).get("results", [])]
    return [{"url": u, "origin": "search_candidate"} for u in urls[:4]]


# -- extraction from a verified site ------------------------------------------------
def normalize_social(url: str) -> dict[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("no.").removeprefix("m.")
    platform = next((p for h, p in SOCIAL.items() if host == h or host.endswith("." + h)), None)
    parts = [p for p in parsed.path.split("/") if p]
    if not platform or not parts:
        return None
    first = parts[0].casefold()
    if platform == "linkedin" and (first not in ("company", "school", "showcase") or len(parts) < 2):
        return None
    if platform == "facebook" and first in {"sharer", "sharer.php", "share.php", "dialog", "plugins", "policy.php", "privacy", "groups", "events", "profile.php", "tr"}:
        return None
    if platform == "instagram" and first in {"p", "reel", "reels", "stories", "explore"}:
        return None
    if platform == "x" and (first in {"intent", "share", "home", "search", "i"} or len(parts) != 1):
        return None
    if platform == "youtube" and not (first in ("channel", "user", "c") or first.startswith("@")):
        return None
    if platform == "tiktok" and not first.startswith("@"):
        return None
    keep = parts[:2] if platform == "linkedin" or (platform == "youtube" and not first.startswith("@")) else parts[:1]
    canonical = {"x": "x.com"}.get(platform, platform + ".com")
    return {"platform": platform, "url": f"https://{canonical}/{'/'.join(keep)}"}


def extract_site(client: Client, d: Dossier, verdict: dict[str, Any], pages: list[Page]) -> None:
    domain = verdict["domain"]
    home = pages[0]
    proof_page = next((p for p in pages if p.resp.final_url == verdict.get("page")), home)
    proof_ev = d.add_evidence(proof_page.resp, "company_owned", verdict.get("span") or verdict["reason"])
    d.claim("official_website", "website", {"url": verdict["homepage"], "domain": domain, "identity_method": verdict["reason"],
            "identity_score": verdict["score"]}, [proof_ev], key="official_website", confidence=verdict["score"])
    d.section("website", "available", f"{verdict['homepage']} verified: {verdict['reason']}")
    links = verdict.get("links") or {}
    for kind in ("news", "careers"):
        if kind in links and client.remaining() > 50:
            page = fetch_page(client, links[kind], kind, domain)
            if page:
                pages.append(page)

    # description / brand
    meta = home.soup.select_one('meta[name="description"]') or home.soup.select_one('meta[property="og:description"]')
    description = str(meta.get("content") or "").strip() if meta else ""
    if len(description) < 40:
        about = next((p for p in pages if p.kind == "about"), None)
        para = next((p.get_text(" ", strip=True) for p in (about or home).soup.find_all("p") if len(p.get_text(strip=True)) > 80), "")
        description = para
    if description:
        description = re.sub(r"\s+", " ", description)[:400]
        ev = d.add_evidence(home.resp, "company_owned", description)
        d.claim("website_description", "website", description, [ev], method="meta_description_or_first_paragraph",
                note="company's own description (promotional copy, not an independent claim)")
    site_name = home.soup.select_one('meta[property="og:site_name"]')
    brand = str(site_name.get("content") or "").strip() if site_name else ""
    if brand and set(tokens(brand)) != set(tokens(d.entity.get("navn") or "")) and len(brand) < 80:
        ev = d.add_evidence(home.resp, "company_owned", f'og:site_name = "{brand}"')
        d.claim("public_brand", "identity", brand, [ev], method="og:site_name")

    # social profiles linked from the verified site (company-owned outbound links)
    core = "".join(core_tokens(d.entity.get("navn") or ""))
    label = domain.split(".")[0].replace("-", "")
    socials: dict[str, tuple[dict[str, str], Page]] = {}
    same_as: set[str] = set()
    for page in pages:
        for node in walk_jsonld(page.jsonld, ORG_TYPES):
            same = node.get("sameAs")
            for url in same if isinstance(same, list) else [same]:
                if isinstance(url, str) and (s := normalize_social(url)):
                    same_as.add(s["url"])
                    socials.setdefault(s["url"], (s, page))
        for a in page.soup.select("a[href]"):
            s = normalize_social(urllib.parse.urljoin(page.resp.final_url, str(a.get("href"))))
            if s:
                socials.setdefault(s["url"], (s, page))
    published = 0
    for url, (s, page) in socials.items():
        handle = re.sub(r"[^a-z0-9]", "", ascii_fold(urllib.parse.urlparse(url).path.split("/")[-1]))
        if url in same_as or (core and (core in handle or handle in core and len(handle) >= 4)) or (label and len(label) >= 4 and label in handle):
            ev = d.add_evidence(page.resp, "company_owned", f"verified site links to {url}")
            d.claim("social_profile", "social_profiles", s, [ev], key=f"social|{url}", method="outbound_link_from_verified_site")
            published += 1
    d.section("social_profiles", "available" if published else "not_available",
              f"{published} profile(s) linked from verified site" + (f"; {len(socials) - published} unmatched link(s) withheld" if len(socials) > published else ""))

    # contact points on the company's own domain
    emails: dict[str, Page] = {}
    phones: dict[str, Page] = {}
    for page in pages:
        for m in re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", page.text + " " + " ".join(a.get("href", "") for a in page.soup.select('a[href^="mailto:"]'))):
            local, _, host = m.group(0).lower().partition("@")
            if registered_domain(host) == domain and GENERIC_MAILBOX.match(local):
                emails.setdefault(f"{local}@{host}", page)
        if page.kind in ("home", "contact"):
            for a in page.soup.select('a[href^="tel:"]')[:3]:
                digits = _phone_digits(a.get("href"))
                if digits:
                    phones.setdefault(digits, page)
    for email, page in list(emails.items())[:3]:
        d.claim("contact_email", "contact", email, [d.add_evidence(page.resp, "company_owned", email)], key=f"email|{email}")
    for phone, page in list(phones.items())[:2]:
        d.claim("contact_phone", "contact", f"+47 {phone[:3]} {phone[3:5]} {phone[5:]}", [d.add_evidence(page.resp, "company_owned", f"tel:{phone}")], key=f"phone|{phone}")
    if emails or phones or d.values("registry_phone"):
        d.section("contact", "available", "contact points from registry and/or verified site")

    # dated activity: JSON-LD articles and <time> elements on the news page, plus company job postings
    activity = 0
    seen: set[str] = set()
    for page in pages:
        for node in walk_jsonld(page.jsonld, {"NewsArticle", "Article", "BlogPosting", "PressRelease"}):
            date = str(node.get("datePublished") or "")[:10]
            title = str(node.get("headline") or node.get("name") or "").strip()
            url = node.get("url") or page.resp.final_url
            if date and isinstance(url, str) and url not in seen and is_news_item(title, url, page.resp.final_url):
                seen.add(url)
                ev = d.add_evidence(page.resp, "company_owned", f"{date} {title}")
                d.claim("company_news", "public_activity", {"date": date, "title": title[:200], "url": url, "date_type": "published"},
                        [ev], key=f"news|{url}", effective_date=date, method="jsonld_article")
                activity += 1
        if page.kind == "news":
            for t in page.soup.find_all("time")[:20]:
                date = str(t.get("datetime") or "")[:10]
                container = t.find_parent(["article", "li", "div"])
                link = container.find("a", href=True) if container else None
                if not (re.match(r"\d{4}-\d{2}-\d{2}$", date) and link):
                    continue
                url = urllib.parse.urljoin(page.resp.final_url, link["href"])
                title = link.get_text(" ", strip=True) or (container.find(["h2", "h3"]).get_text(" ", strip=True) if container.find(["h2", "h3"]) else "")
                if url in seen or registered_domain(url) != domain or not is_news_item(title, url, page.resp.final_url):
                    continue
                seen.add(url)
                ev = d.add_evidence(page.resp, "company_owned", f"{date} {title}")
                d.claim("company_news", "public_activity", {"date": date, "title": title[:200], "url": url, "date_type": "published"},
                        [ev], key=f"news|{url}", effective_date=date, method="news_page_time_element")
                activity += 1
        for node in walk_jsonld(page.jsonld, {"JobPosting"}):
            title = str(node.get("title") or "").strip()
            expires = str(node.get("validThrough") or "")[:10] or None
            if title and not (expires and expires < page.resp.retrieved_at[:10]):  # expired postings are not current hiring
                ev = d.add_evidence(page.resp, "company_owned", f"JobPosting: {title}")
                d.claim("job_posting", "jobs", {"title": title, "url": node.get("url") or page.resp.final_url,
                        "published": str(node.get("datePosted") or "")[:10] or None, "expires": expires,
                        "source": "company website"}, [ev], key=f"job|site|{node.get('url') or title}", method="jsonld_jobposting")
                d.section("jobs", "available", "JobPosting markup on verified company site")
    careers = next((p for p in pages if p.kind == "careers"), None)
    if careers:
        ev = d.add_evidence(careers.resp, "company_owned", f"careers page: {careers.soup.title.get_text(' ', strip=True)[:120] if careers.soup.title else careers.resp.final_url}")
        d.claim("careers_page", "website", careers.resp.final_url, [ev])
    if activity:
        d.section("public_activity", "available", f"{activity} dated item(s) from verified company site")


NAV_WORDS = {"hjem", "home", "forside", "kontakt", "contact", "om oss", "about", "nyheter", "news", "aktuelt", "blogg", "blog", "les mer", "read more"}


def is_news_item(title: str, url: str, page_url: str) -> bool:
    """An article, not a site page that happens to carry Article markup ('Hjem', 'Kontakt', the homepage itself)."""
    path = urllib.parse.urlparse(url).path.strip("/")
    if len(title.strip()) < 15 or title.strip().casefold() in NAV_WORDS or not path:
        return False
    last = ascii_fold(path.split("/")[-1])
    return not any(last == t or last.startswith(t + ".") for terms in PAGE_KINDS.values() for t in terms) and last.count("-") >= 1


def research_website(client: Client, d: Dossier, allow_guessing: bool = True) -> None:
    if not d.entity.get("navn"):
        d.section("website", "failed", "no legal identity to verify a website against")
        return
    tried: set[str] = set()
    outcomes: list[str] = []
    ambiguous: dict[str, Any] | None = None
    blocked = False
    transient: str | None = None  # 429/403/5xx/timeout: we could not check, which is not the same as "not there"
    refused: str | None = None

    def candidates():
        yield from list(d.website_candidates)
        if allow_guessing:
            for host in domain_guesses(d.entity["navn"]):
                if resolves(host):  # DNS only; no HTTP request unless the name resolves
                    yield {"url": host, "origin": "name_derived_domain"}
        yield from brave_candidates(client, d)

    for cand in candidates():
        url = normalize_url(cand["url"])
        dom = registered_domain(url) if url else ""
        if not dom or dom in tried:
            continue
        tried.add(dom)
        result = try_site(client, d, cand)
        if not result:
            continue
        verdict, pages = result
        outcomes.append(f"{dom} ({cand['origin']}): {verdict['verdict']} - {verdict['reason']}")
        if verdict["verdict"] == "exact":
            extract_site(client, d, verdict, pages)
            d.section("website", "available", f"{verdict['homepage']} verified: {verdict['reason']}", candidates_checked=outcomes)
            return
        if verdict["verdict"] == "ambiguous" and not ambiguous:
            ambiguous = verdict
        blocked = blocked or verdict["verdict"] == "blocked"
        known = cand["origin"] in {"official_registry", "nav_employer_homepage"} or dom == d.previous_site_domain
        plausible = known or (cand["origin"] == "name_derived_domain" and dom.endswith(".no"))  # a random .com bot wall says nothing
        if plausible and verdict["verdict"] == "unreachable" and re.search(r"HTTP (403|429)", verdict["reason"]):
            refused = refused or verdict["reason"]  # the likely company site refused us: "blocked", not "nothing there"
        if known and verdict["verdict"] == "unreachable" and "did not resolve" not in verdict["reason"] and not re.search(r"HTTP 40[45]|HTTP 410", verdict["reason"]):
            transient = transient or verdict["reason"]
        if len(tried) >= 6:
            break
    if ambiguous:
        d.section("website", "ambiguous", f"candidate {ambiguous.get('homepage')} not published: {ambiguous['reason']}", candidates_checked=outcomes)
    elif blocked:
        d.section("website", "blocked", "candidate site disallows automated access (robots.txt)", candidates_checked=outcomes)
    elif refused and not transient:
        d.section("website", "blocked", f"candidate site refused automated access this run: {refused}", candidates_checked=outcomes)
        d.section("social_profiles", "blocked", "website could not be checked this run")
        return
    elif transient:
        state = "blocked" if re.search(r"HTTP (403|429)", transient) else "failed"
        d.section("website", state, f"candidate site could not be checked this run: {transient}", candidates_checked=outcomes)
        d.section("social_profiles", state, "website could not be checked this run")
        return
    else:
        d.section("website", "not_available", "no candidate domain resolved to this exact legal entity" if tried else
                  "no registry website and no name-derived domain resolved", candidates_checked=outcomes)
    for name in ("social_profiles",):
        d.section(name, "not_available", "no verified company website to source company-owned profiles from")
