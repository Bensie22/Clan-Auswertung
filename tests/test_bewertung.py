"""Tests für die Score-Logik in app/bewertung.py.

Die Golden-Werte in GOLDEN wurden nicht von Hand aus der Formel abgeleitet, sondern
mit dem Code erzeugt, der vor der Extraktion in generate_html_report stand: die
Fixture lief einmal durch die unveränderte Fassung, das erzeugte player_stats.json
ist die Quelle. Sechs der sieben Zeilen stammen aus einem echten Clan-Export, die
siebte ("Nie Dabei") ist konstruiert, weil im Export niemand mit null Teilnahmen
vorkam – auch ihre Werte kommen aus dem Lauf gegen den alten Code.
"""
import csv
from pathlib import Path

from app.bewertung import (
    DECKS_PRO_KRIEG,
    LAUFENDE_FAME_SPALTE,
    QUALITAETS_SPANNE,
    Kriegsteilnahme,
    Kriegswoche,
    bewerte,
    fame_spalten_sortiert,
    kriegsteilnahme_aus_csv_zeile,
)

FIXTURE = Path(__file__).parent / "fixtures" / "clan_export_sample.csv"

# name -> (score, fame_per_deck, kriege_mit_teilnahme, decks_gesamt, war_points_total)
GOLDEN = {
    "Valar Morghulis": (56.25, 350, 1, 2, 2102),    # Welpenschutz, Qualität am Anschlag
    "Bmbeno":          (62.50, 328, 1, 4, 2624),    # Welpenschutz, alle Decks gespielt
    "Milchreis":       (56.71, 0, 7, 80, 13750),    # im Rolling-Fenster keine Decks -> Qualität 0
    "elazeto":         (67.45, 167, 5, 54, 9503),   # nur in 5 von 7 Kriegen dabei
    "maghrebi":        (93.60, 177, 6, 96, 15300),  # bester Score im Sample
    "MF Tarje":        (66.56, 150, 10, 85, 15568), # immer dabei, Decks liegen gelassen
    "Nie Dabei":       (0.0, 0, 0, 0, 0),           # nie dabei -> alle Guards greifen
}


def _lies_fixture():
    with FIXTURE.open(encoding="utf-8") as f:
        zeilen = list(csv.DictReader(f))
    return zeilen, fame_spalten_sortiert(zeilen[0])


def test_fixture_reproduziert_beobachtete_werte():
    zeilen, fame_spalten = _lies_fixture()
    assert LAUFENDE_FAME_SPALTE in fame_spalten
    assert fame_spalten[0] == LAUFENDE_FAME_SPALTE, "laufender Krieg muss vorne stehen"

    geprueft = 0
    for zeile in zeilen:
        name = zeile["player_name"]
        if name not in GOLDEN:
            continue
        erwartet = GOLDEN[name]
        b = bewerte(kriegsteilnahme_aus_csv_zeile(
            zeile, fame_spalten, int(zeile["player_participating_count"] or 0)
        ))
        assert (
            b.score,
            b.fame_per_deck,
            b.kriege_mit_teilnahme,
            b.decks_gesamt,
            b.war_points_total,
        ) == erwartet, name
        geprueft += 1
    assert geprueft == len(GOLDEN)


def test_laufender_krieg_zaehlt_nur_in_die_qualitaet():
    """Der laufende Krieg fließt in Ø Punkte/Deck ein, nicht in Decks und Dabei-Quote."""
    abgeschlossen = Kriegswoche(fame=1600, decks=DECKS_PRO_KRIEG)
    ohne = bewerte(Kriegsteilnahme(wochen=[abgeschlossen], kriege_im_fenster=1))
    mit = bewerte(Kriegsteilnahme(
        wochen=[Kriegswoche(fame=800, decks=4, laufend=True), abgeschlossen],
        kriege_im_fenster=1,
    ))

    assert mit.decks_gesamt == ohne.decks_gesamt == DECKS_PRO_KRIEG
    assert mit.kriege_mit_teilnahme == ohne.kriege_mit_teilnahme == 1
    assert mit.deck_vollstaendigkeit == ohne.deck_vollstaendigkeit == 1.0
    assert mit.anwesenheits_rate == ohne.anwesenheits_rate == 1.0

    assert ohne.fame_per_deck == 100
    assert mit.fame_per_deck == 120          # (1600 + 800) / (16 + 4)
    assert mit.war_points_total == 2400      # laufender Krieg zählt hier mit
    assert mit.score > ohne.score            # allein über die Qualität


