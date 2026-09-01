# Zentrale Konfiguration – alle Score-Schwellenwerte an einem Ort
# Änderungen hier wirken sich auf alle Mode-Skripte aus.

# --- Score-Formel ---
# Gewichtung der drei Faktoren (Summe = 100)
SCORE_GEWICHT_DECKS       = 50   # Deck-Vollständigkeit: wurden die möglichen Decks gespielt?
SCORE_GEWICHT_ANWESENHEIT = 30   # Dabei-Quote: war der Spieler in den Kriegen dabei?
SCORE_GEWICHT_QUALITAET   = 20   # Qualität: normierter Ø Fame pro Deck
QUALITAET_FAME_MIN        = 75   # Ø Punkte/Deck: ab hier zählt die Qualität überhaupt
QUALITAET_FAME_MAX        = 225  # Ø Punkte/Deck: ab hier volle Qualitätswertung

# --- Verwarnungs- & Kick-Schwellen ---
STRIKE_THRESHOLD    = 50   # Score unter diesem Wert → Verwarnung
KICK_THRESHOLD      = 40   # Score unter diesem Wert → Kick-Kandidat

# --- Beförderungs-Schwelle ---
PROMOTION_SCORE_MIN = 85   # Score über diesem Wert (+ keine Strikes) → Beförderungskandidat

# --- Smart-Mode Klassifizierung ---
SMART_RISIKO_THRESHOLD = 60   # Score unter diesem Wert → RISIKO
SMART_STARK_THRESHOLD  = 80   # Score über diesem Wert  → STARK

# --- Coaching-Stufen ---
COACHING_WARN_THRESHOLD = STRIKE_THRESHOLD  # "Mehr Teilnahme notwendig"
COACHING_MID_THRESHOLD  = 70               # "Konstanz verbessern"
# Score >= COACHING_MID_THRESHOLD → "Weiter so"

# --- Deck-Qualität ---
DROPPER_THRESHOLD  = 130   # Ø Punkte pro Deck unter diesem Wert → Hinweis
MIN_PARTICIPATION  = 1     # Welpenschutz: Nur der erste Clankrieg ist geschützt

# --- Spieler-Badges ---
BADGE_STARK_SCORE  = 90    # ⭐ stark: Score-Schwelle
BADGE_STARK_FAME   = 185   # ⭐ stark: Ø Punkte-Schwelle
BADGE_STABIL_SCORE = 75    # 🛡️ stabil: Score-Schwelle
BADGE_STABIL_FAME  = 145   # 🛡️ stabil: Ø Punkte-Schwelle

# --- Tier-Grenzen ---
TIER_SEHR_STARK    = 90    # Tier: Sehr stark
TIER_SOLIDE        = 75    # Tier: Solide Basis

# --- Clan-Ampel ---
CLAN_RELIABLE_GREEN  = 85  # Zuverlässigkeit: Grün ab
CLAN_RELIABLE_YELLOW = 70  # Zuverlässigkeit: Gelb ab

# --- Beförderung ---
PROMOTION_DONATIONS_MIN = 50  # Mindest-Spenden für Beförderung
