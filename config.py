# Zentrale Konfiguration – alle Score-Schwellenwerte an einem Ort
# Änderungen hier wirken sich auf alle Mode-Skripte aus.

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
MIN_PARTICIPATION  = 3     # Welpenschutz: Bis einschließlich 3 Teilnahmen keine Strafen

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
