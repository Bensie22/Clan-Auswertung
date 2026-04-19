from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from app.utils import validate_tag, normalize_name
from app.data import load_top_decks, score_history_by_player
from app.services import (
    build_players_enriched, get_focus_badge, compute_trend, compute_streak,
    build_promotion_status,
)
from app.cr_api import cr_api_get, fetch_riverracelog, CLAN_TAG_RAW
from config import MIN_PARTICIPATION

router = APIRouter()


@router.get("/player/{player_tag}")
def player(player_tag: str):
    tag = validate_tag(player_tag)
    players = build_players_enriched()
    if tag not in players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")
    return players[tag]


@router.get("/player/{player_tag}/history")
def player_history(player_tag: str):
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    player_name = all_players[tag]["name"]
    history = score_history_by_player()
    entries = history.get(normalize_name(player_name), [])
    scores = [e["score"] for e in entries]

    return {
        "tag": tag,
        "name": player_name,
        "entries": list(reversed(entries)),
        "trend": compute_trend(scores) if scores else "",
        "streak": compute_streak(scores),
        "streak_badge": f"🔥 {compute_streak(scores)}x perfekt" if compute_streak(scores) >= 3 else None,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "best_score": max(scores) if scores else 0,
        "worst_score": min(scores) if scores else 0,
    }


@router.get("/player/{player_tag}/warlog")
def player_warlog(player_tag: str):
    from app.utils import parse_float, parse_int
    tag = validate_tag(player_tag)
    tag_bare = tag.lstrip("#")
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    player_name = all_players[tag]["name"]
    items = fetch_riverracelog()
    if items:
        wars = []
        for item in items:
            standings = item.get("standings", [])
            our_standing = next(
                (s for s in standings if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
            )
            if not our_standing:
                continue
            participants = our_standing.get("clan", {}).get("participants", [])
            player_entry = next(
                (p for p in participants if p.get("tag", "").lstrip("#") == tag_bare), None
            )
            if not player_entry:
                continue
            wars.append({
                "season_id": item.get("seasonId"),
                "created_date": item.get("createdDate"),
                "our_rank": next(
                    (i + 1 for i, s in enumerate(standings) if s.get("clan", {}).get("tag") == CLAN_TAG_RAW), None
                ),
                "fame": player_entry.get("fame", 0),
                "decks_used": player_entry.get("decksUsed", 0),
                "boat_attacks": player_entry.get("boatAttacks", 0),
                "repair_points": player_entry.get("repairPoints", 0),
                "trophy_change": our_standing.get("trophyChange", 0),
            })
        if wars:
            total_fame = sum(w["fame"] for w in wars)
            total_decks = sum(w["decks_used"] for w in wars)
            return {
                "source": "live",
                "tag": tag,
                "name": player_name,
                "wars": wars,
                "total_wars": len(wars),
                "total_fame": total_fame,
                "avg_fame_per_deck": round(total_fame / total_decks) if total_decks > 0 else 0,
            }

    history = score_history_by_player()
    entries = history.get(normalize_name(player_name), [])
    if not entries:
        return {"tag": tag, "name": player_name, "wars": [], "message": "Keine Kriegsdaten vorhanden"}
    wars_csv = []
    for i, entry in enumerate(entries):
        delta = round(entry["score"] - entries[i - 1]["score"], 2) if i > 0 else None
        wars_csv.append({
            "date": entry["date"],
            "score": entry["score"],
            "trophies": entry["trophies"],
            "delta": delta,
            "trend_symbol": "🟢" if entry["score"] >= 80 else "🟡" if entry["score"] >= 50 else "🔴",
        })
    return {
        "source": "csv",
        "tag": tag,
        "name": player_name,
        "wars": list(reversed(wars_csv)),
        "total_wars": len(wars_csv),
        "avg_score": round(sum(e["score"] for e in entries) / len(entries), 2),
    }


@router.get("/player/{player_tag}/decks")
def player_decks(player_tag: str):
    from app.utils import parse_int
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    tag_bare = tag.lstrip("#")
    top_decks_data = load_top_decks()
    decks_dict = top_decks_data.get("decks", {})

    player_decks_list = []
    for deck_key, deck_data in decks_dict.items():
        if not isinstance(deck_data, dict):
            continue
        deck_tags = [str(t) for t in deck_data.get("tags", [])]
        if tag_bare not in deck_tags:
            continue
        wins = parse_int(deck_data.get("wins", 0))
        losses = parse_int(deck_data.get("losses", 0))
        total = wins + losses
        player_decks_list.append({
            "deck_key": deck_key,
            "cards": [c.get("name") for c in deck_data.get("cards", []) if isinstance(c, dict)],
            "wins": wins,
            "losses": losses,
            "total_matches": total,
            "winrate_pct": round(wins / total * 100, 1) if total > 0 else 0,
        })

    player_decks_list.sort(key=lambda x: -x["total_matches"])
    return {
        "tag": tag,
        "name": all_players[tag]["name"],
        "decks": player_decks_list[:20],
        "total_decks_found": len(player_decks_list),
    }


@router.get("/player/{player_tag}/focus")
def player_focus(player_tag: str):
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]
    is_welpenschutz = p.get("participation_count", 0) <= MIN_PARTICIPATION

    return {
        "tag": tag,
        "name": p["name"],
        "role": p.get("role"),
        "score": p.get("score", 0),
        "fame_per_deck": p.get("fame_per_deck", 0),
        "participation_count": p.get("participation_count", 0),
        "focus": focus,
        "welpenschutz": is_welpenschutz,
        "wars_until_evaluated": max(0, MIN_PARTICIPATION + 1 - p.get("participation_count", 0)) if is_welpenschutz else 0,
        "trend": compute_trend(scores) if scores else "",
        "streak": compute_streak(scores),
    }


