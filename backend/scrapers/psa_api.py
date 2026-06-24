"""PSA public API client.

The free PSA public API exposes cert verification by cert number. That response
includes the card's population at its grade (`PopulationAtGrade`/`Population`),
how many are graded higher, and the total population across grades — which is
exactly what we need to watch a 'pop 1' card and detect when another copy of the
same card+grade gets graded.

Set PSA_API_TOKEN in the environment (Render web service). Get a free token at
https://www.psacard.com/publicapi (PSA account -> API access).
"""
from __future__ import annotations

import os
import httpx

PSA_API_TOKEN = os.getenv("PSA_API_TOKEN", "")
PSA_BASE = "https://api.psacard.com/publicapi"

# PSA sits behind Cloudflare, which 1010-blocks default Python user-agents — send
# a browser UA so requests aren't rejected.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _headers() -> dict:
    return {"Authorization": f"bearer {PSA_API_TOKEN}", "User-Agent": _UA, "Accept": "application/json"}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pick(d: dict, *keys):
    """Case-insensitive first-present lookup across possible key spellings."""
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower and lower[k.lower()] not in (None, ""):
            return lower[k.lower()]
    return None


async def psa_cert_lookup(cert_number: str) -> dict | None:
    """Look up a PSA cert. Returns a normalized dict or None on failure.

    Keys: cert, subject, year, brand, card_number, variety, grade,
          population, population_higher, total_population, label.
    `valid` is False when PSA reports the cert as not found/invalid.
    """
    cert = "".join(c for c in str(cert_number) if c.isdigit())
    if not cert or not PSA_API_TOKEN:
        return None

    url = f"{PSA_BASE}/cert/GetByCertNumber/{cert}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers())
        if resp.status_code == 404:
            # PSA reached, but no such cert — distinct from a real API failure.
            return {"cert": cert, "valid": False, "url": f"https://www.psacard.com/cert/{cert}"}
        if resp.status_code >= 400:
            print(f"PSA cert lookup failed: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
    except Exception as e:
        print(f"PSA cert lookup error: {e}")
        return None

    # Response wraps the cert object; tolerate a few shapes.
    cert_obj = data.get("PSACert") or data.get("psaCert") or data.get("cert") or data
    if not isinstance(cert_obj, dict):
        return None

    valid = data.get("IsValidRequest", True) and bool(
        _pick(cert_obj, "CertNumber", "certNumber", "SpecID", "specId", "Subject")
    )

    subject = _pick(cert_obj, "Subject", "subject")
    year = _pick(cert_obj, "Year", "year")
    brand = _pick(cert_obj, "Brand", "brand", "BrandTitle")
    card_number = _pick(cert_obj, "CardNumber", "cardNumber")
    variety = _pick(cert_obj, "Variety", "variety", "VarietyPedigree")
    grade = _pick(cert_obj, "CardGrade", "GradeDescription", "grade", "Grade")

    # PSA's cert response: TotalPopulation = pop AT this grade; PopulationHigher =
    # number graded higher; TotalPopulationWithQualifier = pop at grade w/ a qualifier.
    pop = _int(_pick(cert_obj, "TotalPopulation", "totalPopulation"))
    pop_higher = _int(_pick(cert_obj, "PopulationHigher", "populationHigher"))
    pop_qualifier = _int(_pick(cert_obj, "TotalPopulationWithQualifier", "totalPopulationWithQualifier"))

    label_bits = [str(b) for b in (year, brand, subject) if b]
    if card_number:
        label_bits.append(f"#{card_number}")
    if variety:
        label_bits.append(str(variety))
    if grade:
        label_bits.append(str(grade))
    label = " ".join(label_bits).strip() or f"PSA cert {cert}"

    return {
        "cert": cert,
        "spec_id": _int(_pick(cert_obj, "SpecID", "specId")),
        "subject": subject,
        "year": year,
        "brand": brand,
        "card_number": card_number,
        "variety": variety,
        "grade": grade,
        "population": pop,
        "population_higher": pop_higher,
        "population_qualifier": pop_qualifier,
        "label": label,
        "valid": bool(valid),
        "url": f"https://www.psacard.com/cert/{cert}",
    }


async def spec_population(spec_id) -> dict | None:
    """Full PSA grade breakdown for a card spec. Returns a normalized dict with
    total graded, # of PSA 10s, gem rate, and the per-grade counts — or None on
    failure. (Endpoint: /pop/GetPSASpecPopulation/{specID}.)"""
    if not spec_id or not PSA_API_TOKEN:
        return None
    url = f"{PSA_BASE}/pop/GetPSASpecPopulation/{spec_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers())
        if resp.status_code >= 400:
            print(f"PSA spec pop failed: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
    except Exception as e:
        print(f"PSA spec pop error: {e}")
        return None

    pop = data.get("PSAPop") or data.get("psaPop") or {}
    if not isinstance(pop, dict):
        return None
    total = _int(pop.get("Total")) or 0
    tens = _int(pop.get("Grade10")) or 0
    nines = _int(pop.get("Grade9")) or 0
    gem_rate = round(100 * tens / total) if total else None
    # per-grade counts that are actually populated (skip the zeros)
    grades = {}
    for k, v in pop.items():
        if k.startswith("Grade") and not k.endswith("Q") and _int(v):
            grades[k.replace("Grade", "").replace("_", ".")] = _int(v)
    return {
        "spec_id": spec_id,
        "description": data.get("Description") or data.get("description"),
        "total": total,
        "psa10": tens,
        "psa9": nines,
        "gem_rate": gem_rate,        # % of total graded that are PSA 10
        "grades": grades,            # e.g. {"8": 3, "9": 8, "10": 32}
    }
