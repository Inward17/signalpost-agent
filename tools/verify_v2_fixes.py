#!/usr/bin/env python3
"""Check the four Builderr audit points (version 2 fixes).

    python tools/verify_v2_fixes.py                                  # replay the audited cases against the current code
    python tools/verify_v2_fixes.py --dataset profiles/profiles.jsonl.gz   # scan a profile dataset for the four problems

To compare with version 1:  git show f49124a:profiles/profiles.jsonl.gz > v1.jsonl.gz
                            python tools/verify_v2_fixes.py --dataset v1.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalpost.dossier import Dossier  # noqa: E402
from signalpost.http import Response  # noqa: E402
from signalpost.website import (assess_identity, is_news_item, is_publish_date, legal_name_regex, normalize_social,  # noqa: E402
                                parse_page, section_of_larger_site, social_handle_matches)

NAV_AD = re.compile(r"https://arbeidsplassen\.nav\.no/stillinger/stilling/[0-9a-f-]{36}")


def page(html: str, url: str):
    return parse_page("home", Response(url, url, 200, html.encode(), "text/html; charset=utf-8"))


def dossier(name: str, org: str = "810034882") -> Dossier:
    d = Dossier(org)
    d.entity = {"navn": name, "organisasjonsform": {"kode": "AS"}}
    return d


def replay() -> int:
    """Each check is a real case from Builderr's audit of version 1 (or the exact pattern they described)."""
    checks = []

    # 1. Website must be the company's own, not a parent group or brand site
    v = assess_identity(dossier("ASK SPEKEHUS AS"), [page("<title>ASK Spekehus | ASK Gård</title><body>Spekemat fra gården</body>", "https://askgard.no/")],
                        "official_registry", "askgard.no")
    checks.append(("1 website", "declared brand site with only a brand title (ASK Spekehus -> askgard.no) is not published", v["verdict"] != "exact"))
    v = assess_identity(dossier("ASK SPEKEHUS AS"), [page("<title>ASK</title><body><footer>ASK Spekehus AS</footer></body>", "https://askgard.no/")],
                        "official_registry", "askgard.no")
    checks.append(("1 website", "the same declared site WITH the exact legal name is published", v["verdict"] == "exact"))
    checks.append(("1 website", "dnt.no/nordtrondelag is recognised as a section of a larger site", section_of_larger_site("https://www.dnt.no/nordtrondelag")))
    checks.append(("1 website", "a company's own /no or /home landing path is not a section", not section_of_larger_site("https://www.kunstsilo.no/no")))

    # 2. Social handles must match this company
    for name, url, expected, why in [
        ("NORDIC TOY TEAM AS", "https://facebook.com/Ringobamsen", False, "brand account on the brand site"),
        ("PARASOLLFIX AS", "https://instagram.com/smartfootoriginals", False, "website-name account"),
        ("WALL-IT AS", "https://youtube.com/channel/UCRSZiaTAF2LY9RWUv4Qe-PA", False, "opaque channel ID"),
        ("DIPS AS", "https://linkedin.com/company/dips-as", True, "company-named account"),
        ("SODVIN AS", "https://facebook.com/SodvinAS", True, "company-named account"),
        ("SANDNES ELEKTRISKE SERVICE AS", "https://facebook.com/sandneselektriske", False, "sister/parent account on a subsidiary site"),
        ("AKER AS", "https://linkedin.com/company/akerbp", False, "another company whose handle contains the name"),
        ("DIPS AS", "https://linkedin.com/company/dipsfront", False, "a subsidiary's account on the parent site"),
        ("NORDIC TOY TEAM AS", "https://facebook.com/nordictoyteamgroup", False, "group account"),
    ]:
        checks.append(("2 socials", f"{url} for {name} ({why}) -> {'published' if expected else 'withheld'}",
                       social_handle_matches(name, url) is expected))
    checks.append(("2 socials", "instagram.com/accounts/login is not a profile", normalize_social("https://www.instagram.com/accounts/login/") is None))

    # 3. News must be real, dated posts
    checks.append(("3 news", "'Kontakt oss | WALL-IT' (contact page with article markup) is not news",
                   not is_news_item("Kontakt oss | WALL-IT", "https://wall-it.no/kontakt-oss/", "")))
    checks.append(("3 news", "a demo post slug (blog-test-1) is not news",
                   not is_news_item("Renoveringsprosjekt hos Aarseth", "https://fishtech-hygena.no/2018/08/30/blog-test-1/", "")))
    checks.append(("3 news", "'Se flere nyheter' menu label is not news", not is_news_item("Se flere nyheter fra oss", "https://x.no/nyheter/arkiv-side", "")))
    checks.append(("3 news", "a product page is not news", not is_news_item("Vår nye sofa i eik og lin", "https://x.no/produkter/sofa-eik-lin", "")))
    checks.append(("3 news", "a real post (Sodvin /artikler/...) is news",
                   is_news_item("7 enkle strømgrep før vinteren", "https://www.sodvin.no/privat/artikler/7-enkle-stromgrep", "")))
    times = page("<article><time datetime='2026-01-02' class='published'>2. jan</time></article>"
                 "<article>Oppdatert <time datetime='2026-03-04'>4. mars</time></article>", "https://x.no/nyheter").soup.find_all("time")
    checks.append(("3 news", "a publish date is accepted, an 'Oppdatert' (updated) date is not", [is_publish_date(t) for t in times] == [True, False]))

    from signalpost.http import Client
    from signalpost.website import extract_site
    html = ("<div><a href='/nyheter/forste-sak-om-noe'>Første sak om noe viktig</a><a href='/nyheter/andre-sak-om-noe'>Andre sak om noe viktig</a>"
            "<time datetime='2026-10-01'>1. okt</time></div><ul><li><a href='/p/12345'>Ny avtale med Statens vegvesen signert</a>"
            "<time datetime='2026-09-12'>12. sep</time></li></ul>")
    d = dossier("SANDNES ELEKTRISKE AS")
    extract_site(Client(max_requests=0), d, {"verdict": "exact", "score": 1.0, "reason": "r", "domain": "x.no", "homepage": "https://x.no/", "links": {}},
                 [parse_page("news", Response("https://x.no/nyheter", "https://x.no/nyheter", 200, html.encode(), "text/html"))])
    news = [(c["value"]["date"], c["value"]["url"]) for c in d.claims if c["field"] == "company_news"]
    checks.append(("3 news", "a date shared by several articles is not given to any of them; a list entry with its own date and an unusual URL is kept",
                   news == [("2026-09-12", "https://x.no/p/12345")]))

    # 4. Jobs must be single ads for this company
    from signalpost.website import hiring_org_is_company
    d = dossier("SANDNES ELEKTRISKE AS")
    for employer, expected in [("Sandnes Elektriske AS", True), ("Sandnes Elektriske", False), ("Sandnes Elektriske DA", False),
                               ("Sandnes Elektriske Service AS", False), ("Sandnes Elektriske Holding AS", False)]:
        checks.append(("4 jobs", f"website job for employer {employer!r} -> {'published' if expected else 'withheld'} for Sandnes Elektriske AS",
                       hiring_org_is_company({"hiringOrganization": {"name": employer}}, d) is expected))
    from signalpost.jobs import single_ad_url
    checks.append(("4 jobs", "a NAV search link is replaced by the single-ad URL",
                   single_ad_url({"uuid": "b9aa6260-4ed4-481f-ab32-af5996fe8e55", "link": "https://arbeidsplassen.nav.no/stillinger?q=x"}).endswith("/b9aa6260-4ed4-481f-ab32-af5996fe8e55")))

    failed = 0
    for point, text, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  [{point}] {text}")
        failed += not ok
    print(f"\n{len(checks) - failed}/{len(checks)} audit cases behave as Builderr asked.")
    print("Careers pages and parent-site job markup are covered by tests/test_agent.py::test_job_posting_must_name_this_company_and_careers_pages_are_not_jobs.")
    return 1 if failed else 0


