from fastapi import APIRouter
import requests as http_requests

from app.services import build_players_enriched, build_warning_candidates, build_promotion_candidates
from app.data import load_records, load_strikes_raw, load_kicked_players
from app.cr_api import cr_api_get, CLAN_TAG_ENCODED

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "mode": "json-first"}


@router.get("/debug/ip")
def debug_ip():
    try:
        resp = http_requests.get("https://api.ipify.org?format=json", timeout=5)
        return {"outbound_ip": resp.json().get("ip"), "hinweis": "Diese IP muss im Supercell Developer Key whitelisted sein."}
    except Exception as e:
        return {"error": str(e)}


@router.get("/summary")
def summary():
    players = build_players_enriched()
    warnings = build_warning_candidates()
    promotions = build_promotion_candidates()
    records = load_records()
    strikes = load_strikes_raw()
    return {
        "status": "ok",
        "mode": "json-first",
        "member_count": len(players),
        "warning_candidates": len(warnings),
        "promotion_candidates": len(promotions),
        "records_available": list(records.keys()) if isinstance(records, dict) else [],
        "strike_week": strikes.get("last_strike_week", []),
    }


@router.get("/players")
def players():
    data = list(build_players_enriched().values())
    return {"players": sorted(data, key=lambda x: x["name"].lower())}


@router.get("/warnings")
def warnings():
    return {"players": build_warning_candidates()}


@router.get("/promotions")
def promotions():
    return {"players": build_promotion_candidates()}


@router.get("/strikes")
def strikes():
    return load_strikes_raw()


@router.get("/records")
def records():
    return load_records()


@router.get("/kicked")
def kicked():
    return {"players": load_kicked_players()}


@router.get("/clan/live")
def clan_live():
    """Live Clan-Profil: Mitglieder, Trophäen, Liga, Spenden-Woche. (Benötigt CR_API_KEY)"""
    from fastapi import HTTPException
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    member_list = data.get("memberList", [])
    members_summary = [
        {
            "name": m.get("name"),
            "tag": m.get("tag"),
            "role": m.get("role"),
            "trophies": m.get("trophies"),
            "donations": m.get("donations"),
            "donations_received": m.get("donationsReceived"),
        }
        for m in member_list
    ]
    members_summary.sort(key=lambda x: -x["trophies"])

    return {
        "name": data.get("name"),
        "tag": data.get("tag"),
        "description": data.get("description"),
        "type": data.get("type"),
        "members": data.get("members"),
        "required_trophies": data.get("requiredTrophies"),
        "clan_score": data.get("clanScore"),
        "clan_war_trophies": data.get("clanWarTrophies"),
        "donations_per_week": data.get("donationsPerWeek"),
        "location": data.get("location", {}).get("name"),
        "member_list": members_summary,
    }
