from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.utils import normalize_tag, normalize_name, parse_float, parse_int
from app.data import load_top_decks, load_records, score_history_by_player
from app.services import (
    build_players_enriched, get_focus_badge, compute_trend, compute_streak,
    calculate_teamplay_score_from_stats, build_promotion_status, build_promotion_candidates,
)
from config import (
    BADGE_STARK_FAME, BADGE_STABIL_FAME,
    CLAN_RELIABLE_GREEN, CLAN_RELIABLE_YELLOW,
)

router = APIRouter()


@router.get("/analytics/teamplay")
def analytics_teamplay():
    """Teamplay-Score: Donor/Leecher/Schläfer-Verteilung."""
    all_players = list(build_players_enriched().values())
    return calculate_teamplay_score_from_stats(all_players)


@router.get("/analytics/clan-quality")
def analytics_clan_quality():
    """Clan-Qualität: Durchschnittliche Fame/Deck und Zuverlässigkeitssignal."""
    all_players = list(build_players_enriched().values())
    clan_records = load_records()

    fame_values = [p.get("fame_per_deck", 0) for p in all_players if p.get("fame_per_deck", 0) > 0]
    scores = [p.get("score", 0) for p in all_players]
    avg_fame = round(sum(fame_values) / len(fame_values), 1) if fame_values else 0
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    quality_signal = (
        "⭐ stark 🟢" if avg_fame >= BADGE_STARK_FAME else
        "🛡️ stabil 🟡" if avg_fame >= BADGE_STABIL_FAME else
        "⚠️ ausbaufähig 🔴"
    )
    reliability_signal = (
        "sehr zuverlässig 🟢" if avg_score >= CLAN_RELIABLE_GREEN else
        "okay 🟡" if avg_score >= CLAN_RELIABLE_YELLOW else
        "kritisch 🔴"
    )
    return {
        "avg_fame_per_deck": avg_fame,
        "avg_score_pct": avg_score,
        "quality_signal": quality_signal,
        "reliability_signal": reliability_signal,
        "record_clan_quality": clan_records.get("clan_quality", {}).get("val") if isinstance(clan_records.get("clan_quality"), dict) else None,
        "record_war_rank": clan_records.get("clan_war_rank"),
        "total_active_players": len(all_players),
    }


@router.get("/players/leaderboard")
def players_leaderboard():
    """Vollrangliste aller Spieler nach Score, Fame/Deck und Trophäen."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
        result.append({
            "name": p["name"],
            "tag": tag,
            "role": p.get("role"),
            "score": p.get("score", 0),
            "fame_per_deck": p.get("fame_per_deck", 0),
            "trophies": p.get("trophies", 0),
            "donations": p.get("donations", 0),
            "strikes": p.get("strikes", 0),
            "participation_count": p.get("participation_count", 0),
            "focus_badge": focus["badge"],
            "trend": compute_trend(scores) if scores else "",
            "streak": compute_streak(scores),
        })
    result.sort(key=lambda x: (-x["score"], -x["fame_per_deck"], -x["trophies"]))
    for i, entry in enumerate(result):
        entry["rank"] = i + 1
    return {"players": result, "total": len(result)}


@router.get("/players/trends")
def players_trends():
    """Score-Trends und Deltas aller Spieler der letzten 6 Wochen."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        trend = compute_trend(scores) if scores else "–"
        streak = compute_streak(scores)
        delta = round(scores[-1] - scores[-2], 2) if len(scores) >= 2 else None
        result.append({
            "name": p["name"],
            "tag": tag,
            "score": p.get("score", 0),
            "trend": trend,
            "streak": streak,
            "streak_badge": f"🔥 {streak}" if streak >= 3 else None,
            "delta": delta,
            "delta_symbol": "📈" if delta is not None and delta > 5 else "📉" if delta is not None and delta < -5 else "➡️" if delta is not None else "–",
        })
    result.sort(key=lambda x: -x["score"])
    return {"players": result, "total": len(result)}


@router.get("/players/streaks")
def players_streaks():
    """Spieler mit aktivem Streak (2+ perfekte Wochen)."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        streak = compute_streak(scores)
        if streak >= 2:
            result.append({"name": p["name"], "tag": tag, "streak": streak, "badge": f"🔥 {streak}x 100%", "score": p.get("score", 0)})
    result.sort(key=lambda x: -x["streak"])
    return {"players": result, "message": f"{len(result)} Spieler mit aktivem Streak" if result else "Aktuell keine aktiven Streaks"}


@router.get("/players/comebacks")
def players_comebacks():
    """Größte Score-Verbesserungen gegenüber der vorherigen Woche."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    clan_records = load_records()
    result = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        if len(scores) >= 2:
            delta = round(scores[-1] - scores[-2], 2)
            if delta > 0:
                result.append({
                    "name": p["name"],
                    "tag": tag,
                    "previous_score": scores[-2],
                    "current_score": scores[-1],
                    "improvement": delta,
                    "badge": "🚀 Mega-Comeback!" if delta >= 30 else "📈 Verbesserung",
                })
    result.sort(key=lambda x: -x["improvement"])
    record_delta = clan_records.get("delta", {}) if isinstance(clan_records, dict) else {}
    return {
        "comebacks": result[:10],
        "all_time_record": {"name": record_delta.get("name"), "improvement": record_delta.get("val")} if record_delta else None,
    }