def scan(path: Path) -> int:
    """Count the four audit problems in a profile dataset (one envelope per line, optionally gzipped)."""
    opener = gzip.open if path.suffix == ".gz" else open
    problems = {"1 website": [], "2 socials": [], "3 news": [], "4 jobs": []}
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            name = e["legal_identity"].get("legal_name") or ""
            ev = {x["id"]: x for x in e.get("evidence", [])}
            site = next((c for c in e["claims"] if c["field"] == "official_website"), None)
            if site:
                method = site["value"].get("identity_method", "")
                span = " ".join(ev[i]["claim_span"] for i in site["evidence_ids"] if i in ev)
                name_re = legal_name_regex(name)
                if "declared" in method and "registry phone" not in method and "registered address" not in method \
                        and not re.search(r"\d{3}\s?\d{3}\s?\d{3}", span) and not (name_re and name_re.search(span)):
                    problems["1 website"].append(f"{name}: {site['value']['url']} accepted on a brand title ({span[:60]!r})")
                if section_of_larger_site(site["value"]["url"]):
                    owned = [c["field"] for c in e["claims"] if c["field"] in ("social_profile", "company_news")
                             or (c["field"] == "job_posting" and c["value"].get("source") == "company website")]
                    if owned:
                        problems["1 website"].append(f"{name}: {site['value']['url']} is a section of a larger site but published {sorted(set(owned))}")
            for c in e["claims"]:
                v = c["value"]
                if c["field"] == "social_profile" and not social_handle_matches(name, v["url"]):
                    problems["2 socials"].append(f"{name}: {v['url']}")
                if c["field"] == "company_news" and not is_news_item(v.get("title", ""), v.get("url", ""), "", require_post_url=False):
                    problems["3 news"].append(f"{name}: {v.get('title', '')[:50]!r} {v.get('url')}")
                if c["field"] == "careers_page":
                    problems["4 jobs"].append(f"{name}: careers landing page {v}")
                if c["field"] == "job_posting" and v.get("source") == "NAV Arbeidsplassen" and not NAV_AD.fullmatch(str(v.get("url"))):
                    problems["4 jobs"].append(f"{name}: NAV job is not a single-ad link {v.get('url')}")
    total = 0
    for point, items in problems.items():
        total += len(items)
        print(f"{point}: {len(items)} problem(s)")
        for item in items[:8]:
            print(f"    {item}")
        if len(items) > 8:
            print(f"    ... and {len(items) - 8} more")
    print(f"\nTotal: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, help="scan a profile dataset instead of replaying the audit cases")
    args = ap.parse_args()
    sys.exit(scan(args.dataset) if args.dataset else replay())
