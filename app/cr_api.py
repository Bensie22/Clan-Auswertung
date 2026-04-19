import os
from typing import Any, Dict, List, Optional

import requests as http_requests
from fastapi import HTTPException

CR_API_BASE = "https://proxy.royaleapi.dev/v1"

_raw = os.environ.get("CLAN_TAG", "#Y9YQC8UG")
CLAN_TAG_RAW = _raw if _raw.startswith("#") else f"#{_raw.lstrip('%23')}"
CLAN_TAG_ENCODED = CLAN_TAG_RAW.replace("#", "%23")


def cr_api_get(path: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("CR_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="CR_API_KEY nicht gesetzt in Render Environment Variables.")
    try:
        resp = http_requests.get(
            f"{CR_API_BASE}{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail=f"RoyaleAPI Proxy: Zugriff verweigert (403) – API-Key ungültig oder gesperrt. URL: {CR_API_BASE}{path}")
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail=f"RoyaleAPI Proxy: Ungültiger Key (401) – bitte CR_API_KEY in Render prüfen.")
        raise HTTPException(status_code=502, detail=f"RoyaleAPI Proxy Fehler: HTTP {resp.status_code} – {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Verbindungsfehler zur CR-API: {str(e)}")


def fetch_riverracelog() -> Optional[List[Dict[str, Any]]]:
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/riverracelog")
    if data is None:
        return None
    return data.get("items", [])


def fetch_currentriverrace() -> Optional[Dict[str, Any]]:
    return cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