@router.get("/players/activity")
def players_activity():
    """Alle Spieler mit letztem Kampf, Beitrittsdatum und Teilnahmequote."""
    all_players = build_players_enriched()
    top_decks_data = load_top_decks()
    last_battles = top_decks_data.get("_metadata", {}).get("last_battles", {})
    now = datetime.now(timezone.utc)
    result = []
    for tag, p in all_players.items():
        last_battle_raw = last_battles.get(tag)
        last_battle = None
        days_since_battle = None
        if last_battle_raw:
            try:
                dt = datetime.strptime(last_battle_raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
                last_battle = dt.isoformat()
                days_since_battle = (now - dt).days
            except Exception:
                pass
        result.append({
            "name": p["name"],
            "tag": tag,
            "role": p.get("role"),
            "first_seen": p.get("first_seen"),
            "last_seen": p.get("last_seen"),
            "last_battle": last_battle,
            "days_since_last_battle": days_since_battle,
            "participation_count": p.get("participation_count", 0),
            "wars_in_window": p.get("wars_in_window", 0),
            "score": p.get("score", 0),
        })
    result.sort(key=lambda x: (x["days_since_last_battle"] is None, x.get("days_since_last_battle") or 0), reverse=True)
    return {"players": result, "total": len(result)}


@router.get("/players/search")
def players_search(name: str = Query(..., description="Namensteil des Spielers (Teilstring, nicht case-sensitiv)")):
    """Sucht Spieler im Clan anhand eines Namens."""
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Bitte mindestens 2 Zeichen eingeben.")
    query = name.strip().lower()
    all_players = build_players_enriched()
    results = []
    for tag, p in all_players.items():
        if query in p.get("name", "").lower():
            dabei_total = p.get("wars_in_history_window", 0)
            dabei_count = p.get("wars_with_participation", 0)
            results.append({
                "name": p["name"],
                "tag": tag,
                "role": p.get("role", "member"),
                "wars_with_participation": dabei_count,
                "wars_in_history_window": dabei_total,
                "dabei_display": f"{dabei_count}/{dabei_total}" if dabei_total > 0 else "–",
                "fame_per_deck": p.get("fame_per_deck", 0),
                "strikes": p.get("strikes", 0),
            })
    results.sort(key=lambda x: x["name"].lower())
    return {"results": results, "count": len(results)}


@router.get("/players/inaktiv")
def players_inaktiv(days: int = Query(default=3, ge=1, le=30, description="Inaktiv seit X Tagen")):
    """Spieler, die seit mindestens X Tagen keinen Kampf gespielt haben."""
    all_players = build_players_enriched()
    top_decks_data = load_top_decks()
    last_battles = top_decks_data.get("_metadata", {}).get("last_battles", {})
    now = datetime.now(timezone.utc)
    inaktiv = []
    for tag, p in all_players.items():
        last_battle_raw = last_battles.get(tag)
        days_since = None
        last_battle = None
        if last_battle_raw:
            try:
                dt = datetime.strptime(last_battle_raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
                days_since = (now - dt).days
                last_battle = dt.isoformat()
            except Exception:
                pass
        if days_since is None or days_since >= days:
            inaktiv.append({
                "name": p["name"],
                "tag": tag,
                "role": p.get("role"),
                "last_battle": last_battle,
                "days_since_last_battle": days_since,
                "score": p.get("score", 0),
                "strikes": p.get("strikes", 0),
                "status": "nie gespielt" if days_since is None else f"seit {days_since} Tagen inaktiv",
            })
    inaktiv.sort(key=lambda x: (x["days_since_last_battle"] is None, x.get("days_since_last_battle") or 0), reverse=True)
    return {"filter_days": days, "count": len(inaktiv), "players": inaktiv}


@router.get("/players/donations")
def players_donations():
    """Spenden-Ranking mit Kategorisierung."""
    all_players = list(build_players_enriched().values())
    result = []
    for p in all_players:
        donations = p.get("donations", 0)
        received = p.get("donations_received", 0)
        ratio = round(donations / received, 2) if received > 0 else None
        if donations > 0 and received > 0:
            category = "🤝 Ausgewogen"
        elif donations > 0 and received == 0:
            category = "💪 Spender"
        elif donations == 0 and received > 0:
            category = "📦 Schmarotzer"
        else:
            category = "💤 Schläfer"
        result.append({"name": p["name"], "tag": p.get("tag"), "role": p.get("role"), "donations": donations, "donations_received": received, "donation_ratio": ratio, "category": category})
    result.sort(key=lambda x: (-x["donations"], x["donations_received"]))
    return {
        "players": result,
        "top_donor": result[0]["name"] if result else None,
        "total_donated": sum(p["donations"] for p in result),
        "total_received": sum(p["donations_received"] for p in result),
    }


@router.get("/players/meta")
def players_meta():
    """Trends, Streaks und Comebacks aller Spieler in einem Aufruf."""
    all_players = build_players_enriched()
    history = score_history_by_player()
    clan_records = load_records()
    trends = []
    streaks = []
    comebacks = []
    for tag, p in all_players.items():
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        trend = compute_trend(scores) if scores else "–"
        streak = compute_streak(scores)
        delta = round(scores[-1] - scores[-2], 2) if len(scores) >= 2 else None
        trends.append({"name": p["name"], "tag": tag, "score": p.get("score", 0), "trend": trend, "streak": streak, "streak_badge": f"🔥 {streak}" if streak >= 3 else None, "delta": delta, "delta_symbol": "📈" if delta is not None and delta > 5 else "📉" if delta is not None and delta < -5 else "➡️" if delta is not None else "–"})
        if streak >= 2:
            streaks.append({"name": p["name"], "tag": tag, "streak": streak, "badge": f"🔥 {streak}x 100%", "score": p.get("score", 0)})
        if len(scores) >= 2:
            improvement = round(scores[-1] - scores[-2], 2)
            if improvement > 0:
                comebacks.append({"name": p["name"], "tag": tag, "previous_score": scores[-2], "current_score": scores[-1], "improvement": improvement, "badge": "🚀 Mega-Comeback!" if improvement >= 30 else "📈 Verbesserung"})
    trends.sort(key=lambda x: -x["score"])
    streaks.sort(key=lambda x: -x["streak"])
    comebacks.sort(key=lambda x: -x["improvement"])
    record_delta = clan_records.get("delta", {}) if isinstance(clan_records, dict) else {}
    return {
        "trends": trends,
        "streaks": {"players": streaks, "message": f"{len(streaks)} Spieler mit aktivem Streak" if streaks else "Aktuell keine aktiven Streaks"},
        "comebacks": {"top10": comebacks[:10], "all_time_record": {"name": record_delta.get("name"), "improvement": record_delta.get("val")} if record_delta else None},
    }


@router.get("/compare")
def compare(tags: str = Query(..., description="Kommagetrennte Spieler-Tags (max. 4)")):
    """Vergleicht bis zu 4 Spieler direkt miteinander."""
    tag_list = [normalize_tag(t.strip()) for t in tags.split(",")]
    if len(tag_list) < 2:
        raise HTTPException(status_code=400, detail="Mindestens 2 Tags angeben (kommagetrennt)")

    all_players = build_players_enriched()
    history = score_history_by_player()
    comparison = []
    for tag in tag_list[:4]:
        if tag not in all_players:
            comparison.append({"tag": tag, "error": "Spieler nicht gefunden"})
            continue
        p = all_players[tag]
        entries = history.get(normalize_name(p["name"]), [])
        scores = [e["score"] for e in entries]
        focus = get_focus_badge(p.get("score", 0), p.get("fame_per_deck", 0), p.get("participation_count", 0))
        promo_status = build_promotion_status(p)
        comparison.append({
            "name": p["name"], "tag": tag, "role": p.get("role"),
            "score": p.get("score", 0), "fame_per_deck": p.get("fame_per_deck", 0),
            "trophies": p.get("trophies", 0), "donations": p.get("donations", 0),
            "donations_received": p.get("donations_received", 0), "strikes": p.get("strikes", 0),
            "participation_count": p.get("participation_count", 0), "focus": focus,
            "trend": compute_trend(scores) if scores else "",
            "streak": compute_streak(scores),
            "promotion_progress_pct": promo_status["overall_progress_pct"],
            "promotion_ready": promo_status["eligible"],
        })

    valid = [c for c in comparison if "error" not in c]
    verdict = None
    if len(valid) >= 2:
        verdict = {
            "best_score": max(valid, key=lambda x: x["score"])["name"],
            "best_fame_per_deck": max(valid, key=lambda x: x["fame_per_deck"])["name"],
            "most_trophies": max(valid, key=lambda x: x["trophies"])["name"],
            "top_donor": max(valid, key=lambda x: x["donations"])["name"],
            "promotion_leader": max(valid, key=lambda x: x["promotion_progress_pct"])["name"],
        }
    return {"players": comparison, "verdict": verdict}
