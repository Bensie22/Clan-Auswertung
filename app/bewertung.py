"""Bewertung: der gewichtete Score eines Spielers aus seiner Kriegsteilnahme.

Der Score ist die Grundlage für Verwarnungen, Kicks und Beförderungen. Er lag
vorher inline in ``generate_html_report`` und war damit weder aufrufbar noch
testbar. Hier ist er eine reine Funktion über Kriegsdaten – Urlaub, Strikes und
alles andere an Maßnahmen bleibt beim Aufrufer.

    bewerte(Kriegsteilnahme) -> Bewertung
"""
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping

from config import (
    MIN_PARTICIPATION,
    QUALITAET_FAME_MAX,
    QUALITAET_FAME_MIN,
    SCORE_GEWICHT_ANWESENHEIT,
    SCORE_GEWICHT_DECKS,
    SCORE_GEWICHT_QUALITAET,
)

# 4 Kriegstage x 4 Decks. Eine Supercell-Regel, kein Schwellenwert – deshalb
# steht die Zahl hier und nicht in config.py.
DECKS_PRO_KRIEG = 16

# Ø Punkte pro Deck werden über die letzten Kriege geglättet. Ein einzelner
# Krieg mit schlechtem Matchmaking soll das Bild nicht kippen.
ROLLING_KRIEGE = 4

# Fester Schlüssel für den laufenden Krieg in CSV und Historie.
# "z" sortiert über Ziffern – die Spalte steht dadurch immer ganz vorne.
LAUFENDER_KRIEG_ID   = "zzzcurrent"
LAUFENDE_FAME_SPALTE = f"s_{LAUFENDER_KRIEG_ID}_fame"

# Nenner der Qualitäts-Normierung. Einmal beim Import berechnet und nie 0:
# setzt jemand QUALITAET_FAME_MAX <= QUALITAET_FAME_MIN, wird daraus eine harte
# Ja/Nein-Grenze bei QUALITAET_FAME_MIN. Ein Konfigurationsfehler darf den Cron
# nicht mit einer ZeroDivisionError abbrechen – er schreibt in jedem Lauf State.
QUALITAETS_SPANNE = max(1, QUALITAET_FAME_MAX - QUALITAET_FAME_MIN)


@dataclass(frozen=True)
class Kriegswoche:
    """Ein Krieg aus Sicht eines Spielers.

    ``laufend`` markiert den noch nicht abgeschlossenen Krieg.
    """
    fame: int
    decks: int
    laufend: bool = False


@dataclass(frozen=True)
class Kriegsteilnahme:
    """Alles, was die Bewertung über einen Spieler wissen muss.

    ``wochen`` ist absteigend sortiert – der neueste Krieg zuerst.

    ``kriege_im_fenster`` muss mitgegeben werden: aus 0 Fame und 0 Decks lässt
    sich nicht ableiten, ob der Spieler im Clan war und nichts gespielt hat oder
    ob er damals gar nicht dabei war. Alle anderen Kennzahlen leitet das Modul
    selbst ab.
    """
    wochen: List[Kriegswoche]
    kriege_im_fenster: int


@dataclass(frozen=True)
class Bewertung:
    """Das Ergebnis: der Score und die Kennzahlen, aus denen er entsteht."""
    score: float
    fame_per_deck: int
    deck_vollstaendigkeit: float
    anwesenheits_rate: float
    qualitaet: float
    decks_gesamt: int
    kriege_mit_teilnahme: int
    max_moegliche_decks: int
    war_points_total: int
    ist_welpenschutz: bool


def fame_spalten_sortiert(spalten: Iterable[Any]) -> List[str]:
    """Die Fame-Spalten eines Clan-Exports, neuester Krieg zuerst.

    Absteigend sortiert, und weil "z" über Ziffern sortiert, landet der laufende
    Krieg dadurch immer an erster Stelle.
    """
    return sorted(
        [str(s) for s in spalten if str(s).startswith("s_") and str(s).endswith("_fame")],
        reverse=True,
    )


