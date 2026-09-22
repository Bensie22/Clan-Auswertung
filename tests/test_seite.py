"""Prüft die von Master_Auswertung_GitHub.py erzeugte index.html.

Warum es diese Tests gibt: Die Seite entsteht aus einem rund 900 Zeilen langen
f-String-Template. Ein Tippfehler bricht dort nichts hörbar – die Seite wird
trotzdem erzeugt, nur eben falsch. Genau so sind in der Vergangenheit entstanden:
ein Spielername der als HTML interpretiert wurde, i18n-Markup das ein Attribut
zerlegt hat, und eine sticky Navigation die nie geklebt hat.

Bewusst NICHT geprüft werden exakte Pixel- und Prozentwerte oder einzelne
CSS-Klassennamen. Solche Tests schlagen bei jeder harmlosen Umgestaltung an,
und ein Test der ohne Grund meckert wird bald ignoriert. Geprüft wird, was teuer
ist wenn es unbemerkt kaputtgeht: Sicherheit, Datenschutz, Bewertungslogik.

Aufruf:  python -m pytest tests/ -q
"""
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

TESTPASSWORT = "Test-Passwort-fuer-die-Testsuite"

RIDS = ["zzzcurrent", "20260817", "20260810", "20260803", "20260727", "20260720", "20260713"]
ABGESCHLOSSEN = [r for r in RIDS if r != "zzzcurrent"]


def _krieg(fame, decks, im_clan=1):
    return {"fame": fame, "decks": decks, "im_clan": im_clan}


def _zeile(tag, name, rolle, kriege, spenden=100, empfangen=0):
    """Baut eine CSV-Zeile wie sie fetch_and_build_player_csv erzeugen würde."""
    zeile = {
        "player_tag": tag, "player_name": name, "player_is_current_member": True,
        "player_role": rolle, "player_donations": spenden,
        "player_donations_received": empfangen, "player_trophies": 9000,
    }
    gespielt = decks_gesamt = im_clan_anzahl = 0
    for rid in RIDS:
        k = kriege.get(rid) or _krieg(0, 0, im_clan=0)
        zeile[f"s_{rid}_fame"] = k["fame"]
        zeile[f"s_{rid}_decks_used"] = k["decks"]
        zeile[f"s_{rid}_boat_attacks"] = 0
        zeile[f"s_{rid}_in_clan"] = k["im_clan"]
        if rid != "zzzcurrent" and k["im_clan"]:
            im_clan_anzahl += 1
            decks_gesamt += k["decks"]
            if k["decks"] > 0:
                gespielt += 1
    zeile["player_contribution_count"] = gespielt
    zeile["player_participating_count"] = im_clan_anzahl
    zeile["player_total_decks_used"] = decks_gesamt
    zeile["player_total_boat_attacks"] = 0
    return zeile


@pytest.fixture(scope="module")
def seite():
    """Erzeugt einmalig eine Testseite und gibt ihr HTML zurück.

    generate_html_report schreibt player_stats.json als Nebeneffekt ins Repo.
    Die echte Datei wird deshalb gesichert und danach zurückgespielt – sonst
    landen die Testspieler in einer Zustandsdatei, die der Cron committet.
    """
    import pandas as pd

    os.environ.setdefault("SUPERCELL_API_TOKEN", "dummy")
    os.environ["ADMIN_PASSPHRASE"] = TESTPASSWORT

    zustand = os.path.join(REPO, "player_stats.json")
    sicherung = zustand + ".pytest-backup"
    vorhanden = os.path.exists(zustand)
    if vorhanden:
        shutil.copy2(zustand, sicherung)

    alter_pfad = os.getcwd()
    os.chdir(REPO)
    try:
        spec = importlib.util.spec_from_file_location(
            "master_fuer_test", os.path.join(REPO, "Master_Auswertung_GitHub.py"))
        mg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mg)

        voll = {r: _krieg(2800, 16) for r in RIDS}
        zeilen = [
            # Vorbildlich, alle Decks in allen Kriegen
            _zeile("#AAA", "Vorbild", "elder", voll),
            # Sonderzeichen + Einschleusungsversuch im Namen
            _zeile("#BBB", '>MRK< <img src=x onerror=alert(1)>', "member", voll),
            # Seit 6 Kriegen im Clan, nur einmal gespielt -> kein Welpenschutz
            _zeile("#CCC", "Dauerinaktiv", "member",
                   {"20260817": _krieg(200, 1), "20260810": _krieg(0, 0),
                    "20260803": _krieg(0, 0), "20260727": _krieg(0, 0),
                    "20260720": _krieg(0, 0), "20260713": _krieg(0, 0)},
                   spenden=0, empfangen=500),
            # Erst seit einem Krieg dabei -> Welpenschutz
            _zeile("#DDD", "Neuling", "member", {"20260817": _krieg(2400, 16)}),
            # Zwei Kriege komplett ausgelassen, obwohl im Clan
            _zeile("#EEE", "Luecke", "member",
                   {"20260817": _krieg(2800, 16), "20260810": _krieg(0, 0),
                    "20260803": _krieg(2800, 16), "20260727": _krieg(0, 0),
                    "20260720": _krieg(2800, 16), "20260713": _krieg(2800, 16)}),
        ]

        karten = [{"name": n, "icon": "data:image/gif;base64,R0lGODlhAQABAAAAACw="}
                  for n in ("Hog Rider", "Musketeer", "Cannon", "Ice Spirit",
                            "Skeletons", "Fireball", "Ice Golem", "The Log")]
        karten[0]["name"] = 'Hog "Rider" <b>'   # Kartenname mit Markup

        html, *_ = mg.generate_html_report(
            df_active=pd.DataFrame(zeilen),
            df_history=pd.DataFrame(columns=["player_name", "score", "date", "trophies"]),
            fame_spalte="s_zzzcurrent_fame",
            heute_datum="23.08.2026, 12:00 Uhr",
            header_img_src="data:image/gif;base64,R0lGODlhAQABAAAAACw=",
            radar_clans=[],
            records={"donations": {"name": "<b>Boss</b>", "val": 2174},
                     "delta": {"name": "maghrebi", "val": 80.0},
                     "trophies": {"name": "lukasl 5", "val": 14000}},
            strikes_data={"players": {"Dauerinaktiv": 0}, "last_strike_week": 0,
                          "demoted_this_week": [], "kicked_this_week": []},
            race_state_de="Clankrieg",
            raw_mahnwache=[{"name": '>MRK< <img src=x onerror=alert(1)>', "offen": 4}],
            top_decks_data={"decks": {"d1": {"wins": 12, "losses": 4, "cards": karten,
                                             "players": ["Vorbild"]}}},
            # Gegner-Decks gehoeren mit in die Fixture: Sie bauen ihre Kartenbilder
            # in einem eigenen Codepfad. Ohne sie lief der Test gegen verzerrte
            # Bilder ins Leere – dort stand der kaputte Inline-Stil noch, waehrend
            # der Clan-Deck-Pfad laengst korrigiert war.
            opponent_decks={"g1": {"cards": karten, "seen": 10, "losses": 9}},
            echte_neulinge=["Neuling"], rueckkehrer=[], warn_rueckkehrer=[],
            kicked_players={}, is_weekly_run=True,
            player_profiles={"#AAA": {"exp_level": 60, "best_trophies": 9000,
                                      "win_rate": 55,
                                      "favourite_card": 'Rascals <script>alert(1)</script>'}},
        )
        return html
    finally:
        os.chdir(alter_pfad)
        if vorhanden:
            shutil.copy2(sicherung, zustand)
            os.remove(sicherung)


