"""Offline checks for the parts that can publish wrong facts. Run: python tests/test_agent.py (or pytest)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalpost.dossier import Dossier  # noqa: E402
from signalpost.envelope import build  # noqa: E402
from signalpost.http import Response, assert_public_url  # noqa: E402
from signalpost.registry import summarize_changes  # noqa: E402
from signalpost.website import assess_identity, domain_guesses, normalize_social, parse_page  # noqa: E402

ENTITY = {"navn": "SANDNES ELEKTRISKE AS", "organisasjonsform": {"kode": "AS"}, "telefon": "51 60 11 22",
          "forretningsadresse": {"adresse": ["Langgata 1"], "postnummer": "4306", "kommune": "SANDNES"}}


def dossier() -> Dossier:
    d = Dossier("810034882")
    d.entity = dict(ENTITY)
    return d


def page(html: str, url: str = "https://www.sandneselektriske.no/"):
    return parse_page("home", Response(url, url, 200, html.encode(), "text/html; charset=utf-8"))


def verdict(html: str, origin: str = "name_derived_domain", domain: str = "sandneselektriske.no") -> dict:
    return assess_identity(dossier(), [page(html)], origin, domain)


def test_orgnr_on_page_is_exact():
    v = verdict("<html><body><footer>Sandnes Elektriske AS · Org.nr 810 034 882 MVA</footer></body></html>")
    assert v["verdict"] == "exact" and v["score"] == 1.0


def test_conflicting_orgnr_rejected_even_with_name():
    v = verdict("<body><p>Sandnes Elektriske AS</p><p>Org.nr: 936 770 851</p><p>Tlf 51 60 11 22</p></body>", origin="official_registry")
    assert v["verdict"] == "rejected"


def test_parked_domain_rejected():
    assert verdict("<title>sandneselektriske.no</title><body>This domain is for sale</body>")["verdict"] == "rejected"


def test_name_only_on_unrelated_domain_is_not_published():
    v = verdict("<title>Elektro</title><body><p>Vi samarbeider med Sandnes Elektriske AS</p></body>", domain="elektrofirma.no")
    assert v["verdict"] == "ambiguous"


def test_name_plus_phone_is_exact():
    v = verdict("<body><h1>Sandnes Elektriske AS</h1><a href='tel:+4751601122'>51 60 11 22</a></body>")
    assert v["verdict"] == "exact" and v["score"] >= 0.95


def test_brand_without_corroboration_on_guessed_domain_is_ambiguous():
    v = verdict("<title>Sandnes Elektriske</title><body>Elektriker i Sandnes</body>")
    assert v["verdict"] == "ambiguous"


def test_english_as_does_not_satisfy_legal_suffix():
    d = dossier()
    d.entity = {"navn": "ASTRA HOLDING AS", "organisasjonsform": {"kode": "AS"}}
    html = "<title>Astra Holding | Long term home for British Businesses</title><body>Astra Holding as a long-term owner</body>"
    v = assess_identity(d, [page(html, "https://www.astraholding.com/")], "name_derived_domain", "astraholding.com")
    assert v["verdict"] != "exact", v


def test_shared_phone_on_registry_site_is_not_exact():
    d = dossier()
    d.entity = {"navn": "VESTGARD INVEST AS", "organisasjonsform": {"kode": "AS"}, "telefon": "76158008"}
    html = "<title>XPartner</title><body>XPartner Vesteralen, tlf 76 15 80 08</body>"
    v = assess_identity(d, [page(html, "https://xpartner.as/")], "official_registry", "xpartner.as")
    assert v["verdict"] == "ambiguous", v


def test_orgnr_on_group_listing_page_is_ambiguous():
    html = "<body><li>Sandnes Elektriske AS org.nr 810 034 882</li><li>Bergen Elektro AS org.nr 912 345 678</li></body>"
    v = assess_identity(dossier(), [page(html, "https://elgruppen.no/")], "name_derived_domain", "elgruppen.no")
    assert v["verdict"] == "ambiguous", v


def test_domain_guesses_skip_generic_names():
    assert domain_guesses("HOLDING AS") == []
    assert "sandneselektriske.no" in domain_guesses("SANDNES ELEKTRISKE AS")


def test_social_normalisation_rejects_share_links():
    assert normalize_social("https://www.facebook.com/sharer/sharer.php?u=x") is None
    assert normalize_social("https://no.linkedin.com/company/dips-as/about") == {"platform": "linkedin", "url": "https://linkedin.com/company/dips-as"}


def test_ssrf_guard():
    for bad in ("http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "https://example.com:8080/"):
        try:
            assert_public_url(bad)
        except ValueError:
            continue
        raise AssertionError(f"not blocked: {bad}")


def test_registry_change_summary_drops_housekeeping():
    ops = [{"op": "replace", "path": "/registreringsdatoAntallAnsatteEnhetsregisteret", "value": "2026-10-13"},
           {"op": "replace", "path": "/antallAnsatte", "value": 351}]
    assert summarize_changes(ops) == [{"field": "registered employees", "op": "replace", "value": 351}]


def _envelope(d: Dossier, previous=None, now="2026-10-16T00:00:00Z"):
    return build(d, run={"run_id": "t"}, previous=previous, now=now)


def test_refresh_idempotent_change_and_stale_carry():
    d1 = dossier()
    d1.section("identity", "available", "x")
    ev = d1.add_evidence(None, "official_registry", "antallAnsatte: 10", url="https://x")
    d1.claim("registered_employees", "identity", 10, [ev])
    d1.section("jobs", "available", "x")
    d1.claim("job_posting", "jobs", {"title": "Elektriker"}, [ev], key="job|1")
    first = json.loads(json.dumps(_envelope(d1)))
    assert first["changes"] == [] and first["refresh"]["is_first_run"]

    same = dossier()
    same.section("identity", "available", "x")
    same.claim("registered_employees", "identity", 10, [ev])
    same.section("jobs", "available", "x")
    same.claim("job_posting", "jobs", {"title": "Elektriker"}, [ev], key="job|1")
    assert _envelope(same, first)["changes"] == []  # same snapshot: no false changes

    changed = dossier()
    changed.section("identity", "available", "x")
    changed.claim("registered_employees", "identity", 12, [ev])
    changed.section("jobs", "not_available", "checked, none")
    env = _envelope(changed, first)
    kinds = sorted(c["change_type"] for c in env["changes"])
    assert kinds == ["changed_registered_employees", "closed_job"], kinds
    assert env["changes"][0]["old_evidence"], "previous evidence preserved on change"

    blocked = dossier()
    blocked.section("identity", "available", "x")
    blocked.claim("registered_employees", "identity", 10, [ev])
    blocked.section("jobs", "blocked", "feed down")
    env = _envelope(blocked, first)
    stale = [c for c in env["claims"] if c.get("stale")]
    assert env["changes"] == [] and len(stale) == 1  # failed refresh keeps last value, flags it


def test_missing_financials_never_zero():
    d = dossier()
    env = _envelope(d)
    assert not [c for c in env["claims"] if c["section"] == "financials"]
    assert env["sections"]["financials"]["state"] == "not_available"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} passed")