@router.get("/player/{player_tag}/streak")
def player_streak(player_tag: str):
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]
    streak = compute_streak(scores)

    return {
        "name": p["name"],
        "tag": tag,
        "streak": streak,
        "streak_badge": f"🔥 {streak}x perfekt" if streak >= 3 else (f"🔥 {streak}" if streak >= 2 else "Kein aktiver Streak"),
        "trend": compute_trend(scores) if scores else "",
        "recent_scores": scores[-6:],
        "current_score": p.get("score", 0),
    }


@router.get("/player/{player_tag}/promotion-status")
def player_promotion_status(player_tag: str):
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    return {"name": p["name"], "tag": tag, **build_promotion_status(p)}


@router.get("/player/{player_tag}/stats")
def player_stats_combined(player_tag: str):
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    history = score_history_by_player()
    entries = history.get(normalize_name(p["name"]), [])
    scores = [e["score"] for e in entries]
    focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
    streak = compute_streak(scores)
    is_welpenschutz = p.get("participation_count", 0) <= MIN_PARTICIPATION

    return {
        "name": p["name"],
        "tag": tag,
        "role": p.get("role"),
        "score": p.get("score", 0),
        "fame_per_deck": p.get("fame_per_deck", 0),
        "trophies": p.get("trophies", 0),
        "participation_count": p.get("participation_count", 0),
        "focus": focus,
        "welpenschutz": is_welpenschutz,
        "wars_until_evaluated": max(0, MIN_PARTICIPATION + 1 - p.get("participation_count", 0)) if is_welpenschutz else 0,
        "trend": compute_trend(scores) if scores else "",
        "streak": streak,
        "streak_badge": f"🔥 {streak}x perfekt" if streak >= 3 else (f"🔥 {streak}" if streak >= 2 else None),
        "recent_scores": scores[-6:],
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "best_score": max(scores) if scores else 0,
    }


@router.get("/player/{player_tag}/battlelog")
def player_battlelog(player_tag: str):
    tag = validate_tag(player_tag)
    tag_encoded = f"%23{tag.lstrip('#')}"
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    data = cr_api_get(f"/players/{tag_encoded}/battlelog")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    battles = data if isinstance(data, list) else []
    river_race_battles = [b for b in battles if "riverRace" in b.get("type", "").lower() or "river" in b.get("type", "").lower()][:25]

    result = []
    for b in river_race_battles:
        team = b.get("team", [{}])[0] if b.get("team") else {}
        opponent = b.get("opponent", [{}])[0] if b.get("opponent") else {}
        player_crowns = team.get("crowns", 0)
        opp_crowns = opponent.get("crowns", 0)
        result.append({
            "battle_time": b.get("battleTime"),
            "type": b.get("type"),
            "result": "win" if player_crowns > opp_crowns else "loss" if player_crowns < opp_crowns else "draw",
            "crowns": player_crowns,
            "opponent_crowns": opp_crowns,
            "opponent_name": opponent.get("name"),
            "opponent_tag": opponent.get("tag"),
            "player_deck": [c.get("name") for c in team.get("cards", []) if isinstance(c, dict)],
            "opponent_deck": [c.get("name") for c in opponent.get("cards", []) if isinstance(c, dict)],
        })

    wins = sum(1 for b in result if b["result"] == "win")
    total = len(result)
    return {
        "tag": tag,
        "name": all_players[tag]["name"],
        "battles": result,
        "total_battles": total,
        "wins": wins,
        "losses": total - wins,
        "winrate_pct": round(wins / total * 100, 1) if total > 0 else 0,
    }


@router.get("/player/{player_tag}/live")
def player_live(player_tag: str):
    tag = validate_tag(player_tag)
    tag_encoded = f"%23{tag.lstrip('#')}"
    data = cr_api_get(f"/players/{tag_encoded}")
    if data is None:
        raise HTTPException(status_code=503, detail="CR-API nicht verfügbar.")

    clan_info = data.get("clan", {})
    return {
        "name": data.get("name"),
        "tag": data.get("tag"),
        "trophies": data.get("trophies"),
        "best_trophies": data.get("bestTrophies"),
        "level": data.get("expLevel"),
        "war_day_wins": data.get("warDayWins"),
        "donations": data.get("donations"),
        "donations_received": data.get("donationsReceived"),
        "donations_total": data.get("totalDonations"),
        "clan_name": clan_info.get("name"),
        "clan_tag": clan_info.get("tag"),
        "role": data.get("role"),
        "last_seen": data.get("lastSeen"),
        "arena": data.get("arena", {}).get("name"),
    }