def kriegsteilnahme_aus_csv_zeile(
    zeile: Mapping[str, Any],
    fame_spalten: List[str],
    kriege_im_fenster: int,
) -> Kriegsteilnahme:
    """Baut die Kriegsteilnahme aus einer Zeile des Clan-Exports.

    ``fame_spalten`` kommt aus :func:`fame_spalten_sortiert` und ist loop-invariant,
    wird deshalb übergeben statt je Zeile neu berechnet.

    ``kriege_im_fenster`` muss aus ``player_participating_count`` kommen: die Zeile
    selbst schreibt 0 Fame und 0 Decks sowohl für "Krieg existierte, Spieler nicht
    dabei" als auch für "dabei, nichts gespielt".
    """
    return Kriegsteilnahme(
        wochen=[
            Kriegswoche(
                fame=int(zeile.get(spalte, 0) or 0),
                decks=int(zeile.get(spalte.replace("_fame", "_decks_used"), 0) or 0),
                laufend=(spalte == LAUFENDE_FAME_SPALTE),
            )
            for spalte in fame_spalten
        ],
        kriege_im_fenster=kriege_im_fenster,
    )


def bewerte(teilnahme: Kriegsteilnahme) -> Bewertung:
    """Gewichteter 3-Faktor-Score.

    50% Deck-Vollständigkeit (wurden die möglichen Decks gespielt?),
    30% Dabei-Quote (war der Spieler in den Kriegen überhaupt dabei?),
    20% Qualität (normierter Ø Fame pro Deck).
    """
    # Der laufende Krieg ist noch nicht abgeschlossen und zählt deshalb nicht in
    # Deck-Vollständigkeit und Dabei-Quote – unfair, solange er läuft.
    abgeschlossen = [w for w in teilnahme.wochen if not w.laufend]

    decks_gesamt = sum(w.decks for w in abgeschlossen)
    kriege_mit_teilnahme = sum(1 for w in abgeschlossen if w.decks > 0)
    kriege_im_fenster = teilnahme.kriege_im_fenster

    anwesenheits_rate = (
        kriege_mit_teilnahme / kriege_im_fenster if kriege_im_fenster > 0 else 0.0
    )
    max_moegliche_decks = kriege_mit_teilnahme * DECKS_PRO_KRIEG
    deck_vollstaendigkeit = (
        decks_gesamt / max_moegliche_decks if max_moegliche_decks > 0 else 0.0
    )

    # Ø Punkte/Deck schließen den laufenden Krieg bewusst mit ein: die Kennzahl
    # soll den aktuellen Stand zeigen, nicht den der letzten abgeschlossenen
    # Woche. Damit fließt der laufende Krieg über die Qualität mit 20% in den
    # Score ein, während er die übrigen 80% nicht berührt.
    rolling = teilnahme.wochen[:ROLLING_KRIEGE]
    rolling_fame = sum(w.fame for w in rolling)
    rolling_decks = sum(w.decks for w in rolling)
    fame_per_deck = round(rolling_fame / rolling_decks) if rolling_decks > 0 else 0

    qualitaet = (
        max(0.0, min(1.0, (fame_per_deck - QUALITAET_FAME_MIN) / QUALITAETS_SPANNE))
        if fame_per_deck > 0
        else 0.0
    )

    score = round(
        SCORE_GEWICHT_DECKS * deck_vollstaendigkeit +
        SCORE_GEWICHT_ANWESENHEIT * anwesenheits_rate +
        SCORE_GEWICHT_QUALITAET * qualitaet,
        2
    )

    return Bewertung(
        score=score,
        fame_per_deck=fame_per_deck,
        deck_vollstaendigkeit=deck_vollstaendigkeit,
        anwesenheits_rate=anwesenheits_rate,
        qualitaet=qualitaet,
        decks_gesamt=decks_gesamt,
        kriege_mit_teilnahme=kriege_mit_teilnahme,
        max_moegliche_decks=max_moegliche_decks,
        war_points_total=sum(w.fame for w in teilnahme.wochen),
        ist_welpenschutz=kriege_mit_teilnahme <= MIN_PARTICIPATION,
    )
