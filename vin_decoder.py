"""
vin_decoder.py - Décodage VIN (local + API NHTSA)
"""
import pandas as pd
import requests
import os
from config import VIN_MODE, NHTSA_API_URL, VIN_MAPPING_CSV


def decode_vin(vin: str) -> dict | None:
    """
    Décode un VIN selon le mode configuré.
    Retourne dict {make, model, year} ou None.
    """
    vin = vin.strip().upper()
    if len(vin) != 17:
        return None

    if VIN_MODE == "local":
        return _decode_local(vin)
    elif VIN_MODE == "api":
        return _decode_api(vin)
    elif VIN_MODE == "both":
        result = _decode_local(vin)
        if result:
            return result
        return _decode_api(vin)
    return None


def _decode_local(vin: str) -> dict | None:
    """Décodage local via vin_mapping.csv (préfixes WMI 3 chars)."""
    if not os.path.exists(VIN_MAPPING_CSV):
        return None
    try:
        df = pd.read_csv(VIN_MAPPING_CSV)
        wmi = vin[:3]  # World Manufacturer Identifier (3 premiers chars)
        row = df[df["wmi"].str.upper() == wmi]
        if row.empty:
            # Essayer avec 2 caractères
            wmi2 = vin[:2]
            row = df[df["wmi"].str.upper() == wmi2]
        if not row.empty:
            r = row.iloc[0]
            # Extraire l'année depuis le 10ème caractère VIN
            year = _decode_year_char(vin[9])
            return {
                "make": r.get("make", "Inconnu"),
                "model": r.get("model", "Inconnu"),
                "year": year or r.get("year_default", 2010),
                "source": "local"
            }
    except Exception as e:
        print(f"[VIN Local] Erreur: {e}")
    return None


def _decode_api(vin: str) -> dict | None:
    """Décodage via API NHTSA vPIC."""
    try:
        url = NHTSA_API_URL.format(vin=vin)
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("Results", [])
        info = {r["Variable"]: r["Value"] for r in results if r["Value"] not in (None, "", "0", "Not Applicable")}
        make = info.get("Make", "")
        model = info.get("Model", "")
        year = info.get("Model Year", "")
        if make and model:
            return {
                "make": make.title(),
                "model": model.title(),
                "year": int(year) if str(year).isdigit() else None,
                "source": "NHTSA API"
            }
    except Exception as e:
        print(f"[VIN API] Erreur: {e}")
    return None


# Mapping du 10ème caractère VIN → année modèle
_YEAR_CHARS = {
    'A': 1980, 'B': 1981, 'C': 1982, 'D': 1983, 'E': 1984,
    'F': 1985, 'G': 1986, 'H': 1987, 'J': 1988, 'K': 1989,
    'L': 1990, 'M': 1991, 'N': 1992, 'P': 1993, 'R': 1994,
    'S': 1995, 'T': 1996, 'V': 1997, 'W': 1998, 'X': 1999,
    'Y': 2000, '1': 2001, '2': 2002, '3': 2003, '4': 2004,
    '5': 2005, '6': 2006, '7': 2007, '8': 2008, '9': 2009,
    'A2': 2010, 'B2': 2011, 'C2': 2012, 'D2': 2013, 'E2': 2014,
    'F2': 2015, 'G2': 2016, 'H2': 2017, 'J2': 2018, 'K2': 2019,
    'L2': 2020, 'M2': 2021, 'N2': 2022, 'P2': 2023, 'R2': 2024,
}

# Version simplifiée pour le 10ème char seul (cycle de 30 ans)
_YEAR_CHAR_SIMPLE = {
    'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014,
    'F': 2015, 'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019,
    'L': 2020, 'M': 2021, 'N': 2022, 'P': 2023, 'R': 2024,
    'S': 1995, 'T': 1996, 'V': 1997, 'W': 1998, 'X': 1999,
    'Y': 2000, '1': 2001, '2': 2002, '3': 2003, '4': 2004,
    '5': 2005, '6': 2006, '7': 2007, '8': 2008, '9': 2009,
}


def _decode_year_char(char: str) -> int | None:
    """Retourne l'année à partir du 10ème caractère VIN."""
    return _YEAR_CHAR_SIMPLE.get(char.upper())