def test_qualitaet_ist_nach_oben_und_unten_begrenzt():
    def qualitaet_bei(fame_pro_deck):
        woche = Kriegswoche(fame=fame_pro_deck * DECKS_PRO_KRIEG, decks=DECKS_PRO_KRIEG)
        return bewerte(Kriegsteilnahme(wochen=[woche], kriege_im_fenster=1)).qualitaet

    assert qualitaet_bei(50) == 0.0     # unter QUALITAET_FAME_MIN
    assert qualitaet_bei(75) == 0.0     # genau auf der Untergrenze
    assert qualitaet_bei(150) == 0.5
    assert qualitaet_bei(225) == 1.0    # genau auf der Obergrenze
    assert qualitaet_bei(400) == 1.0    # darüber wird gedeckelt


def test_ohne_decks_keine_qualitaet_trotz_teilnahme():
    """Fame 0 bei gespielten Decks ist etwas anderes als gar nicht gespielt."""
    b = bewerte(Kriegsteilnahme(
        wochen=[Kriegswoche(fame=0, decks=DECKS_PRO_KRIEG)],
        kriege_im_fenster=1,
    ))
    assert b.fame_per_deck == 0
    assert b.qualitaet == 0.0
    assert b.deck_vollstaendigkeit == 1.0
    assert b.score == 80.0   # 50 Decks + 30 Anwesenheit, 0 Qualität


def test_welpenschutz_kommt_aus_der_teilnahme_nicht_aus_urlaub():
    erster_krieg = bewerte(Kriegsteilnahme(
        wochen=[Kriegswoche(fame=1600, decks=DECKS_PRO_KRIEG)],
        kriege_im_fenster=1,
    ))
    assert erster_krieg.ist_welpenschutz is True

    zweiter_krieg = bewerte(Kriegsteilnahme(
        wochen=[
            Kriegswoche(fame=1600, decks=DECKS_PRO_KRIEG),
            Kriegswoche(fame=1600, decks=DECKS_PRO_KRIEG),
        ],
        kriege_im_fenster=2,
    ))
    assert zweiter_krieg.ist_welpenschutz is False


def test_keine_kriege_keine_division_durch_null():
    b = bewerte(Kriegsteilnahme(wochen=[], kriege_im_fenster=0))
    assert b.score == 0
    assert b.fame_per_deck == 0
    assert b.max_moegliche_decks == 0
    assert b.anwesenheits_rate == 0.0
    assert b.deck_vollstaendigkeit == 0.0


def test_nur_die_letzten_vier_kriege_zaehlen_fuer_punkte_pro_deck():
    stark = Kriegswoche(fame=200 * DECKS_PRO_KRIEG, decks=DECKS_PRO_KRIEG)
    schwach = Kriegswoche(fame=100 * DECKS_PRO_KRIEG, decks=DECKS_PRO_KRIEG)
    b = bewerte(Kriegsteilnahme(
        wochen=[stark, stark, stark, stark, schwach, schwach],
        kriege_im_fenster=6,
    ))
    assert b.fame_per_deck == 200          # die beiden alten Kriege bleiben draußen
    assert b.war_points_total == 4 * stark.fame + 2 * schwach.fame


def test_kaputte_qualitaetsgrenzen_brechen_den_cron_nicht():
    """QUALITAET_FAME_MAX <= QUALITAET_FAME_MIN darf keine ZeroDivisionError geben.

    Der Cron schreibt in jedem Lauf State-Dateien. Ein Konfigurationsfehler würde
    sonst bewerte() für jeden Spieler abbrechen und damit den ganzen Lauf.
    Erwartetes Verhalten stattdessen: harte Ja/Nein-Grenze bei QUALITAET_FAME_MIN.
    """
    import importlib

    import config
    import app.bewertung as modul

    original = config.QUALITAET_FAME_MAX
    try:
        config.QUALITAET_FAME_MAX = config.QUALITAET_FAME_MIN
        importlib.reload(modul)
        assert modul.QUALITAETS_SPANNE >= 1

        unter = modul.bewerte(modul.Kriegsteilnahme(
            wochen=[modul.Kriegswoche(fame=50 * DECKS_PRO_KRIEG, decks=DECKS_PRO_KRIEG)],
            kriege_im_fenster=1,
        ))
        ueber = modul.bewerte(modul.Kriegsteilnahme(
            wochen=[modul.Kriegswoche(fame=200 * DECKS_PRO_KRIEG, decks=DECKS_PRO_KRIEG)],
            kriege_im_fenster=1,
        ))
        assert unter.qualitaet == 0.0
        assert ueber.qualitaet == 1.0
    finally:
        config.QUALITAET_FAME_MAX = original
        importlib.reload(modul)

    assert QUALITAETS_SPANNE == 150
