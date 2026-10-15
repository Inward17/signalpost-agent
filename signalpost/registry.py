"""Brønnøysund collectors (NLOD 2.0): entity, annual accounts, roles, subunits, announcements."""
from __future__ import annotations

import re
from typing import Any

from .dossier import Dossier
from .http import Client

ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES = ENTITY + "/roller"
SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
ANNOUNCEMENTS = "https://w2.brreg.no/kunngjoring/hent_nr.jsp?orgnr={org}"
ANNOUNCEMENT_ITEM = "https://w2.brreg.no/kunngjoring/hent_en.jsp?kid={kid}&sokeverdi={org}&spraak=nb"
JSON = "application/json"


def _get(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _address(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [", ".join(addr.get("adresse") or []), " ".join(filter(None, [addr.get("postnummer"), addr.get("poststed")]))]
    if addr.get("landkode") and addr.get("landkode") != "NO":
        parts.append(addr.get("land") or addr["landkode"])
    return ", ".join(p for p in parts if p) or None


def _state_for(resp, what: str) -> tuple[str, str]:
    if resp.status in (404, 410):
        return "not_available", f"{what}: registry returned HTTP {resp.status} (no record)"
    if resp.status in (401, 403, 429) or (resp.error or "").startswith("blocked"):
        return "blocked", f"{what}: {resp.error}"
    return "failed", f"{what}: {resp.error or resp.status}"


# -- identity -----------------------------------------------------------------
def fetch_entity(client: Client, d: Dossier) -> None:
    resp = client.get(ENTITY.format(org=d.org), accept=JSON)
    if not resp.ok:
        state, reason = _state_for(resp, "live entity")
        if d.seed.get("name"):
            # fall back to the frozen registry snapshot row supplied with the batch
            _seed_identity(d)
            d.section("identity", "available", f"{reason}; identity from frozen registry snapshot row")
        else:
            d.section("identity", state, reason)
        return
    body = resp.json()
    if body.get("organisasjonsnummer") != d.org:  # identity anchor must match exactly
        d.section("identity", "failed", "registry response organisation number mismatch")
        return
    d.entity = body
    src = "official_registry"

    def add(field: str, value: Any, span_key: str, **kw: Any) -> None:
        if value in (None, "", [], {}):
            return
        ev = d.add_evidence(resp, src, f"{span_key}: {value if not isinstance(value, (dict, list)) else str(value)[:300]}")
        d.claim(field, kw.pop("section", "identity"), value, [ev], **kw)

    add("legal_name", body.get("navn"), "navn")
    add("legal_form", {"code": _get(body, "organisasjonsform", "kode"), "label": _get(body, "organisasjonsform", "beskrivelse")}, "organisasjonsform")
    status = "bankrupt" if body.get("konkurs") else "liquidating" if body.get("underAvvikling") else \
        "forced_dissolution" if body.get("underTvangsavviklingEllerTvangsopplosning") else "active"
    add("registry_status", status, "konkurs/underAvvikling/underTvangsavvikling")
    add("registered_business_address", _address(body.get("forretningsadresse")), "forretningsadresse", section="locations")
    add("postal_address", _address(body.get("postadresse")), "postadresse")
    add("municipality", _get(body, "forretningsadresse", "kommune"), "forretningsadresse.kommune")
    industries = [{"code": body[k]["kode"], "label": body[k].get("beskrivelse")} for k in ("naeringskode1", "naeringskode2", "naeringskode3") if body.get(k)]
    add("industry", industries, "naeringskode")
    if body.get("harRegistrertAntallAnsatte") or body.get("antallAnsatte") is not None:
        add("registered_employees", body.get("antallAnsatte"), "antallAnsatte",
            effective_date=body.get("registreringsdatoAntallAnsatteNAVAaregisteret") or body.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
    add("founded_date", body.get("stiftelsesdato"), "stiftelsesdato")
    add("registered_date", body.get("registreringsdatoEnhetsregisteret"), "registreringsdatoEnhetsregisteret")
    add("registry_website", body.get("hjemmeside"), "hjemmeside")
    if (body.get("organisasjonsform") or {}).get("kode") != "ENK":  # sole-trader phone = personal data
        add("registry_phone", body.get("telefon") or body.get("mobil"), "telefon", section="contact")
        if d.values("registry_phone"):
            d.section("contact", "available", "phone number registered in Enhetsregisteret")
    add("vat_registered", body.get("registrertIMvaregisteret"), "registrertIMvaregisteret")
    add("in_corporate_group", body.get("erIKonsern"), "erIKonsern")
    if body.get("kapital"):
        cap = body["kapital"]
        add("share_capital", {"amount": cap.get("belop"), "currency": cap.get("valuta"), "type": cap.get("type")}, "kapital", effective_date=cap.get("innfortDato"))
    add("registered_activity", " ".join(body.get("aktivitet") or body.get("vedtektsfestetFormaal") or []).strip() or None, "aktivitet/vedtektsfestetFormaal")
    add("historical_names", [h.get("navn") for h in body.get("historiskeNavn") or [] if h.get("navn")], "historiskeNavn")
    add("latest_submitted_accounts_year", body.get("sisteInnsendteAarsregnskap"), "sisteInnsendteAarsregnskap", section="financials")
    if body.get("hjemmeside"):
        d.website_candidates.append({"url": body["hjemmeside"], "origin": "official_registry"})
    d.section("identity", "available", "live Brønnøysund entity record matched by exact organisation number")


def _seed_identity(d: Dossier) -> None:
    seed = d.seed
    ev = d.add_evidence(None, "official_registry_snapshot", f"snapshot row {d.org}: {seed.get('name')}", url=ENTITY.format(org=d.org))
    d.entity = {"navn": seed.get("name"), "organisasjonsform": {"kode": seed.get("legal_form")}, "hjemmeside": seed.get("website"),
                "forretningsadresse": {"kommune": seed.get("municipality")}}
    for field, key in (("legal_name", "name"), ("municipality", "municipality"), ("registry_website", "website")):
        if seed.get(key):
            d.claim(field, "identity", seed[key], [ev], method="frozen_snapshot")
    if seed.get("website"):
        d.website_candidates.append({"url": seed["website"], "origin": "official_registry"})


# -- annual accounts -----------------------------------------------------------
FIN_FIELDS = {
    "revenue": ("resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter"),
    "operating_result": ("resultatregnskapResultat", "driftsresultat", "driftsresultat"),
    "profit_before_tax": ("resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad"),
    "net_result": ("resultatregnskapResultat", "aarsresultat"),
    "total_assets": ("eiendeler", "sumEiendeler"),
    "equity": ("egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
    "total_debt": ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
    "payroll_costs": ("resultatregnskapResultat", "driftsresultat", "driftskostnad", "loennskostnad"),
}


def fetch_accounts(client: Client, d: Dossier) -> None:
    resp = client.get(ACCOUNTS.format(org=d.org), accept=JSON)
    if not resp.ok:
        state, reason = _state_for(resp, "annual accounts")
        if state == "not_available" and (d.entity.get("organisasjonsform") or {}).get("kode") in {"ENK", "ANS", "DA"}:
            state, reason = "not_applicable", "legal form may be exempt from filing; registry returned no normalised accounts"
        d.section("financials", state, reason)
        return
    records = resp.json() if isinstance(resp.json(), list) else []
    records.sort(key=lambda r: (_get(r, "regnskapsperiode", "tilDato") or "", r.get("regnskapstype") != "SELSKAP"), reverse=True)
    found = 0
    for rec in records:
        period = _get(rec, "regnskapsperiode", "fraDato"), _get(rec, "regnskapsperiode", "tilDato")
        if not period[1]:
            continue
        period_s = f"{period[0]}/{period[1]}"
        kind = (rec.get("regnskapstype") or "SELSKAP").lower()
        currency = rec.get("valuta") or "NOK"
        for field, path in FIN_FIELDS.items():
            value = _get(rec, *path)
            if value is None:  # absent stays absent: never zero-filled
                continue
            ev = d.add_evidence(resp, "official_annual_accounts", f"{kind} {period_s} {'.'.join(path)} = {value} {currency} (record id {rec.get('id')})")
            d.claim(field, "financials", {"amount": value, "currency": currency, "statement": kind}, [ev],
                    key=f"{field}|{kind}|{period[1]}", reporting_period=period_s, effective_date=period[1])
            found += 1
        if rec.get("revisjon"):
            ev = d.add_evidence(resp, "official_annual_accounts", f"{kind} {period_s} revisjon = {rec['revisjon']}")
            d.claim("audit_status", "financials", {"not_audited": rec["revisjon"].get("ikkeRevidertAarsregnskap"),
                    "audit_opt_out": rec["revisjon"].get("fravalgRevisjon")}, [ev], key=f"audit|{kind}|{period[1]}", reporting_period=period_s)
    d.section("financials", "available" if found else "not_available",
              f"{len(records)} filed annual-account record(s) from Regnskapsregisteret" if found else "registry returned no financial values")


# -- roles ----------------------------------------------------------------------
def fetch_roles(client: Client, d: Dossier) -> None:
    resp = client.get(ROLES.format(org=d.org), accept=JSON)
    if not resp.ok:
        d.section("leadership", *_state_for(resp, "roles"))
        return
    count = 0
    for group in resp.json().get("rollegrupper", []):
        for item in group.get("roller", []):
            if item.get("avregistrert") or _get(item, "person", "erDoed"):
                continue
            name = _get(item, "person", "navn") or {}
            person = " ".join(filter(None, [name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")]))
            entity = item.get("enhet") or {}
            entity_name = entity.get("navn")
            holder = person or (" ".join(entity_name) if isinstance(entity_name, list) else entity_name)
            if not holder:
                continue
            value = {"name": holder, "role": _get(item, "type", "beskrivelse"), "role_code": _get(item, "type", "kode"),
                     "holder_type": "person" if person else "organisation"}
            if entity.get("organisasjonsnummer"):
                value["organisation_number"] = entity["organisasjonsnummer"]
            # birth dates are deliberately discarded (data minimisation)
            ev = d.add_evidence(resp, "official_roles", f"{value['role']}: {holder}")
            d.claim("role", "leadership", value, [ev], key=f"role|{value['role_code']}|{holder}", effective_date=group.get("sistEndret"))
            count += 1
    d.section("leadership", "available" if count else "not_available", f"{count} active registered role(s)" if count else "no active registered roles")


# -- subunits (registered workplaces) -----------------------------------------------
def fetch_subunits(client: Client, d: Dossier) -> None:
    resp = client.get(SUBUNITS.format(org=d.org), accept=JSON)
    if not resp.ok:
        state, reason = _state_for(resp, "subunits")
        d.section("locations", state if not d.values("registered_business_address") else "available", reason)
        return
    rows = _get(resp.json(), "_embedded", "underenheter") or []
    for row in rows:
        if row.get("slettedato"):
            continue
        value = {"name": row.get("navn"), "organisation_number": row.get("organisasjonsnummer"),
                 "address": _address(row.get("beliggenhetsadresse") or row.get("postadresse")),
                 "municipality": _get(row, "beliggenhetsadresse", "kommune"),
                 "industry": _get(row, "naeringskode1", "beskrivelse"), "employees": row.get("antallAnsatte"),
                 "started": row.get("oppstartsdato")}
        d.subunit_orgs.add(str(row.get("organisasjonsnummer")))
        if row.get("navn"):
            d.subunit_names.append(row["navn"])
        ev = d.add_evidence(resp, "official_subunits", f"underenhet {value['organisation_number']}: {value['name']}, {value['address']}")
        d.claim("registered_workplace", "locations", value, [ev], key=f"subunit|{value['organisation_number']}")
        if row.get("hjemmeside"):
            d.website_candidates.append({"url": row["hjemmeside"], "origin": "official_registry"})
    has_address = bool(d.values("registered_business_address"))
    d.section("locations", "available" if rows or has_address else "not_available",
              f"{len(rows)} registered subunit(s)" + (" plus registered business address" if has_address else ""))


# -- official registry change log (dated public activity) ------------------------------
UPDATES = "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter?organisasjonsnummer={org}&dato={since}&size=100&includeChanges=true"
FIELD_LABELS = {"navn": "name", "antallAnsatte": "registered employees", "forretningsadresse": "business address", "postadresse": "postal address",
                "hjemmeside": "website", "naeringskode1": "industry", "organisasjonsform": "legal form", "konkurs": "bankruptcy flag",
                "underAvvikling": "liquidation flag", "kapital": "share capital", "vedtektsdato": "articles of association date",
                "sisteInnsendteAarsregnskap": "latest filed accounts", "telefon": "phone", "aktivitet": "registered activity",
                "vedtektsfestetFormaal": "statutory purpose", "registrertIMvaregisteret": "VAT registration", "epostadresse": "email"}


def summarize_changes(ops: list[dict]) -> list[dict[str, Any]]:
    out = {}
    for op in ops or []:
        root = str(op.get("path") or "").strip("/").split("/")[0]
        if root.startswith("registreringsdato") or root.startswith("_") or root not in FIELD_LABELS:
            continue  # housekeeping timestamps carry no business meaning
        value = op.get("value")
        if isinstance(value, dict):
            value = _address(value) if "adresse" in value or "postnummer" in value else value.get("beskrivelse") or value.get("belop") or value
        out[root] = {"field": FIELD_LABELS[root], "op": op.get("op"), "value": value}
    return list(out.values())


def fetch_registry_updates(client: Client, d: Dossier, months: int = 24, limit: int = 10) -> None:
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=30 * months)).strftime("%Y-%m-%dT00:00:00.000Z")
    resp = client.get(UPDATES.format(org=d.org, since=since), accept=JSON)
    if not resp.ok:
        d.section("public_activity", *_state_for(resp, "registry change log"))
        return
    rows = _get(resp.json(), "_embedded", "oppdaterteEnheter") or []
    events = []
    for row in rows:
        if str(row.get("organisasjonsnummer")) != d.org:
            continue
        changes = summarize_changes(row.get("endringer"))
        if changes or row.get("endringstype") in ("Ny", "Sletting"):
            events.append((row, changes))
    for row, changes in events[-limit:]:
        date = str(row.get("dato") or "")[:10]
        text = "; ".join(f"{c['field']} → {c['value']}" for c in changes) or str(row.get("endringstype"))
        ev = d.add_evidence(resp, "official_registry_changelog", f"{date} oppdateringsid {row.get('oppdateringsid')}: {text}"[:400])
        d.claim("registry_change", "public_activity", {"date": date, "type": row.get("endringstype"), "changes": changes,
                "url": ENTITY.format(org=d.org)}, [ev], key=f"update|{row.get('oppdateringsid')}", effective_date=date)
    d.section("public_activity", "available" if events else "not_available",
              f"{len(events)} dated registry change(s) since {since[:10]}" if events else f"no substantive registry changes since {since[:10]}")