@pytest.fixture(scope="module")
def zeilen(seite):
    return re.findall(r"<tr class='player-row'.*?</tr>", seite, re.S)


def _zeile_von(zeilen, name):
    for z in zeilen:
        if f'data-name="{name}"' in z:
            return z
    return ""


# ── Sicherheit: Spielernamen dürfen kein HTML werden ────────────────────────
# Clash-Royale-Namen dürfen < > & enthalten (im Clan gibt es ">MRK<").

def test_spielername_wird_escaped(seite):
    assert "onerror=alert(1)>" not in seite
    assert "&lt;img src=x onerror=alert(1)&gt;" in seite


def test_kartenname_wird_escaped(seite):
    assert "<script>alert(1)</script>" not in seite


def test_rekordname_wird_escaped(seite):
    assert "&lt;b&gt;Boss&lt;/b&gt;" in seite


def test_kein_i18n_markup_in_attributwerten(seite):
    """t() liefert <span>-Markup – in einem Attribut zerlegt das den Tag."""
    treffer = re.findall(r'\s[a-zA-Z-]+="[^"]*<span[^"]*"', seite)
    assert not treffer, f"Markup im Attribut: {treffer[:2]}"


# ── Datenschutz: keine Drittanbieter, kein Klartext im Leitungs-Bereich ─────

def test_keine_externen_ressourcen(seite):
    for host in ("fonts.googleapis.com", "fonts.gstatic.com", "hdqwalls.com"):
        assert host not in seite, f"{host} wird nachgeladen"


def test_schrift_wird_selbst_ausgeliefert(seite):
    assert "@font-face" in seite and "fonts/nunito-latin.woff2" in seite
    for datei in ("nunito-latin.woff2", "nunito-latin-ext.woff2"):
        assert os.path.exists(os.path.join(REPO, "fonts", datei)), f"fonts/{datei} fehlt"


def test_leitungsbereich_ist_verschluesselt(seite):
    treffer = re.search(r"var ADMIN_BLOB = (\{.*?\});", seite, re.S)
    assert treffer, "kein verschlüsselter Block eingebettet"
    blob = json.loads(treffer.group(1).replace("<\\/", "</"))
    assert blob["iter"] >= 200_000
    assert len(base64.b64decode(blob["salt"])) == 16
    assert len(base64.b64decode(blob["iv"])) == 12


def test_leitungsbereich_laesst_sich_entschluesseln(seite):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = json.loads(re.search(r"var ADMIN_BLOB = (\{.*?\});", seite, re.S)
                      .group(1).replace("<\\/", "</"))
    key = hashlib.pbkdf2_hmac("sha256", TESTPASSWORT.encode(),
                              base64.b64decode(blob["salt"]), blob["iter"], dklen=32)
    klar = AESGCM(key).decrypt(base64.b64decode(blob["iv"]),
                               base64.b64decode(blob["data"]), None).decode("utf-8")
    assert "chatbox_0" in klar and "Spenden auffällig" in klar


