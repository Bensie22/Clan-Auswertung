from fastapi import APIRouter, HTTPException

from app.utils import validate_tag, normalize_name
from app.services import (
    build_players_enriched, build_promotion_candidates,
    get_focus_badge, build_promotion_status,
    calculate_teamplay_score_from_stats,
)
from config import (
    STRIKE_THRESHOLD, BADGE_STARK_SCORE, BADGE_STARK_FAME,
    BADGE_STABIL_FAME, DROPPER_THRESHOLD, MIN_PARTICIPATION,
    PROMOTION_SCORE_MIN,
)

router = APIRouter()
PROMOTION_DONATIONS_MIN = 50


@router.get("/coaching/tips")
def coaching_tips():
    """Aktuelle Coaching-Hinweise für den Clan-Leader."""
    all_players = list(build_players_enriched().values())
    tips = []

    low_performers = [p for p in all_players if p.get("score", 0) < STRIKE_THRESHOLD]
    if low_performers:
        names = ", ".join(p["name"] for p in low_performers[:5])
        tips.append({"category": "⚠️ Leistung", "priority": "hoch", "tip": f"{len(low_performers)} Spieler unter {STRIKE_THRESHOLD}% Score: {names}", "action": "Strike-Gespräch führen oder Warnung aussprechen"})

    high_strikes = [p for p in all_players if p.get("strikes", 0) >= 3]
    if high_strikes:
        names = ", ".join(p["name"] for p in high_strikes)
        tips.append({"category": "🚨 Strike-Alarm", "priority": "hoch", "tip": f"{len(high_strikes)} Spieler mit ≥3 Strikes: {names}", "action": "Letzte Warnung oder Kick erwägen"})

    fame_values = [p.get("fame_per_deck", 0) for p in all_players if p.get("fame_per_deck", 0) > 0]
    avg_fame = sum(fame_values) / len(fame_values) if fame_values else 0
    if avg_fame < BADGE_STABIL_FAME:
        tips.append({"category": "🎯 Deck-Qualität", "priority": "mittel", "tip": f"Clan-Durchschnitt: {round(avg_fame, 1)} Fame/Deck (Ziel: ≥{BADGE_STABIL_FAME})", "action": "Deck-Optimierung empfehlen – Top-Decks im Clan-Chat teilen"})

    teamplay = calculate_teamplay_score_from_stats(all_players)
    if teamplay["score"] < 35:
        tips.append({"category": "🤝 Teamplay", "priority": "mittel", "tip": f"Teamplay-Score: {teamplay['score']} – {teamplay['leecher']} Schmarotzer, {teamplay['sleeper']} Schläfer", "action": "Spendenkultur ansprechen – Erinnerung im Chat posten"})

    promo_candidates = build_promotion_candidates()
    if promo_candidates:
        names = ", ".join(p["name"] for p in promo_candidates[:3])
        tips.append({"category": "🎖️ Beförderungen", "priority": "niedrig", "tip": f"{len(promo_candidates)} Spieler bereit für Elder-Beförderung: {names}", "action": "Beförderung durchführen und öffentlich beglückwünschen"})

    if not tips:
        tips.append({"category": "✅ Alles gut", "priority": "info", "tip": "Clan läuft gut – keine kritischen Punkte erkennbar", "action": "Weiter so! Positive Leistungen öffentlich loben"})

    return {"tips": tips, "total": len(tips), "high_priority": sum(1 for t in tips if t["priority"] == "hoch")}


