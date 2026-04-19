from typing import Any, Dict, List

from app.utils import normalize_name
from app.data import (
    load_current_players, load_donations_map, latest_score_map,
    load_player_stats, strikes_for_player,
)
from config import (
    STRIKE_THRESHOLD, PROMOTION_SCORE_MIN,
    DROPPER_THRESHOLD, MIN_PARTICIPATION,
    BADGE_STARK_SCORE, BADGE_STARK_FAME,
    BADGE_STABIL_SCORE, BADGE_STABIL_FAME,
    TIER_SOLIDE,
)

PROMOTION_DONATIONS_MIN = 50


def compute_trend(scores: List[float]) -> str:
    return "".join([
        "🟢" if s >= TIER_SOLIDE else
        "🟡" if s >= STRIKE_THRESHOLD else
        "🔴"
        for s in scores[-6:]
    ])


def compute_streak(scores: List[float]) -> int:
    streak = 0
    for s in reversed(scores):
        if s >= 100.0:
            streak += 1
        else:
            break
    return streak


def get_focus_badge(score: float, fame_per_deck: float, participation_count: int) -> Dict[str, str]:
    if participation_count <= MIN_PARTICIPATION:
        return {
            "badge": "🌱 neu dabei",
            "label": "NEWCOMER",
            "description": "Noch im Welpenschutz – Bewertung startet nach 3 Kriegen",
        }
    if score >= BADGE_STARK_SCORE and fame_per_deck >= BADGE_STARK_FAME:
        return {
            "badge": "⭐ stark",
            "label": "STARK",
            "description": "Sehr starke Leistung in Krieg und Deck-Qualität",
        }
    if score >= BADGE_STABIL_SCORE and fame_per_deck >= BADGE_STABIL_FAME:
        return {
            "badge": "🛡️ stabil",
            "label": "STABIL",
            "description": "Solider und verlässlicher Mitspieler",
        }
    if fame_per_deck < DROPPER_THRESHOLD and participation_count > MIN_PARTICIPATION:
        return {
            "badge": "⚠️ ausbaufähig",
            "label": "DROPPER",
            "description": "Niedrige Punkte pro Deck – Deck-Qualität verbessern",
        }
    return {
        "badge": "👀 auffällig",
        "label": "WATCH",
        "description": "Im Auge behalten",
    }


def build_promotion_status(p: Dict[str, Any]) -> Dict[str, Any]:
    score = p.get("score", 0)
    donations = p.get("donations", 0)
    strikes = p.get("strikes", 0)
    role = normalize_name(p.get("role", "member"))

    missing_score = max(0.0, round(PROMOTION_SCORE_MIN - score, 2))
    missing_donations = max(0, PROMOTION_DONATIONS_MIN - donations)

    eligible = (
        role in {"member", "mitglied", ""}
        and score >= PROMOTION_SCORE_MIN
        and donations >= PROMOTION_DONATIONS_MIN
        and strikes == 0
    )

    score_progress = min(100.0, round(score / PROMOTION_SCORE_MIN * 100, 1)) if PROMOTION_SCORE_MIN else 100.0
    donation_progress = min(100.0, round(donations / PROMOTION_DONATIONS_MIN * 100, 1)) if PROMOTION_DONATIONS_MIN else 100.0
    strike_ok = strikes == 0
    overall_progress = round((score_progress + donation_progress + (100.0 if strike_ok else 0.0)) / 3, 1)

    missing_items = []
    if missing_score > 0:
        missing_items.append(f"{missing_score}% Score fehlen")
    if missing_donations > 0:
        missing_items.append(f"{missing_donations} Spenden fehlen")
    if strikes > 0:
        missing_items.append(f"{strikes} Strike(s) vorhanden")

    return {
        "eligible": eligible,
        "current_role": p.get("role", "member"),
        "score": score,
        "score_progress_pct": score_progress,
        "donations": donations,
        "donation_progress_pct": donation_progress,
        "strikes": strikes,
        "strike_free": strike_ok,
        "overall_progress_pct": overall_progress,
        "missing": missing_items,
        "summary": (
            "Bereit für Beförderung zu Elder! 🎉"
            if eligible
            else ("Fehlt: " + "; ".join(missing_items) if missing_items else "Bereits befördert oder nicht geeignet")
        ),
    }


