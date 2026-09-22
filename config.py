# Zentrale Konfiguration – alle Score-Schwellenwerte an einem Ort
# Änderungen hier wirken sich auf alle Mode-Skripte aus.

# --- Verwarnungs- & Kick-Schwellen ---
STRIKE_THRESHOLD    = 50   # Score unter diesem Wert → Verwarnung
KICK_THRESHOLD      = 40   # Score unter diesem Wert → Kick-Kandidat

# Karenzzeit nach einer Regeländerung: Bis zu diesem Tag (einschließlich) werden
# KEINE automatischen Maßnahmen ausgeführt – keine Verwarnung, keine Degradierung,
# kein Ausschluss. Die neuen Werte sind trotzdem sofort sichtbar.
#
# Warum: Die Umstellung auf SCORE_MODELL_ERFUELLUNG bewertet zehn Wochen
# Vergangenheit rückwirkend nach Regeln, die es damals nicht gab. Wer unter den
# alten Regeln sicher war, würde sonst beim ersten Wochenlauf degradiert oder
# entfernt – nicht wegen seines Verhaltens, sondern weil wir die Messlatte
# verschoben haben. Die Karenzzeit gibt allen die Chance, den neuen Wert zu sehen
# und zu reagieren.
#
# Format "JJJJ-MM-TT" (Europe/Berlin). None = keine Karenzzeit.
# Läuft von selbst ab – nach dem Stichtag greifen die Regeln wieder normal.
STRIKES_AUSGESETZT_BIS = "2026-10-20"

# --- Beförderungs-Schwelle ---
# Maßgeblich für Beförderungen ist allein PROMOTION_FAME_MIN (weiter unten).
# Die frühere zweite Kennzahl PROMOTION_SCORE_MIN (Score >= 85) wurde im August 2026
# entfernt: Website-Badge und Pipeline haben unterschiedliche Werte gemeldet, sodass
# ein Mitglied auf der Seite "➔ BEFÖRDERN" sehen konnte, ohne in der Auswertung
# Beförderungskandidat zu sein.

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

# --- Deck-Vollständigkeit (wer immer dabei ist, aber nie fertig spielt) ---
# AKTIV seit 23.08.2026. Auf False setzen, um sie abzuschalten.
# Hintergrund: Die Anwesenheit zählt pro Krieg binär – wer ein einziges Deck spielt,
# bekommt dieselben 30 Punkte wie jemand mit 16. Dadurch fällt "immer dabei, aber
# nie fertig" durch alle Netze. Diese Regel greift das gezielt auf, ohne den Score
# anzufassen.
DECK_QUOTE_REGEL_AKTIV  = True
DECK_QUOTE_MIN          = 0.85  # Quote darunter → Hinweis
# Drei Bedingungen müssen zusammenkommen, damit niemand zufällig getroffen wird:
DECK_QUOTE_MIN_KRIEGE   = 4     # erst ab so vielen gewerteten Kriegen (kleine Stichprobe)
DECK_QUOTE_MIN_FEHLEND  = 15    # und erst ab so vielen liegengelassenen Decks (Menge)

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

# DIE Beförderungs-Kennzahl: Fame im laufenden Krieg.
# Gilt einheitlich für das "➔ BEFÖRDERN"-Badge auf der Website, die Beförderungs-
# kandidaten der API (/coaching, /promotions) und die Pipeline (full_auto, commander).
# Wer den Wert hier ändert, ändert ihn überall – es gibt bewusst keine zweite Schwelle mehr.
PROMOTION_FAME_MIN = 2800

# =====================================================================
# AKTIVE REGELN (freigegeben am 23.08.2026).
# Auf False setzen, um eine davon wieder abzuschalten.
# =====================================================================

# 1) Ehrlichere Skala: ein Wert statt Anwesenheit + Deck-Nutzung.
#    Erfüllung = gespielte Decks / (Kriege im Clan × 16).
#    Ein komplett verpasster Krieg zählt dadurch automatisch als 0 von 16 –
#    die Anwesenheit steckt implizit drin und muss nicht extra belohnt werden.
#    Heute schenkt die Anwesenheit 30 der 50 nötigen Punkte: Wer immer auftaucht
#    und 4 von 16 Decks spielt, landet bei 52,5 und wird nie verwarnt.
SCORE_MODELL_ERFUELLUNG   = True
SCORE_GEWICHT_ERFUELLUNG  = 80
SCORE_GEWICHT_QUALITAET   = 20

# 2) Konsequenzen sichtbar machen: Zahlen statt Namen.
#    Die Engagierten sehen sonst nie, dass überhaupt etwas passiert.
ZEIGE_KONSEQUENZEN_BLOCK  = True

# 3) Anerkennung für alle, die vollständig liefern (nicht nur Top 3).
ZEIGE_LEISTUNGSTRAEGER    = True
LEISTUNGSTRAEGER_QUOTE    = 0.95   # ab dieser Erfüllung gilt man als Leistungsträger

# 4) Erwartung schon beim Eintritt benennen, statt später zu korrigieren.
ZEIGE_ERWARTUNG_BEITRITT  = True
ERWARTUNG_DECKS_PRO_KRIEG = 14     # von 16

# 5) Ø Fame/Deck über ALLE abgeschlossenen Kriege statt nur der letzten 3–4.
#    Messung: Das 3-Kriege-Fenster schwankt im Schnitt um 24 Fame/Deck, bei
#    einzelnen Spielern um bis zu 39. Bei einer Badge-Grenze von 145 kippen
#    dadurch 21 von 39 Mitgliedern über die Schwelle, ohne ihr Verhalten zu
#    ändern – das ist Rauschen, keine Bewertung. Der Gesamtschnitt glättet
#    stärker (was die ursprüngliche Absicht war) und lässt sich vom Mitglied
#    im Kriegsverlauf selbst nachrechnen.
#    Der laufende Krieg bleibt in beiden Modi außen vor – er ist nicht fertig.
FAME_SCHNITT_ALLE_KRIEGE = True