def test_kein_leitungsinhalt_im_klartext(seite):
    """Der sichtbare Text des Geheimteils darf nirgends offen in der Seite stehen."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = json.loads(re.search(r"var ADMIN_BLOB = (\{.*?\});", seite, re.S)
                      .group(1).replace("<\\/", "</"))
    key = hashlib.pbkdf2_hmac("sha256", TESTPASSWORT.encode(),
                              base64.b64decode(blob["salt"]), blob["iter"], dklen=32)
    klar = AESGCM(key).decrypt(base64.b64decode(blob["iv"]),
                               base64.b64decode(blob["data"]), None).decode("utf-8")

    def nur_text(s):
        s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
        return re.sub(r"<[^>]+>", "\n", s)

    # Der Wiki-Text und der Knopf-Titel nennen diese Begriffe bewusst – ohne Namen.
    harmlos = {"Spenden auffällig", "Notable Donations", "Chat-Hilfe", "Chat Helper",
               "Kopieren", "Copy", "Bereich der Clanleitung"}
    geheim = {z.strip() for z in nur_text(klar).splitlines()
              if len(z.strip()) >= 18 and z.strip() not in harmlos}
    oeffentlich = nur_text(seite)
    lecks = sorted(z for z in geheim if z in oeffentlich)
    assert not lecks, f"Leitungsinhalt steht im Klartext: {lecks[:3]}"


def test_ohne_passwort_kein_leitungsbereich():
    """Fehlt ADMIN_PASSPHRASE, darf der Bereich fehlen – nie unverschlüsselt drin sein."""
    import pandas as pd
    zustand = os.path.join(REPO, "player_stats.json")
    sicherung = zustand + ".pytest-backup2"
    vorhanden = os.path.exists(zustand)
    if vorhanden:
        shutil.copy2(zustand, sicherung)
    alter_pfad, altes_pw = os.getcwd(), os.environ.pop("ADMIN_PASSPHRASE", None)
    os.chdir(REPO)
    try:
        spec = importlib.util.spec_from_file_location(
            "master_ohne_pw", os.path.join(REPO, "Master_Auswertung_GitHub.py"))
        mg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mg)
        html, *_ = mg.generate_html_report(
            df_active=pd.DataFrame([_zeile("#AAA", "Vorbild", "elder",
                                           {r: _krieg(2800, 16) for r in RIDS})]),
            df_history=pd.DataFrame(columns=["player_name", "score", "date", "trophies"]),
            fame_spalte="s_zzzcurrent_fame", heute_datum="23.08.2026, 12:00 Uhr",
            header_img_src="", radar_clans=[],
            records={"donations": {"name": "-", "val": 0}, "delta": {"name": "-", "val": 0},
                     "trophies": {"name": "-", "val": 0}},
            strikes_data={"players": {}, "last_strike_week": 0,
                          "demoted_this_week": [], "kicked_this_week": []},
            race_state_de="Trainingstag", raw_mahnwache=[], top_decks_data={},
            echte_neulinge=[], rueckkehrer=[], warn_rueckkehrer=[],
            kicked_players={}, is_weekly_run=False)
        assert "var ADMIN_BLOB = null;" in html
        assert "chatbox_0" not in html and "<textarea" not in html
    finally:
        os.chdir(alter_pfad)
        if altes_pw is not None:
            os.environ["ADMIN_PASSPHRASE"] = altes_pw
        if vorhanden:
            shutil.copy2(sicherung, zustand)
            os.remove(sicherung)


def test_keine_oeffentliche_spenden_markierung(seite, zeilen):
    """📦/💤 stellen einzelne Mitglieder öffentlich bloß – gehören in den Admin-Teil."""
    assert not any("📦" in z or "💤" in z for z in zeilen)


# ── Bewertungslogik: betrifft echte Menschen ────────────────────────────────

def test_welpenschutz_gilt_fuer_echte_neulinge(zeilen):
    assert "🌱" in _zeile_von(zeilen, "Neuling")


def test_kein_welpenschutz_bei_dauerhafter_inaktivitaet(zeilen):
    """6 Kriege im Clan, einmal gespielt: früher dauerhaft geschützt – das war die Lücke."""
    assert "🌱" not in _zeile_von(zeilen, "Dauerinaktiv")


def test_verwarnung_erscheint_nicht_oeffentlich(zeilen):
    assert "❌" not in _zeile_von(zeilen, "Dauerinaktiv")


def test_ausgelassene_kriege_sind_im_trend_sichtbar(zeilen):
    """Wer im Clan war und nicht gespielt hat, bekommt einen roten Punkt."""
    trend = re.search(r"<td class='trend-cell'>([^<]*)</td>",
                      _zeile_von(zeilen, "Luecke")).group(1)
    assert trend.count("🔴") == 2, trend


def test_laufender_krieg_faelscht_den_trend_nicht(zeilen):
    """Nur abgeschlossene Kriege zählen – sonst stünde tagsüber überall Rot."""
    trend = re.search(r"<td class='trend-cell'>([^<]*)</td>",
                      _zeile_von(zeilen, "Vorbild")).group(1)
    assert trend == "🟢" * 6, trend


def test_deck_nutzung_ist_in_sich_stimmig(zeilen):
    """"Gespielt" darf nie über dem Maximum liegen, und das Maximum ist Kriege × 16.

    Klingt selbstverständlich, ist es aber nicht: Beide Zahlen stammen aus getrennten
    CSV-Spalten (player_total_decks_used und player_contribution_count). Laufen die
    auseinander, steht auf der Seite etwas Unmögliches wie "160/96" – und niemand
    kann der Auswertung dann noch trauen.
    """
    for z in zeilen:
        decks = re.search(
            r">(\d+)/(\d+)</span><br><span[^>]*><span class='i18n-de'>Decks gespielt", z)
        dabei = re.search(
            r">(\d+)/(\d+)</span><br><span[^>]*><span class=\"i18n-de\">Kriege aktiv", z)
        if not decks:
            continue
        gespielt, maximum = int(decks.group(1)), int(decks.group(2))
        name = re.search(r'data-name="([^"]*)"', z).group(1)
        assert gespielt <= maximum, f"{name}: {gespielt}/{maximum} – mehr gespielt als möglich"
        if dabei:
            kriege = int(dabei.group(1))
            assert maximum == kriege * 16, \
                f"{name}: Maximum {maximum} passt nicht zu {kriege} Kriegen × 16"


# ── Deck-Vollständigkeit: wer immer dabei ist, aber nie fertig spielt ───────

def _mg():
    spec = importlib.util.spec_from_file_location(
        "master_quote", os.path.join(REPO, "Master_Auswertung_GitHub.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _k(decks, im_clan=True):
    return {"decks": decks, "im_clan": im_clan}


def test_deck_quote_regel_braucht_alle_drei_bedingungen():
    """Die Regel ist seit 08/2026 aktiv – sie darf aber nie an einer Bedingung allein hängen.

    Quote, Mindestanzahl Kriege und Mindest-Fehlmenge müssen zusammenkommen, sonst
    trifft es Neuzugänge und Leute mit ein paar fehlenden Decks.
    """
    import config
    assert 0 < config.DECK_QUOTE_MIN < 1
    assert config.DECK_QUOTE_MIN_KRIEGE >= 3, "zu wenige Kriege = Zufallstreffer"
    assert config.DECK_QUOTE_MIN_FEHLEND >= 10, "zu kleine Fehlmenge = Bagatellen"
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    # Quote weit unter der Grenze, aber nur zwei Kriege -> darf NICHT greifen
    assert m.bewerte_deck_quote([_k(0, False)] * 8 + [_k(4), _k(4)])["auffaellig"] is False


def test_deck_quote_erkennt_dauerhaft_unvollstaendige():
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    q = m.bewerte_deck_quote([_k(12)] * 10)      # immer dabei, nie fertig
    assert q["kriege"] == 10 and q["fehlend"] == 40
    assert q["auffaellig"] is True


def test_beitrittskrieg_zaehlt_nicht_fuer_die_quote():
    """Wer mitten in der Kriegswoche beitritt, konnte keine 16 Decks spielen."""
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    # 6 Kriege nicht im Clan, dann Beitritt mit nur 8 möglichen Decks, dann voll
    q = m.bewerte_deck_quote([_k(0, False)] * 6 + [_k(8)] + [_k(16)] * 3)
    assert q["kriege"] == 3, "Beitrittskrieg darf nicht mitzählen"
    assert q["quote"] == 1.0 and q["auffaellig"] is False


def test_rueckkehrer_wird_nicht_fuer_die_pause_bestraft():
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    q = m.bewerte_deck_quote([_k(16)] * 3 + [_k(0, False)] * 3 + [_k(7)] + [_k(16)] * 3)
    assert q["quote"] == 1.0 and q["auffaellig"] is False


def test_wenige_kriege_schuetzen_vor_der_regel():
    """Eine Quote aus zwei Kriegen ist Zufall, keine Aussage."""
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    q = m.bewerte_deck_quote([_k(0, False)] * 7 + [_k(10), _k(9), _k(10)])
    assert q["kriege"] < 4 and q["auffaellig"] is False


def test_kleine_fehlmenge_loest_nicht_aus():
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    q = m.bewerte_deck_quote([_k(14), _k(15), _k(15), _k(14), _k(15)])
    assert q["fehlend"] < 15 and q["auffaellig"] is False


def test_langzeitmitglied_verliert_keinen_krieg(zeilen):
    """Der älteste Krieg im Fenster zählt, wenn der Spieler dort schon im Clan war."""
    m = _mg()
    m.DECK_QUOTE_REGEL_AKTIV = True
    q = m.bewerte_deck_quote([_k(16)] * 10)
    assert q["kriege"] == 10, "sonst verlieren Veteranen grundlos einen Krieg"


def test_verwarnungen_haengen_am_spieler_tag():
    """Namen sind änderbar – über den Namen wäre eine Verwarnung umgehbar."""
    spec = importlib.util.spec_from_file_location(
        "master_migration", os.path.join(REPO, "Master_Auswertung_GitHub.py"))
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    umgeschluesselt = mg.migrate_strikes_to_tags(
        {"elazeto": 1, "Ehemaliger": 2, "#AAA": 3}, {"elazeto": "#ELA1"})
    assert umgeschluesselt == {"#AAA": 3, "#ELA1": 1, "Ehemaliger": 2}
    # Tag-Eintrag gewinnt, damit in der Übergangsphase nichts doppelt zählt
    assert mg.migrate_strikes_to_tags({"#ELA1": 5, "elazeto": 1},
                                      {"elazeto": "#ELA1"}) == {"#ELA1": 5}


# ── Spieler-Suche ───────────────────────────────────────────────────────────

def test_jede_zeile_traegt_ihren_namen(zeilen):
    """Die Suche liest data-name; über den Zelltext würde sie Tooltips mitfinden."""
    assert zeilen and all("data-name=" in z for z in zeilen)


def test_suchfeld_steht_vor_den_tabellen(seite):
    pos_feld = seite.find('id="spieler-suche-feld"')
    pos_tabelle = seite.find("<div class='tier-section' data-tier=")
    assert pos_feld > 0 and pos_tabelle > pos_feld


def test_alle_leistungsstufen_sind_waehlbar(seite):
    """Auch unbesetzte Stufen bleiben sichtbar – sonst wirken sie abgeschafft."""
    for stufe in ("alle", "sehr-stark", "solide-basis", "mehr-drin", "ausbaufaehig"):
        assert f'data-tier="{stufe}"' in seite
    assert not re.search(r"\.stufe-btn\.leer \{\{?[^}]*display:\s*none", seite)


def test_stufe_mehr_drin_existiert_weiterhin(seite):
    assert "Mehr drin" in seite and "Underperforming" in seite


def test_name_und_stufe_schliessen_sich_aus(seite):
    """Beides gleichzeitig ergäbe 0 Treffer ohne erkennbaren Grund."""
    rumpf = seite[seite.find("function stufeSetzen"):seite.find("function stufeZuruecksetzen")]
    assert 'feld.value = ""' in rumpf
    assert "function stufeZuruecksetzen" in seite


# ── Layout-Fallen, die schon einmal zugeschlagen haben ──────────────────────

def test_body_ist_kein_scroll_container(seite):
    """overflow-x auf <body> macht jedes position:sticky darin wirkungslos."""
    assert not re.search(r"\bbody \{[^}]*overflow-x", seite)
    assert re.search(r"\bhtml \{[^}]*overflow-x:\s*hidden", seite)


def test_tabwechsel_springt_ohne_animation(seite):
    """Tabwechsel muss hart nach oben springen, nicht smooth.

    Gemessen: behavior:'smooth' wird je nach Browser und Systemeinstellung
    ignoriert – window.scrollTo tut dann gar nichts. Die Seite bleibt stehen wo
    sie war, und die Ueberschrift des neuen Tabs liegt hinter der sticky
    Tab-Leiste. Genau so ist die Top-Decks-Ansicht aufgefallen.

    Der scrollIntoView im Akkordeon ist bewusst nicht mitgemeint: Dort hat der
    Nutzer das Element gerade selbst angeklickt, es ist also ohnehin sichtbar.
    """
    for name in ("openTab", "openTabByName"):
        treffer = re.search(rf"function {name}\(.*?\n            \}}", seite, re.S)
        assert treffer, f"{name} nicht gefunden"
        code = re.sub(r"//[^\n]*", "", treffer.group(0))   # Kommentare raus, sonst
        assert "behavior" not in code, f"{name} scrollt noch animiert"
        assert re.search(r"window\.scrollTo\(0,\s*0\)", code), \
            f"{name} springt nicht an den Seitenanfang"


# ── Top-Decks: Siegquote ohne Stichprobe ist keine Aussage ─────────────────
#
# Stand 22.09.2026 standen 93 von 100 gespeicherten Decks auf 100 %, 38 davon
# aus einem einzigen Spiel. Ursache war das Kuerzen der Datei nach Siegquote:
# Decks mit Niederlagen flogen zuerst raus, uebrig blieb eine Gewinnerauswahl.

def _deck_karten(variante=1):
    """Acht Karten mit eindeutigen Namen – build_deck_sections dedupliziert danach."""
    return [{"name": f"Karte {variante}-{i}", "icon": "data:image/gif;base64,R0lGODlhAQABAAAAACw="}
            for i in range(8)]


def test_guete_bevorzugt_die_belastbare_bilanz():
    """6:0 darf nicht vor 14:1 stehen – der Kern des Problems."""
    m = _mg()
    assert m.get_deck_guete(14, 15) > m.get_deck_guete(6, 6)
    assert m.get_deck_guete(15, 15) > m.get_deck_guete(14, 15)
    assert m.get_deck_guete(5, 5) > m.get_deck_guete(1, 1)
    assert m.get_deck_guete(0, 0) == 0.0


def test_decks_werden_nach_spielanzahl_gekuerzt_nicht_nach_quote():
    """Sonst bleibt eine Gewinnerauswahl uebrig und die Quote sagt nichts mehr."""
    with open(os.path.join(REPO, "Master_Auswertung_GitHub.py"), encoding="utf-8") as f:
        code = f.read()
    block = code[code.index("--- DECK CLEANUP"):]
    block = block[:block.index("top_decks_data[")]
    schluessel = re.search(r"key=lambda k: \((.*?)\)\n", block, re.S).group(1)
    assert schluessel.strip().startswith('decks[k]["wins"] + decks[k]["losses"]'), (
        f"gekuerzt wird nach '{schluessel.strip()}' – die Spielanzahl muss zuerst kommen"
    )


def test_meta_decks_sortieren_nach_guete():
    """Ein Zufallstreffer darf nicht oben auf der Seite landen."""
    m = _mg()
    daten = {"decks": {
        "zufall":   {"cards": _deck_karten(1), "wins": 6,  "losses": 0, "players": ["A"], "tags": ["#A"]},
        "bewaehrt": {"cards": _deck_karten(2), "wins": 14, "losses": 1, "players": ["B"], "tags": ["#B"]},
    }}
    meta = [s for s in m.build_deck_sections(daten) if "Meta" in s["title"]][0]["decks"]
    assert meta, "keine Meta-Decks gebildet"
    assert meta[0]["wins"] == 14, "der 6:0-Zufallstreffer steht vorn"


def test_winrate_nennt_die_stichprobe(seite):
    """100 % ohne Spielanzahl ist die eigentliche Irrefuehrung."""
    # Das Badge enthaelt i18n-Spans – ohne sie zu entfernen stuende im Text
    # "aus from 16 Spielen games". Also erst die englische Fassung raus, dann
    # alle Tags, dann auf dem reinen deutschen Text pruefen.
    nur_de = re.sub(r"<span class=['\"]i18n-en['\"]>.*?</span>", "", seite, flags=re.S)
    nur_text = re.sub(r"<[^>]+>", " ", nur_de)
    assert re.search(r"\d+%\s+aus\s+\d+\s+Spielen", nur_text), \
        "kein Winrate-Badge nennt die Spielanzahl"
    assert not re.search(r"\d+%\s+Win\b", nur_text), \
        "altes Badge '100% Win' ohne Stichprobe ist noch da"


# ── Filter "Offene Decks" (oeffentlich, Entscheidung vom 22.09.2026) ───────

def test_offene_decks_ist_waehlbar(seite):
    assert 'data-tier="offene-decks"' in seite, "Filterknopf fehlt"
    assert "Offene Decks" in seite and "Unplayed decks" in seite, "nicht zweisprachig"


def test_jede_zeile_sagt_ob_decks_offen_sind(seite, zeilen):
    """Ohne data-offen an JEDER Zeile filtert der Knopf ins Leere."""
    alle = re.findall(r"<tr class='player-row'[^>]*>", seite)
    assert alle, "keine Spielerzeilen"
    ohne = [z for z in alle if "data-offen=" not in z]
    assert not ohne, f"{len(ohne)} Zeilen ohne data-offen"
    assert any('data-offen="1"' in z for z in alle), "niemand als auffaellig markiert"
    assert any('data-offen="0"' in z for z in alle), "alle markiert – das waere unplausibel"


def test_urlauber_gilt_nicht_als_auffaellig():
    """Angemeldeter Urlaub nimmt aus beiden Clan-Werten heraus – dann auch hier."""
    m = _mg()
    kriege = [_k(2) for _ in range(6)]             # dauerhaft unvollstaendig
    ohne_urlaub = m.bewerte_deck_quote(kriege)
    assert ohne_urlaub["auffaellig"], "Testfall trifft die Regel gar nicht"
    # Die Ausnahme greift im Seitenbau, nicht in bewerte_deck_quote selbst:
    quelle = open(os.path.join(REPO, "Master_Auswertung_GitHub.py"), encoding="utf-8").read()
    assert re.search(r"if is_urlaub:\s*\n\s*deck_quote = dict\(deck_quote, auffaellig=False\)", quelle), \
        "Urlauber werden nicht von der Auffaelligkeit ausgenommen"


def test_offene_decks_filtert_ueber_die_stufen_hinweg(seite):
    """Die Auffaelligkeit ist eine Zeilen-Eigenschaft, kein eigener Tier-Block.

    Ein eigener Abschnitt wuerde die Score-Reihenfolge zerreissen – auch ein
    Spieler aus "Sehr stark" kann Decks liegen lassen.
    """
    assert 'data-tier="offene-decks"' not in re.sub(
        r"<button[^>]*>", "", seite), "es gibt einen Tier-Block statt eines Zeilenfilters"
    assert re.search(r'aktuelleStufe === "offene-decks"', seite), \
        "die Filterlogik kennt den Knopf nicht"
    assert re.search(r'player-row\[data-offen="1"\]', seite), \
        "der Zaehler am Knopf fehlt"


def test_spaltenbreiten_ergeben_hundert_prozent(seite):
    breiten = [int(b) for b in re.findall(r"th:nth-child\(\d\) \{ width: (\d+)%", seite)]
    assert sum(breiten) == 100, f"{sum(breiten)}% statt 100%"


def test_kartenbilder_werden_nicht_verzerrt(seite):
    """Breite per CSS ohne Hoehe laesst die Attribut-Hoehe stehen.

    Die Kartenbilder tragen width='300' height='360' als Attribut. Setzt das CSS
    nur die Breite, bleibt height=360px wirksam und die Karte wird gequetscht –
    gemessen am 22.09.2026: 64x360 statt 64x77, Verhaeltnis 0,18 statt 0,83.
    """
    # Beide Bildpfade muessen in der Fixture vorkommen – Clan-Decks und
    # Gegner-Decks werden an verschiedenen Stellen gebaut. Genau daran ist die
    # erste Fassung dieses Tests vorbeigelaufen.
    assert "Meta-Decks" in seite, "Fixture rendert keine Clan-Decks"
    assert "Gegner-Deck" in seite, "Fixture rendert keine Gegner-Decks"

    regel = re.search(r"\.deck-images img \{([^}]*)\}", seite)
    assert regel, "keine eigene Regel fuer .deck-images img"
    assert "height: auto" in regel.group(1), "ohne height:auto gewinnt das Attribut"
    assert "aspect-ratio" in regel.group(1), \
        "ohne aspect-ratio faellt das Deck zusammen, wenn die Bilder blockiert sind"

    # Und inline darf keine Breite ohne Hoehe mehr auftauchen.
    for bild in re.findall(r"<img [^>]*>", seite):
        stil = re.search(r"style=['\"]([^'\"]*)['\"]", bild)
        if stil and "width" in stil.group(1):
            assert "height" in stil.group(1), f"Breite ohne Hoehe inline: {bild[:90]}"


def test_kartenbilder_haben_alt_und_laden_verzoegert(seite):
    bilder = re.findall(r"<img [^>]*>", seite)
    assert bilder, "keine Kartenbilder gerendert"
    assert all(re.search(r'alt="[^"]+"', b) for b in bilder)
    assert all("loading='lazy'" in b for b in bilder)


def test_keine_deutschen_reste_in_der_englischen_ansicht(seite):
    ohne_deutsch = re.sub(r"<span class=['\"]i18n-de['\"]>.*?</span>", "", seite, flags=re.S)
    reste = [m for m in ("Gespendet:", "Lieblingskarte", "Kriegssiege", "Boot-Angriffe",
                         "Welpenschutz aktiv", " Uhr") if m in ohne_deutsch]
    assert not reste, f"deutsche Reste in der EN-Ansicht: {reste}"


# ── Karenzzeit nach einer Regeländerung ─────────────────────────────────────

def test_karenzzeit_erkennt_zeitraum_korrekt():
    """Vor und am Stichtag aktiv, danach nicht mehr – sie läuft von selbst ab."""
    from datetime import date
    m = _mg()
    m.STRIKES_AUSGESETZT_BIS = "2026-10-20"
    assert m.karenzzeit_aktiv(date(2026, 10, 1))[0] is True
    assert m.karenzzeit_aktiv(date(2026, 10, 20))[0] is True, "Stichtag zählt noch dazu"
    assert m.karenzzeit_aktiv(date(2026, 10, 21))[0] is False
    assert m.karenzzeit_aktiv(date(2026, 10, 1))[1] == "20.10.2026"


def test_karenzzeit_ohne_datum_ist_aus():
    m = _mg()
    m.STRIKES_AUSGESETZT_BIS = None
    assert m.karenzzeit_aktiv()[0] is False


def test_karenzzeit_bei_unsinnigem_datum_ist_aus():
    """Ein Tippfehler darf nicht stillschweigend alle Maßnahmen abschalten."""
    m = _mg()
    m.STRIKES_AUSGESETZT_BIS = "20.10.2026"   # falsches Format
    assert m.karenzzeit_aktiv()[0] is False


def _lauf_mit_karenz(karenz_bis, is_weekly=True):
    """Erzeugt einen Wochenlauf mit einem Spieler, der klar unter der Grenze liegt."""
    import pandas as pd
    import shutil
    zustand = os.path.join(REPO, "player_stats.json")
    sicherung = zustand + ".pytest-karenz"
    vorhanden = os.path.exists(zustand)
    if vorhanden:
        shutil.copy2(zustand, sicherung)
    alter_pfad = os.getcwd()
    os.chdir(REPO)
    try:
        m = _mg()
        m.STRIKES_AUSGESETZT_BIS = karenz_bis
        # 6 Kriege im Clan, nur einer gespielt -> Score weit unter 50
        zeile = _zeile("#ZZZ", "Aussetzer", "elder",
                       {"20260817": _krieg(200, 1), "20260810": _krieg(0, 0),
                        "20260803": _krieg(0, 0), "20260727": _krieg(0, 0),
                        "20260720": _krieg(0, 0), "20260713": _krieg(0, 0)})
        strikes = {"players": {}, "last_strike_week": 0,
                   "demoted_this_week": ["AlterEintrag"], "kicked_this_week": []}
        html, _, _, _, strikes_nachher, gekickt = m.generate_html_report(
            df_active=pd.DataFrame([zeile]),
            df_history=pd.DataFrame(columns=["player_name", "score", "date", "trophies"]),
            fame_spalte="s_zzzcurrent_fame", heute_datum="20.10.2026, 12:00 Uhr",
            header_img_src="", radar_clans=[],
            records={"donations": {"name": "-", "val": 0}, "delta": {"name": "-", "val": 0},
                     "trophies": {"name": "-", "val": 0}},
            strikes_data=strikes, race_state_de="Trainingstag", raw_mahnwache=[],
            top_decks_data={}, echte_neulinge=[], rueckkehrer=[], warn_rueckkehrer=[],
            kicked_players={}, is_weekly_run=is_weekly)
        return html, strikes_nachher, gekickt
    finally:
        os.chdir(alter_pfad)
        if vorhanden:
            shutil.copy2(sicherung, zustand)
            os.remove(sicherung)


def test_karenzzeit_verhindert_jede_massnahme():
    """Kernzusage: in der Karenzzeit keine Verwarnung, keine Degradierung, kein Kick."""
    html, strikes, gekickt = _lauf_mit_karenz("2099-12-31")
    assert strikes["demoted_this_week"] == [], "niemand darf degradiert werden"
    assert strikes["kicked_this_week"] == [], "niemand darf entfernt werden"
    assert not strikes["players"], "es darf auch keine Verwarnung gesammelt werden"


def test_wochenwechsel_wird_auch_in_der_karenzzeit_gebucht():
    """Sonst zeigte der Konsequenzen-Block die Namen der Vorwoche als 'diese Woche'."""
    _, strikes, _ = _lauf_mit_karenz("2099-12-31")
    assert "AlterEintrag" not in strikes["demoted_this_week"]
    assert strikes["last_strike_week"] != 0, "Woche muss weitergezählt werden"


def test_ohne_karenzzeit_greift_die_massnahme_wieder():
    """Gegenprobe – die Schonfrist darf die Regel nicht dauerhaft aushebeln."""
    _, strikes, _ = _lauf_mit_karenz("2020-01-01")   # längst abgelaufen
    assert strikes["demoted_this_week"] == ["Aussetzer"]


def test_karenzzeit_wird_auf_der_seite_angekuendigt():
    html, _, _ = _lauf_mit_karenz("2099-12-31")
    assert "Schonfrist bis" in html and "31.12.2099" in html
    assert "keine Verwarnungen" in html


# ---------------------------------------------------------------------------
# Wochenlauf: Wird RUN_MODE=weekly ueberhaupt jemals gesetzt?
#
# Warum es diese drei Tests gibt: Genau das war von April bis September 2026
# nicht der Fall. Der einzige Workflow hatte `RUN_MODE: radar` fest verdrahtet
# und keinen zweiten Ausloeser, also blieb `is_weekly_run` dauerhaft False.
# Folge: keine Verwarnung, keine Degradierung, kein Kick, kein Eintrag in
# score_history.csv und keine Wochenmail – fuenf Monate lang, ohne eine einzige
# Fehlermeldung. Die gesamte Bewertungslogik lief ins Leere, und von aussen war
# das nicht zu sehen.
#
# Bewusst als Textpruefung statt ueber pyyaml: Die Testsuite soll ohne
# zusaetzliche Abhaengigkeit laufen, und geprueft wird ohnehin die Anwesenheit
# bestimmter Werte, nicht die YAML-Struktur.
# ---------------------------------------------------------------------------
WORKFLOW = os.path.join(REPO, ".github", "workflows", "main.yml")


def _workflow_text():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


def test_wochenlauf_ist_ueberhaupt_erreichbar():
    """RUN_MODE darf nicht auf einen einzigen Wert festgenagelt sein."""
    text = _workflow_text()
    assert "schedule:" in text, "ohne schedule-Block laeuft der Wochenlauf nie automatisch"
    assert "weekly" in text, "RUN_MODE=weekly kommt im Workflow gar nicht vor"
    assert not re.search(r"^\s*RUN_MODE:\s*radar\s*$", text, re.M), (
        "RUN_MODE ist fest auf radar verdrahtet – genau der Fehler von 04-09/2026"
    )


def test_zehn_minuten_lauf_bleibt_radar():
    """Gegenprobe: cron-job.org schickt keinen Input, da muss radar herauskommen."""
    text = _workflow_text()
    assert "default: radar" in text, "ohne Default verliert der 10-Minuten-Lauf seinen Modus"
    assert "'radar'" in text, "der Ausdruck braucht radar als letzten Rueckfallwert"


def test_wochenlauf_startet_erst_nach_dem_warlog_refresh():
    """Montags, aber nicht zu frueh.

    Zwei harte Grenzen liegen davor: Das Flussrennen endet um 10:00 UTC
    (is_clan_war_period), und prefetch_warlog.py frischt den Warlog-Cache erst
    ab Montag 12:00 Europe/Berlin auf (= 11:00 UTC in der Winterzeit). Ein Lauf
    davor kennt den gerade beendeten Krieg noch nicht und wuerde auf veralteten
    Daten bewerten – der Fehler waere still, die Zahlen einfach falsch.
    """
    treffer = re.findall(r"-\s*cron:\s*['\"]([^'\"]+)['\"]", _workflow_text())
    assert treffer, "kein cron-Eintrag gefunden"
    for ausdruck in treffer:
        minute, stunde, _tag, _monat, wochentag = ausdruck.split()
        assert wochentag == "1", f"Wochenlauf soll montags starten, steht aber auf {wochentag}"
        assert int(stunde) >= 12, f"{ausdruck} liegt vor dem Warlog-Refresh"
        assert minute.isdigit(), f"{ausdruck} laeuft mehrmals pro Stunde"