def calculate_teamplay_score_from_stats(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(players)
    if total == 0:
        return {"score": 0, "donors": 0, "leecher": 0, "sleeper": 0, "signal": "unbekannt", "total_players": 0}

    donors = sum(1 for p in players if p.get("donations", 0) > 0)
    leecher = sum(
        1 for p in players
        if p.get("donations", 0) == 0
        and p.get("donations_received", 0) > 0
        and p.get("participation_count", 0) > MIN_PARTICIPATION
    )
    sleeper = sum(1 for p in players if p.get("donations", 0) == 0 and p.get("donations_received", 0) == 0)

    donor_share = (donors / total) * 100
    leecher_share = (leecher / total) * 100
    sleeper_share = (sleeper / total) * 100

    score = round(max(0, min(100, donor_share - (leecher_share * 0.7) - (sleeper_share * 0.3))))
    signal = "sehr gut 🟢" if score >= 60 else "okay 🟡" if score >= 35 else "kritisch 🔴"

    return {
        "score": score,
        "signal": signal,
        "donors": donors,
        "leecher": leecher,
        "sleeper": sleeper,
        "total_players": total,
        "donor_share_pct": round(donor_share, 1),
        "leecher_share_pct": round(leecher_share, 1),
        "sleeper_share_pct": round(sleeper_share, 1),
    }


def build_players_enriched() -> Dict[str, Dict[str, Any]]:
    members = load_current_players()
    donations = load_donations_map()
    scores = latest_score_map()
    stats = load_player_stats()
    enriched: Dict[str, Dict[str, Any]] = {}
    for tag, base in members.items():
        score_entry = scores.get(normalize_name(base.get("name"))) or {}
        donation_entry = donations.get(tag, {"donations": 0, "received": 0})
        stat_entry = stats.get(tag, {})
        enriched[tag] = {
            **base,
            "donations": stat_entry.get("donations", donation_entry.get("donations", 0)),
            "donations_received": stat_entry.get("donations_received", donation_entry.get("received", 0)),
            "score": stat_entry.get("score", score_entry.get("score", 0.0)),
            "trophies": stat_entry.get("trophies", score_entry.get("trophies", 0)),
            "score_date": score_entry.get("date"),
            "strikes": strikes_for_player(tag, base.get("name", "")),
            "fame_per_deck": stat_entry.get("fame_per_deck", 0),
            "war_points_total": stat_entry.get("war_points_total", 0),
            "wars_with_participation": stat_entry.get("participation_count", 0),
            "wars_in_history_window": stat_entry.get("wars_in_window", 0),
            "participation_count": stat_entry.get("participation_count", 0),
            "total_decks": stat_entry.get("total_decks", 0),
            "wars_in_window": stat_entry.get("wars_in_window", 0),
        }
    return enriched


def build_warning_candidates() -> List[Dict[str, Any]]:
    players = build_players_enriched()
    out: List[Dict[str, Any]] = []
    for tag, p in players.items():
        reasons: List[str] = []
        if p["score"] < STRIKE_THRESHOLD:
            reasons.append(f"Score unter {STRIKE_THRESHOLD}")
        if p["strikes"] >= 2:
            reasons.append("bereits mehrere Strikes vorhanden")
        if reasons:
            out.append({
                "name": p["name"],
                "tag": tag,
                "role": p["role"],
                "score": p["score"],
                "donations": p["donations"],
                "donations_received": p["donations_received"],
                "trophies": p["trophies"],
                "strikes": p["strikes"],
                "reason": "; ".join(reasons),
                "recommended_action": "warning",
            })
    return sorted(out, key=lambda x: (x["score"], -x["strikes"], x["donations"]))


def build_promotion_candidates() -> List[Dict[str, Any]]:
    players = build_players_enriched()
    out: List[Dict[str, Any]] = []
    for tag, p in players.items():
        role = normalize_name(p.get("role", "member"))
        if role not in {"member", "mitglied", ""}:
            continue
        if p["score"] < PROMOTION_SCORE_MIN:
            continue
        if p["donations"] < PROMOTION_DONATIONS_MIN:
            continue
        if p["strikes"] > 0:
            continue
        out.append({
            "name": p["name"],
            "tag": tag,
            "current_role": p.get("role", "member"),
            "score": p["score"],
            "donations": p["donations"],
            "donations_received": p["donations_received"],
            "trophies": p["trophies"],
            "recommended_action": "promote_to_elder",
        })
    return sorted(out, key=lambda x: (-x["score"], -x["donations"], -x["trophies"]))