@router.get("/coaching/messages")
def coaching_messages():
    """Vorgefertigte Nachrichten-Templates für häufige Clan-Situationen."""
    return {
        "hinweis": "Ersetze {name}, {score}, {strikes} mit echten Werten aus /player/{tag} oder /warnings",
        "categories": {
            "willkommen": {"title": "Willkommensnachricht", "templates": ["Willkommen im Clan, {name}! 🎉 Schön, dass du dabei bist. Lies dir die Clan-Regeln durch und meld dich bei Fragen!", "Hey {name}, herzlich willkommen bei HAMBURG! 🏆 Viel Spaß beim Spielen – wir freuen uns auf dich!"]},
            "krieg_erinnerung": {"title": "Kriegs-Erinnerung", "templates": ["⚔️ Kriegstag läuft! Bitte alle Decks nutzen – auch 1 Deck zählt! Gemeinsam schaffen wir das! 💪", "Noch offene Decks da? Jetzt ist die Zeit! Jedes Deck zählt für den Clan. Los geht's! 🔥", "Kriegstag Reminder: Alle Decks spielen, egal mit welchem Score. Dabei sein ist alles! ⚔️"]},
            "warnung": {"title": "Warnung / Strike", "templates": ["{name}, dein Score liegt bei {score}% – das ist unter unserer Mindestgrenze von 50%. Das ist Strike {strikes}. Bitte beim nächsten Krieg mehr Decks nutzen.", "Hey {name}, kurze Rückmeldung: {score}% ist nicht ausreichend. Wir erwarten mindestens 50%. Beim nächsten Krieg bitte vollen Einsatz! 🙏"]},
            "befoerderung": {"title": "Beförderung zu Elder", "templates": ["🎖️ Herzlichen Glückwunsch, {name}! Du wirst heute zum Elder befördert. Dein Einsatz hat das verdient. Weiter so! 🏆", "Großes Lob an {name}! 🌟 Für deinen konstanten Einsatz wirst du zum Elder befördert. Danke für alles!"]},
            "lob": {"title": "Lob / Anerkennung", "templates": ["Riesenlob an {name} für {score}% Score diese Woche! 🔥 So macht Clan-Krieg Spaß!", "Top-Performance von {name} mit {score}%! ⭐ Du bist ein echter Leistungsträger!", "Shoutout an {name} – perfekte Woche mit 100%! 🏆🔥 Respekt!"]},
            "kick": {"title": "Kick-Nachricht", "templates": ["{name}, leider müssen wir dich aufgrund anhaltend niedriger Leistungen entfernen. Du kannst dich gerne wieder bewerben, wenn du aktiver spielen kannst.", "Hey {name}, wir haben dich leider aus dem Clan entfernt. Du bist jederzeit herzlich willkommen zurückzukehren, wenn die Zeit passt!"]},
        },
    }


@router.get("/promotions/progress")
def promotions_progress():
    """Beförderungsfortschritt aller Members."""
    all_players = list(build_players_enriched().values())
    result = []
    for p in all_players:
        role = normalize_name(p.get("role", "member"))
        if role in {"member", "mitglied", ""}:
            status = build_promotion_status(p)
            result.append({"name": p["name"], "tag": p.get("tag"), **status})
    result.sort(key=lambda x: -x["overall_progress_pct"])
    return {"candidates": result, "ready_count": sum(1 for r in result if r["eligible"]), "total_members": len(result)}


@router.get("/player/{player_tag}/coaching")
def player_coaching(player_tag: str):
    """Individueller Coaching-Hinweis für einen Spieler."""
    tag = validate_tag(player_tag)
    all_players = build_players_enriched()
    if tag not in all_players:
        raise HTTPException(status_code=404, detail="Spieler nicht gefunden")

    p = all_players[tag]
    score = p.get("score", 0)
    fame = p.get("fame_per_deck", 0)
    strikes = p.get("strikes", 0)
    donations = p.get("donations", 0)
    received = p.get("donations_received", 0)
    participation = p.get("participation_count", 0)
    tips = []
    messages = []

    if participation <= MIN_PARTICIPATION:
        tips.append("🌱 Noch im Welpenschutz – einfach mitspielen, noch keine Bewertung!")
    elif score < STRIKE_THRESHOLD:
        tips.append(f"⚠️ Score {score}% unter Grenze ({STRIKE_THRESHOLD}%) – mehr Kriege aktiv mitspielen")
        if strikes > 0:
            tips.append(f"🚨 {strikes} Strike(s) vorhanden – dringend verbessern")
        messages.append(f"Hey {p['name']}, dein Score liegt bei {score}%. Bitte beim nächsten Krieg alle Decks nutzen. Das wäre Strike {strikes + 1}, wenn es so weitergeht.")
    elif score >= BADGE_STARK_SCORE and fame >= BADGE_STARK_FAME:
        tips.append(f"⭐ Top-Performer! Score {score}%, {fame} Fame/Deck – weiter so!")
        messages.append(f"Riesenlob an {p['name']}! {score}% Score und starke Deck-Qualität – echter Leistungsträger! 🏆")
    elif fame < DROPPER_THRESHOLD:
        tips.append(f"🎯 Fame/Deck ({fame}) ausbaufähig – stärkere Decks nutzen (Ziel: ≥{DROPPER_THRESHOLD})")
        messages.append(f"Hey {p['name']}, du bist dabei – super! Probiere mal stärkere Decks für mehr Punkte. 💪")
    else:
        tips.append(f"🛡️ Solide Leistung mit {score}% Score – weiter so!")

    if donations == 0 and received > 0:
        tips.append(f"📦 {received} Karten erhalten, aber nichts gespendet – bitte auch spenden!")
        messages.append(f"Hey {p['name']}, denk bitte ans Spenden! Du hast {received} Karten bekommen, aber noch nichts zurückgegeben. 🙏")

    focus = get_focus_badge(score, fame, participation)
    return {"name": p["name"], "tag": tag, "score": score, "fame_per_deck": fame, "strikes": strikes, "focus": focus, "coaching_tips": tips, "suggested_messages": messages}
