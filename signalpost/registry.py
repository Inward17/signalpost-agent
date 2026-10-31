"""Brønnøysund collectors (NLOD 2.0): entity, annual accounts, roles, subunits, announcements."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .dossier import Dossier
from .http import Client

ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES = ENTITY + "/roller"
SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
ANNOUNCEMENTS = "https://w2.brreg.no/kunngjoring/hent_nr.jsp?orgnr={org}"
ANNOUNCEMENT_ITEM = "https://w2.brreg.no/kunngjoring/hent_en.jsp?kid={kid}&sokeverdi={org}&spraak=nb"
JSON = "application/json"
SUPPRESSED_PERSONS: set[str] = set()  # filled by run.py from <state-dir>/suppressed_persons.txt
BULK_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
SNAPSHOT: dict[str, Any] = {}  # metadata of the frozen registry file passed with the batch (filled by load_frozen_registry)


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


# -- frozen registry file -----------------------------------------------------
# The bulk CSV (enheter/lastned/csv) names its columns after the API fields, a few with different casing.
_ALIASES = {"registreringsdatoantallansatteNAVAaregisteret": "registreringsdatoAntallAnsatteNAVAaregisteret",
            "registreringsdatoenhetsregisteret": "registreringsdatoEnhetsregisteret",
            "registrertIMvaRegisteret": "registrertIMvaregisteret"}
_LISTS = ("adresse", "aktivitet", "vedtektsfestetFormaal")   # lists in the API, one joined string in the CSV
_NUMBERS = ("antallAnsatte", "belop", "antallAksjer")


def _api_shape(row: dict[str, Any]) -> dict[str, Any]:
    """A bulk CSV row ("forretningsadresse.kommune": "...") or an API-shaped JSON record -> the live API's entity shape."""
    if "organisasjonsnummer" not in row and "organisation_number" in row:  # starter-kit universe row
        row = {"organisasjonsnummer": row["organisation_number"], "navn": row.get("name"), "organisasjonsform.kode": row.get("legal_form"),
               "antallAnsatte": row.get("employees"), "konkurs": row.get("bankrupt"), "underAvvikling": row.get("liquidating"),
               "forretningsadresse.kommune": row.get("municipality"), "forretningsadresse.kommunenummer": row.get("municipality_number"),
               "naeringskode1.kode": row.get("industry_code"), "naeringskode1.beskrivelse": row.get("industry_label"),
               "hjemmeside": row.get("website"), "sisteInnsendteAarsregnskap": row.get("latest_submitted_accounts")}
    out: dict[str, Any] = {}
    for key, value in row.items():
        if not key or value in (None, ""):
            continue
        if isinstance(value, str):
            value = {"true": True, "false": False}.get(value, value)
        *parents, leaf = _ALIASES.get(key, key).split(".")
        if leaf in _LISTS and isinstance(value, str):
            value = [line.strip() for line in value.split("\n") if line.strip()] if leaf == "adresse" else [value]
        if leaf in _NUMBERS and isinstance(value, str):
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                pass
        node = out
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value
    return out


def _text(path: Path) -> io.TextIOWrapper:
    raw = path.open("rb")
    gz = raw.read(2) == b"\x1f\x8b"   # Brreg serves the bulk CSV gzip-compressed whatever the file is called
    raw.seek(0)
    return io.TextIOWrapper(gzip.GzipFile(fileobj=raw) if gz else raw, encoding="utf-8-sig", errors="replace", newline="")


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with _text(path) as fh:
        head = fh.read(65536)
    first = head.lstrip()[:1]
    with _text(path) as fh:
        if first == "[":    # JSON array (enheter/lastned JSON)  # ponytail: loaded whole; stream it if the full JSON dump is passed
            yield from json.load(fh)
        elif first == "{":  # JSONL
            yield from (json.loads(line) for line in fh if line.strip())
        else:               # CSV with standard "" quote escaping; Brreg uses "," but ";" and tab exports are accepted
            header = head.split("\n", 1)[0]
            yield from csv.DictReader(fh, delimiter=max(",;\t", key=header.count))


