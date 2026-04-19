import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.utils import normalize_tag, parse_float, parse_int
from app.data import load_player_stats, score_history_rows
from app.services import build_players_enriched, get_focus_badge
from app.cr_api import cr_api_get, fetch_riverracelog, fetch_currentriverrace, CLAN_TAG_RAW, CLAN_TAG_ENCODED

router = APIRouter()

_radar_cache: Dict[str, Any] = {}
_radar_cache_ts: float = 0.0
_RADAR_TTL = 120  # Sekunden


@router.get("/warlog")
def warlog():
    """Kriegsverlauf – live von CR-API oder CSV als Fallback."""
    items = fetch_riverracelog()
    if items:
        wars = []
        for item in items:
            standings = item.get("standings", [])
            our_standing = next(
                (s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            our_rank = next(
                (i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            if not our_standing:
                continue
            clan = our_standing.get("clan", {})
            participants = clan.get("participants", [])
            total_decks = sum(p.get("decksUsed", 0) for p in participants)
            total_fame = clan.get("fame", 0)
            wars.append({
                "season_id": item.get("seasonId"),
                "section_index": item.get("sectionIndex"),
                "created_date": item.get("createdDate"),
                "our_rank": our_rank,
                "total_clans": len(standings),
                "our_fame": total_fame,
                "trophy_change": our_standing.get("trophyChange", 0),
                "total_decks_used": total_decks,
                "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
                "participants_count": len(participants),
                "players": sorted([
                    {
                        "name": p.get("name"),
                        "tag": p.get("tag"),
                        "fame": p.get("fame", 0),
                        "decks_used": p.get("decksUsed", 0),
                        "boat_attacks": p.get("boatAttacks", 0),
                        "repair_points": p.get("repairPoints", 0),
                    }
                    for p in participants
                ], key=lambda x: -x["fame"]),
            })
        return {"source": "live", "wars": wars, "total_recorded": len(wars)}

    rows = score_history_rows()
    by_date: Dict[str, list] = {}
    for row in rows:
        date = str(row.get("date") or "").strip()
        if not date:
            continue
        if date not in by_date:
            by_date[date] = []
        by_date[date].append({
            "name": str(row.get("player_name") or "").strip(),
            "score": parse_float(row.get("score", 0)),
            "trophies": parse_int(row.get("trophies", 0)),
        })
    wars = []
    for date, date_players in sorted(by_date.items()):
        scores = [p["score"] for p in date_players]
        wars.append({
            "date": date,
            "participants": len(date_players),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "players": sorted(date_players, key=lambda x: -x["score"]),
        })
    return {"source": "csv", "wars": list(reversed(wars)), "total_recorded": len(wars)}


@router.get("/warlog/current")
def warlog_current():
    """Aktuelle Kriegsübersicht aller Spieler mit Score, Fame/Deck und Badge."""
    enriched_players = list(build_players_enriched().values())
    result = []
    for p in enriched_players:
        focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
        result.append({
            "name": p["name"],
            "tag": p.get("tag"),
            "role": p.get("role"),
            "score": p.get("score", 0),
            "fame_per_deck": p.get("fame_per_deck", 0),
            "total_decks": p.get("total_decks", 0),
            "participation_count": p.get("participation_count", 0),
            "wars_in_window": p.get("wars_in_window", 0),
            "focus_badge": focus["badge"],
            "focus_label": focus["label"],
        })
    scores = [p["score"] for p in result]
    fame_values = [p["fame_per_deck"] for p in result if p["fame_per_deck"] > 0]
    return {
        "clan_avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "clan_avg_fame_per_deck": round(sum(fame_values) / len(fame_values), 1) if fame_values else 0,
        "total_members": len(result),
        "players": sorted(result, key=lambda x: -x["score"]),
    }


@router.get("/war/mahnwache")
def war_mahnwache():
    """Wer hat heute noch offene Decks? (Benötigt CR_API_KEY)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    state = data.get("state", "unknown")
    clan = data.get("clan", {})
    participants = clan.get("participants", [])

    if state not in ("warDay", "war", "full"):
        return {"state": state, "message": "Aktuell kein aktiver Kriegstag.", "open_decks": []}

    current_members = load_player_stats()
    open_decks = []
    for p in participants:
        if normalize_tag(p.get("tag", "")) not in current_members:
            continue
        decks_used_today = p.get("decksUsedToday", 0)
        open_today = max(0, 4 - decks_used_today)
        if open_today > 0:
            open_decks.append({
                "name": p.get("name"),
                "tag": p.get("tag"),
                "decks_open_today": open_today,
                "decks_used_today": decks_used_today,
                "fame": p.get("fame", 0),
                "boat_attacks": p.get("boatAttacks", 0),
            })
    open_decks.sort(key=lambda x: -x["decks_open_today"])
    return {
        "state": state,
        "open_decks_count": len(open_decks),
        "open_decks": open_decks,
        "message": f"{len(open_decks)} Spieler haben noch offene Decks heute!" if open_decks else "Alle Decks heute gespielt! 🎉",
    }


@router.get("/war/radar")
def war_radar():
    """Live-Standings aller Clans im aktuellen River Race. (Benötigt CR_API_KEY) — 2 Min. gecacht."""
    global _radar_cache, _radar_cache_ts
    now = time.time()
    if _radar_cache and (now - _radar_cache_ts) < _RADAR_TTL:
        return {**_radar_cache, "cached": True, "cache_age_seconds": int(now - _radar_cache_ts)}

    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    clans_data = data.get("clans", [])
    state = data.get("state", "unknown")
    standings = []
    for clan in clans_data:
        standings.append({
            "name": clan.get("name"),
            "tag": clan.get("tag"),
            "fame": clan.get("fame", 0),
            "repair_points": clan.get("repairPoints", 0),
        })
    standings.sort(key=lambda x: -x["fame"])
    for i, s in enumerate(standings):
        s["rank"] = i + 1

    our_entry = next((s for s in standings if s["tag"] == CLAN_TAG_RAW), None)
    our_rank = our_entry["rank"] if our_entry else None
    leader_fame = standings[0]["fame"] if standings else 0
    fame_gap = (leader_fame - our_entry["fame"]) if our_entry and our_rank and our_rank > 1 else 0

    result = {
        "state": state,
        "our_rank": our_rank,
        "our_fame": our_entry["fame"] if our_entry else 0,
        "fame_gap_to_leader": fame_gap,
        "standings": standings,
        "cached": False,
    }
    _radar_cache = result
    _radar_cache_ts = now
    return result


@router.get("/war/prognose")
def war_prognose():
    """3-Szenarien Sieg-Prognose. (Benötigt CR_API_KEY)"""
    data = cr_api_get(f"/clans/{CLAN_TAG_ENCODED}/currentriverrace")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    state = data.get("state", "unknown")
    period_type = data.get("periodType", "")
    clans_data = data.get("clans", [])

    if not clans_data:
        return {"state": state, "message": "Keine Clan-Daten verfügbar."}

    clans = []
    for c in clans_data:
        is_us = c.get("tag") == CLAN_TAG_RAW
        participants = c.get("participants", [])
        medals = c.get("periodPoints", 0) or sum(p.get("fame", 0) for p in participants)
        decks_used = sum(p.get("decksUsedToday", 0) for p in participants)
        member_count = max(len(participants), 1)
        max_decks = member_count * 4
        remaining = max(0, max_decks - decks_used)
        effizienz = round(medals / decks_used) if decks_used > 0 else None
        clans.append({
            "name": c.get("name", "Unbekannt"),
            "tag": c.get("tag"),
            "is_us": is_us,
            "medals": medals,
            "decks_used": decks_used,
            "max_decks": max_decks,
            "remaining_decks": remaining,
            "effizienz": effizienz,
        })

    played = [c for c in clans if c["effizienz"] is not None]
    fallback_eff = round(sum(c["effizienz"] for c in played) / len(played)) if played else 160
    fallback_eff = max(75, min(250, fallback_eff))

    us = next((c for c in clans if c["is_us"]), None)
    if not us:
        return {"state": state, "message": "Unser Clan nicht im Rennen gefunden."}

    def project_rank(clan_list, medals_per_deck: int):
        results = []
        for c in clan_list:
            projected = c["medals"] + c["remaining_decks"] * medals_per_deck
            results.append({"name": c["name"], "is_us": c["is_us"],
                            "projected": int(projected), "remaining": c["remaining_decks"]})
        results.sort(key=lambda x: x["projected"], reverse=True)
        our_entry = next((r for r in results if r["is_us"]), None)
        if our_entry is None:
            raise HTTPException(status_code=503, detail="Eigener Clan nicht in Projektionsliste gefunden")
        rank = results.index(our_entry) + 1
        return rank, int(our_entry["projected"]), results

    real_projections = []
    for c in clans:
        eff = c["effizienz"] if c["effizienz"] is not None else fallback_eff
        eff = max(75, min(250, eff))
        projected = int(c["medals"] + c["remaining_decks"] * eff)
        real_projections.append({"name": c["name"], "is_us": c["is_us"],
                                 "projected": projected, "remaining": c["remaining_decks"], "eff": eff})
    real_projections.sort(key=lambda x: x["projected"], reverse=True)
    our_real = next((r for r in real_projections if r["is_us"]), None)
    if our_real is None:
        raise HTTPException(status_code=503, detail="Eigener Clan nicht in realistischer Projektionsliste gefunden")
    rank_real = real_projections.index(our_real) + 1

    rank_worst, medals_worst, _ = project_rank(clans, 100)
    rank_best, medals_best, _   = project_rank(clans, 200)
    medals_real = our_real["projected"]
    our_eff_real = our_real["eff"]

    def rank_label(r):
        return {1: "Platz 1", 2: "Platz 2", 3: "Platz 3"}.get(r, f"Platz {r}")

    if rank_worst == 1:
        fazit = "Selbst im schlechtesten Fall halten wir Platz 1. Einfach alle Decks spielen!"
    elif rank_worst <= 2 and rank_best == 1:
        fazit = f"Im Worst Case Platz {rank_worst}, im Best Case Platz 1. Die Qualität der Kämpfe entscheidet!"
    elif rank_best == 1:
        fazit = "Platz 1 ist nur möglich wenn wir deutlich besser kämpfen als die Gegner. Alle Siege zählen!"
    elif rank_best <= 2:
        fazit = f"Platz 1 nicht mehr erreichbar. Platz 2 ist das Ziel – alle Decks spielen!"
    else:
        fazit = "Platz 1 oder 2 ist heute nicht mehr erreichbar. Alle Decks spielen für maximale Trophäen."

    return {
        "state": state,
        "period_type": period_type,
        "our_medals": us["medals"],
        "our_decks_used": us["decks_used"],
        "our_max_decks": us["max_decks"],
        "our_remaining_decks": us["remaining_decks"],
        "scenario_worst": {"medals_per_deck": 100, "our_rank": rank_worst, "our_rank_label": rank_label(rank_worst), "our_projected_medals": medals_worst, "beschreibung": "Alle verbleibenden Decks verloren (100 Fame/Deck)"},
        "scenario_real": {"our_effizienz": our_eff_real, "our_rank": rank_real, "our_rank_label": rank_label(rank_real), "our_projected_medals": medals_real, "beschreibung": f"Hochrechnung mit aktuellem Schnitt (~{our_eff_real} Fame/Deck)"},
        "scenario_best": {"medals_per_deck": 200, "our_rank": rank_best, "our_rank_label": rank_label(rank_best), "our_projected_medals": medals_best, "beschreibung": "Alle verbleibenden Decks gewonnen (200 Fame/Deck)"},
        "fazit": fazit,
        "standings_real": [{"rank": i + 1, "name": c["name"], "is_us": c["is_us"], "projected_medals": c["projected"], "effizienz": c["eff"]} for i, c in enumerate(real_projections)],
    }


@router.get("/war/status")
def war_status():
    """Alles zum aktuellen Krieg in einem Aufruf. (Benötigt CR_API_KEY)"""
    data = fetch_currentriverrace()
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    state = data.get("state", "unknown")
    clan = data.get("clan", {})
    clans_data = data.get("clans", [])
    participants = clan.get("participants", [])
    current_members = load_player_stats()

    open_decks = []
    if state in ("warDay", "war", "full"):
        for p in participants:
            if normalize_tag(p.get("tag", "")) not in current_members:
                continue
            decks_used_today = p.get("decksUsedToday", 0)
            open_today = max(0, 4 - decks_used_today)
            if open_today > 0:
                open_decks.append({
                    "name": p.get("name"),
                    "tag": p.get("tag"),
                    "decks_open_today": open_today,
                    "decks_used_today": decks_used_today,
                    "fame": p.get("fame", 0),
                    "boat_attacks": p.get("boatAttacks", 0),
                })
        open_decks.sort(key=lambda x: -x["decks_open_today"])

    standings = []
    for c in clans_data:
        standings.append({"name": c.get("name"), "tag": c.get("tag"), "fame": c.get("fame", 0), "repair_points": c.get("repairPoints", 0)})
    standings.sort(key=lambda x: -x["fame"])
    for i, s in enumerate(standings):
        s["rank"] = i + 1

    our_entry = next((s for s in standings if s["tag"] == CLAN_TAG_RAW), None)
    our_rank = our_entry["rank"] if our_entry else None
    our_fame = our_entry["fame"] if our_entry else clan.get("fame", 0)
    leader_fame = standings[0]["fame"] if standings else 0

    decks_used_today = sum(p.get("decksUsedToday", 0) for p in participants)
    remaining_decks = sum(max(0, 4 - p.get("decksUsedToday", 0)) for p in participants)
    avg_fame_per_deck = round(our_fame / decks_used_today) if decks_used_today > 0 else 150
    projected_fame = our_fame + round(remaining_decks * avg_fame_per_deck)
    second_fame = standings[1]["fame"] if len(standings) > 1 else 0
    can_win = projected_fame > leader_fame
    can_top2 = projected_fame > second_fame if our_rank and our_rank > 2 else True

    return {
        "state": state,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "cache_hinweis": "⚠️ CR-API cached Daten für 2–5 Minuten. Bei Abweichungen zum Spiel: Ingame-Stand hat immer Vorrang.",
        "mahnwache": {"open_decks_count": len(open_decks), "open_decks": open_decks, "message": f"{len(open_decks)} Spieler haben noch offene Decks!" if open_decks else "Alle Decks gespielt! 🎉"},
        "radar": {"our_rank": our_rank, "our_fame": our_fame, "fame_gap_to_leader": max(0, leader_fame - our_fame), "standings": standings},
        "prognose": {"remaining_decks": remaining_decks, "avg_fame_per_deck": avg_fame_per_deck, "projected_fame": projected_fame, "verdict": "🏆 Sieg möglich!" if can_win else "🥈 Top 2 erreichbar" if can_top2 else "⚔️ Schwierig – alle Decks müssen gespielt werden"},
    }


@router.get("/war/history")
def war_history():
    """Vollständiger River-Race-Verlauf. (Benötigt CR_API_KEY)"""
    items = fetch_riverracelog()
    if items is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    history = []
    for item in items:
        standings = item.get("standings", [])
        our_standing = next((s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None)
        our_rank = next((i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None)
        clan = our_standing.get("clan", {}) if our_standing else {}
        participants = clan.get("participants", [])
        total_fame = clan.get("fame", 0)
        total_decks = sum(p.get("decksUsed", 0) for p in participants)
        history.append({
            "season_id": item.get("seasonId"),
            "section_index": item.get("sectionIndex"),
            "created_date": item.get("createdDate"),
            "our_rank": our_rank,
            "total_clans": len(standings),
            "our_fame": total_fame,
            "trophy_change": our_standing.get("trophyChange", 0) if our_standing else 0,
            "participants_count": len(participants),
            "total_decks_used": total_decks,
            "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
            "top_scorer": max(participants, key=lambda x: x.get("fame", 0)).get("name") if participants else None,
        })

    wins = sum(1 for h in history if h["our_rank"] == 1)
    top2 = sum(1 for h in history if h["our_rank"] and h["our_rank"] <= 2)
    return {
        "races": history,
        "total_races": len(history),
        "wins": wins,
        "top2_finishes": top2,
        "avg_rank": round(sum(h["our_rank"] for h in history if h["our_rank"]) / len([h for h in history if h["our_rank"]]), 1) if history else None,
    }


@router.get("/war/live-participants")
def war_live_participants():
    """Live-Liste aller Kriegsteilnehmer. (Benötigt CR_API_KEY)"""
    data = fetch_currentriverrace()
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    state = data.get("state", "unknown")
    clan = data.get("clan", {})
    participants = clan.get("participants", [])

    result = []
    for p in participants:
        decks_used = p.get("decksUsed", 0)
        fame = p.get("fame", 0)
        result.append({
            "name": p.get("name"),
            "tag": p.get("tag"),
            "fame": fame,
            "decks_used": decks_used,
            "decks_used_today": p.get("decksUsedToday", 0),
            "decks_open_today": max(0, 4 - p.get("decksUsedToday", 0)),
            "boat_attacks": p.get("boatAttacks", 0),
            "repair_points": p.get("repairPoints", 0),
            "avg_fame_per_deck": round(fame / decks_used) if decks_used > 0 else 0,
        })

    result.sort(key=lambda x: -x["fame"])
    total_fame = sum(p["fame"] for p in result)
    total_decks = sum(p["decks_used"] for p in result)
    return {
        "state": state,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "cache_hinweis": "⚠️ CR-API cached Daten für 2–5 Minuten.",
        "participants": result,
        "total_participants": len(result),
        "clan_fame": total_fame,
        "clan_decks_used": total_decks,
        "clan_avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
    }