def load_frozen_registry(path: Path, orgs: set[str]) -> dict[str, dict[str, Any]]:
    """This batch's rows from the frozen registry snapshot, in the live API's shape. Fallback only: used when the live call fails."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for row in _rows(path):
        scanned += 1
        org = re.sub(r"\D", "", str(row.get("organisasjonsnummer") or row.get("organisation_number") or ""))
        if org in orgs and org not in found:
            found[org] = _api_shape(row)
            if len(found) == len(orgs):
                break
    SNAPSHOT.update({"file": path.name, "content_sha256": digest.hexdigest(), "rows_scanned": scanned, "batch_rows_found": len(found),
                     "file_modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return found


# -- identity -----------------------------------------------------------------
def fetch_entity(client: Client, d: Dossier) -> None:
    resp = client.get(ENTITY.format(org=d.org), accept=JSON)
    if resp.ok:
        body = resp.json()
        if body.get("organisasjonsnummer") == d.org:  # identity anchor must match exactly
            _publish_entity(d, body, lambda span: d.add_evidence(resp, "official_registry", span))
            d.section("identity", "available", "live Brønnøysund entity record matched by exact organisation number")
            return
        state, reason = "failed", "registry response organisation number mismatch"
    else:
        state, reason = _state_for(resp, "live entity")
    if d.snapshot_entity.get("navn"):
        # the same registry record from the frozen file supplied with the batch: every field, cited to that file
        _publish_entity(d, d.snapshot_entity, lambda span: d.add_evidence(
            None, "official_registry_snapshot", f"frozen registry file {SNAPSHOT.get('file')}, row {d.org}: {span}", url=BULK_URL,
            extraction="frozen_registry_file", content_sha256=SNAPSHOT.get("content_sha256"), retrieved_at=SNAPSHOT.get("file_modified_at")))
        d.section("identity", "available", f"{reason}; identity from the frozen registry file supplied with the batch "
                                           f"({SNAPSHOT.get('file')}, sha256 {str(SNAPSHOT.get('content_sha256'))[:12]})")
    elif d.seed.get("name"):
        # no registry file: fall back to the snapshot fields in the input row
        _seed_identity(d)
        d.section("identity", "available", f"{reason}; identity from frozen registry snapshot row")
    else:
        d.section("identity", state, reason)


def _publish_entity(d: Dossier, body: dict[str, Any], evidence: Any) -> None:
    """Identity, location and contact claims from one registry record (live API response or frozen-file row)."""
    d.entity = body

    def add(field: str, value: Any, span_key: str, **kw: Any) -> None:
        if value in (None, "", [], {}):
            return
        ev = evidence(f"{span_key}: {value if not isinstance(value, (dict, list)) else str(value)[:300]}")
        d.claim(field, kw.pop("section", "identity"), value, [ev], **kw)

    add("legal_name", body.get("navn"), "navn")
    add("legal_form", {"code": _get(body, "organisasjonsform", "kode"), "label": _get(body, "organisasjonsform", "beskrivelse")}, "organisasjonsform")
    status = "bankrupt" if body.get("konkurs") else "liquidating" if body.get("underAvvikling") else \
        "forced_dissolution" if body.get("underTvangsavviklingEllerTvangsopplosning") else "active"
    add("registry_status", status, "konkurs/underAvvikling/underTvangsavvikling")
    add("registered_business_address", _address(body.get("forretningsadresse")), "forretningsadresse", section="locations")
    add("postal_address", _address(body.get("postadresse")), "postadresse")
    add("municipality", _get(body, "forretningsadresse", "kommune"), "forretningsadresse.kommune")
    industries = [{"code": body[k]["kode"], "label": body[k].get("beskrivelse")} for k in ("naeringskode1", "naeringskode2", "naeringskode3")
                  if isinstance(body.get(k), dict) and body[k].get("kode")]
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
    add("latest_submitted_accounts_year", body.get("sisteInnsendteAarsregnskap"), "sisteInnsendteAarsregnskap")
    if body.get("hjemmeside"):
        d.website_candidates.append({"url": body["hjemmeside"], "origin": "official_registry"})
    if d.values("registered_business_address"):
        d.section("locations", "available", "registered business address")


def _seed_identity(d: Dossier) -> None:
    seed = d.seed
    # the fact came from the batch's snapshot row, not the live API: cite the registry's bulk dataset and say so
    ev = d.add_evidence(None, "official_registry_snapshot",
                        f"input snapshot row for {d.org} (live entity API unavailable this run): name={seed.get('name')!r}",
                        url="https://data.brreg.no/enhetsregisteret/api/enheter/lastned", extraction="frozen_snapshot_row")
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
            if not holder or holder.casefold() in SUPPRESSED_PERSONS:  # honoured objection / erasure request
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


def oslo_date(stamp: str) -> str:
    """Calendar date in Norway of an ISO timestamp, whatever offset the API sends it with (it has sent both "Z" and local time).
    Taking the first 10 characters instead shifted late-evening entries by a day between runs: a false refresh change."""
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp[:10]
    if t.tzinfo is None:
        return t.date().isoformat()   # no offset given: already local
    t = t.astimezone(timezone.utc)
    # EU summer time (CEST, UTC+2) from 01:00 UTC on the last Sunday of March to 01:00 UTC on the last Sunday of October; else CET (UTC+1)
    def last_sunday(month: int) -> datetime:
        day = datetime(t.year, month, 31, 1, tzinfo=timezone.utc)
        return day - timedelta(days=(day.weekday() + 1) % 7)
    return (t + timedelta(hours=2 if last_sunday(3) <= t < last_sunday(10) else 1)).date().isoformat()


def fetch_registry_updates(client: Client, d: Dossier, months: int = 24, limit: int = 10) -> None:
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
        date = oslo_date(str(row.get("dato") or ""))
        text = "; ".join(f"{c['field']} → {c['value']}" for c in changes) or str(row.get("endringstype"))
        ev = d.add_evidence(resp, "official_registry_changelog", f"{date} oppdateringsid {row.get('oppdateringsid')}: {text}"[:400])
        d.claim("registry_change", "public_activity", {"date": date, "type": row.get("endringstype"), "changes": changes,
                "url": ENTITY.format(org=d.org)}, [ev], key=f"update|{row.get('oppdateringsid')}", effective_date=date)
    d.section("public_activity", "available" if events else "not_available",
              f"{len(events)} dated registry change(s) since {since[:10]}" if events else f"no substantive registry changes since {since[:10]}")
