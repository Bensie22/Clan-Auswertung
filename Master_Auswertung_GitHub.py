import os
import glob
import heapq
import shutil
import requests
import csv
import base64
import json
import sys
import time
import traceback
import html
import copy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Tuple
from pathlib import Path
import pandas as pd
from email.message import EmailMessage
import smtplib

# === 1. Konfiguration & Pfade ===

from config import (
    STRIKE_THRESHOLD, DROPPER_THRESHOLD, MIN_PARTICIPATION,
    BADGE_STARK_SCORE, BADGE_STARK_FAME,
    BADGE_STABIL_SCORE, BADGE_STABIL_FAME,
    TIER_SEHR_STARK, TIER_SOLIDE,
    CLAN_RELIABLE_GREEN, CLAN_RELIABLE_YELLOW,
)

APP_CONFIG = {
    "STRIKE_THRESHOLD":    STRIKE_THRESHOLD,
    "DROPPER_THRESHOLD":   DROPPER_THRESHOLD,
    "MIN_PARTICIPATION":   MIN_PARTICIPATION,
    "BADGE_STARK_SCORE":   BADGE_STARK_SCORE,
    "BADGE_STARK_FAME":    BADGE_STARK_FAME,
    "BADGE_STABIL_SCORE":  BADGE_STABIL_SCORE,
    "BADGE_STABIL_FAME":   BADGE_STABIL_FAME,
    "TIER_SEHR_STARK":     TIER_SEHR_STARK,
    "TIER_SOLIDE":         TIER_SOLIDE,
    "CLAN_RELIABLE_GREEN": CLAN_RELIABLE_GREEN,
    "CLAN_RELIABLE_YELLOW":CLAN_RELIABLE_YELLOW,
}

CHAT_COLORS = ["#38bdf8", "#a855f7", "#ef4444", "#f97316", "#10b981", "#fbbf24", "#6366f1", "#ec4899"]
MAHNWACHE_COLORS = ["#7dd3fc", "#fdba74"]

JOIN_EVENT_TTL_HOURS = 24

DECK_LOOKBACK_DAYS = 30
DECK_META_MIN_MATCHES = 5
DECK_SOLID_MIN_MATCHES = 4
DECK_BEGINNER_MIN_MATCHES = 3

# API Settings (Token & E-Mails kommen sicher aus den Secrets!)
API_TOKEN = os.environ.get("SUPERCELL_API_TOKEN")
CLAN_TAG = "%23Y9YQC8UG"
CLAN_NAME = "HAMBURG"
CLAN_URL = "clan-hamburg.de"
BASE_URL = "https://proxy.royaleapi.dev/v1"

# Cloud-taugliche Pfade (relativ zur Skript-Datei)
BASE_DIR = Path(__file__).parent.resolve()
upload_folder = BASE_DIR / "uploads"
archiv_folder = upload_folder / "archiv"
output_folder = BASE_DIR / "output"
score_history_path = BASE_DIR / "score_history.csv"
records_path = BASE_DIR / "records.json"
strikes_path = BASE_DIR / "strikes.json"
top_decks_path = BASE_DIR / "top_decks.json"
player_war_decks_path = BASE_DIR / "player_war_decks.json"
war_radar_cache_path  = BASE_DIR / "war_radar_cache.json"
donations_memory_path = BASE_DIR / "donations_memory.json"
member_memory_path = BASE_DIR / "member_memory.json"
urlaub_path = BASE_DIR / "urlaub.txt"
kicked_players_path = BASE_DIR / "kicked_players.json"
HEADER_IMAGE_PATH = BASE_DIR / "clash_pix.jpg"
website_opt_out_path = BASE_DIR / "website_opt_out.json"


def load_war_radar_cache() -> dict:
    """Lädt den gespeicherten periodPoints-Stand pro Clan (für Delta-Berechnung)."""
    if war_radar_cache_path.exists():
        try:
            with open(war_radar_cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_war_radar_cache(cache: dict):
    """Speichert den aktuellen periodPoints-Stand pro Clan."""
    try:
        with open(war_radar_cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ war_radar_cache konnte nicht gespeichert werden: {e}")


def safe_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def t(de: str, en: str) -> str:
    """i18n dual-render helper. Emits both languages; CSS hides inactive one based on <html lang>."""
    return f'<span class="i18n-de">{de}</span><span class="i18n-en">{en}</span>'


def normalize_player_tag(tag: str) -> str:
    return str(tag or "").strip().upper()


def normalize_player_name(name: str) -> str:
    return str(name or "").strip().casefold()


def load_website_opt_outs() -> tuple[dict, set, set]:
    default_registry = {"players": []}
    if not website_opt_out_path.exists():
        return default_registry, set(), set()

    try:
        with open(website_opt_out_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except Exception as e:
        print(f"⚠️ Warnung: website_opt_out.json fehlerhaft, ignoriere Opt-Outs. ({e})")
        return default_registry, set(), set()

    if not isinstance(registry, dict) or not isinstance(registry.get("players", []), list):
        return default_registry, set(), set()

    active_tags = set()
    active_names = set()
    for entry in registry.get("players", []):
        if not isinstance(entry, dict):
            continue
        if not entry.get("active", True):
            continue
        if not entry.get("reviewed", False):
            continue

        tag = normalize_player_tag(entry.get("tag", ""))
        name = normalize_player_name(entry.get("name", ""))
        if tag:
            active_tags.add(tag)
        if name:
            active_names.add(name)

    return registry, active_tags, active_names


def is_player_opted_out(tag: str = "", name: str = "", opted_out_tags: set | None = None, opted_out_names: set | None = None) -> bool:
    opted_out_tags = opted_out_tags or set()
    opted_out_names = opted_out_names or set()
    return normalize_player_tag(tag) in opted_out_tags or normalize_player_name(name) in opted_out_names


def sanitize_top_decks_for_website(top_decks_data: dict, opted_out_tags: set, opted_out_names: set) -> dict:
    sanitized = copy.deepcopy(top_decks_data or {})
    decks = sanitized.get("decks", {})

    for deck_key in list(decks.keys()):
        deck_data = decks.get(deck_key, {})
        recent_matches = deck_data.get("recent_matches", [])
        filtered_matches = [
            match for match in recent_matches
            if not is_player_opted_out(match.get("tag", ""), match.get("player", ""), opted_out_tags, opted_out_names)
        ]

        deck_data["recent_matches"] = filtered_matches
        deck_data["wins"] = sum(1 for match in filtered_matches if match.get("result") == "win")
        deck_data["losses"] = sum(1 for match in filtered_matches if match.get("result") == "loss")

        visible_players = []
        for player_name in deck_data.get("players", []):
            if not is_player_opted_out(name=player_name, opted_out_tags=opted_out_tags, opted_out_names=opted_out_names):
                if player_name not in visible_players:
                    visible_players.append(player_name)
        deck_data["players"] = visible_players

        visible_tags = []
        for tag in deck_data.get("tags", []):
            if not is_player_opted_out(tag=tag, opted_out_tags=opted_out_tags, opted_out_names=opted_out_names):
                if tag not in visible_tags:
                    visible_tags.append(tag)
        deck_data["tags"] = visible_tags

        if deck_data["wins"] + deck_data["losses"] <= 0:
            del decks[deck_key]

    return sanitized


def build_legal_pages() -> Tuple[str, str]:
    site_name = safe_env("IMPRESSUM_SITE_NAME", CLAN_NAME)
    owner_name = safe_env("IMPRESSUM_OWNER_NAME")
    street = safe_env("IMPRESSUM_STREET")
    city = safe_env("IMPRESSUM_CITY")
    legal_email = safe_env("IMPRESSUM_EMAIL", safe_env("EMAIL_SENDER"))
    responsible_name = safe_env("IMPRESSUM_RESPONSIBLE_NAME", owner_name)

    missing_fields = [
        label for label, value in [
            ("Name der Website", site_name),
            ("Hauptverantwortliche Person", owner_name),
            ("Straße und Hausnummer", street),
            ("PLZ und Ort", city),
            ("E-Mail-Adresse", legal_email),
            ("Verantwortlich nach § 18 Abs. 2 MStV", responsible_name),
        ] if not value
    ]

    setup_notice = ""
    if missing_fields:
        setup_notice = (
            "<div class='legal-warning'>"
            "<b>Hinweis:</b> Das Impressum ist noch nicht vollständig konfiguriert. "
            "Bitte hinterlege diese Umgebungsvariablen bzw. GitHub-Secrets: "
            f"{html.escape(', '.join(missing_fields))}."
            "</div>"
        )

    impressum_html = f"""
        <div class="legal-page">
            {setup_notice}
            <h2>🧾 {t('Impressum', 'Imprint')}</h2>
            <p><b>{t('Angaben gemäß § 5 DDG', 'Information pursuant to § 5 DDG (German Digital Services Act)')}</b></p>
            <div class="legal-section">
                <p><b>{t('Clan Hamburg (nicht eingetragene Gemeinschaft)', 'Clan Hamburg (unregistered community)')}</b></p>
                <p><b>{t('Vertreten durch:', 'Represented by:')}</b></p>
                <p>{html.escape(owner_name)}</p>
                <p>{html.escape(street)}</p>
                <p>{html.escape(city)}</p>
            </div>
            <div class="legal-section">
                <h3>{t('Kontakt', 'Contact')}</h3>
                <p><b>{t('E-Mail:', 'Email:')}</b> <a href='mailto:{html.escape(legal_email)}'>{html.escape(legal_email)}</a></p>
            </div>
            <div class="legal-section">
                <h3>{t('Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV', 'Responsible for content according to § 18 (2) MStV')}</h3>
                <p>{html.escape(responsible_name)}</p>
                <p>{t('(Anschrift wie oben)', '(Address as above)')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('Hinweis gemäß § 36 VSBG', 'Notice pursuant to § 36 VSBG')}</h3>
                <p>{t('Wir sind nicht bereit und nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.', 'We are neither willing nor obligated to take part in dispute resolution procedures before a consumer arbitration board.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('Haftung für Links', 'Liability for links')}</h3>
                <p>{t('Diese Website enthält Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben. Für diese fremden Inhalte übernehmen wir keine Gewähr. Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich.', 'This website contains links to external third-party websites whose content we cannot influence. We accept no responsibility for this external content. The respective provider or operator of the linked pages is always responsible for the content of those pages.')}</p>
            </div>
        </div>
    """

    datenschutz_html = f"""
        <div class="legal-page">
            <h2>🧾 {t('Datenschutzerklärung', 'Privacy Policy')}</h2>
            <div class="legal-section">
                <h3>{t('1. Verantwortliche Stelle', '1. Controller')}</h3>
                <p>{t('Die verantwortliche Stelle für die Datenverarbeitung auf dieser Website ist im Impressum dieser Website angegeben.', 'The controller for data processing on this website is named in the imprint of this website.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('2. Welche Daten verarbeitet werden', '2. What data is processed')}</h3>
                <p>{t('Auf dieser Website werden spielbezogene Daten dargestellt, insbesondere Ingame-Namen, Rollen, Trophäen, Spendenwerte sowie Kriegs- und Aktivitätsstatistiken.', 'This website displays game-related data, in particular in-game names, roles, trophies, donation values as well as war and activity statistics.')}</p>
                <p>{t('Diese Daten stammen aus öffentlich zugänglichen Schnittstellen (APIs) des Spiels Clash Royale sowie von Drittanbietern (z. B. RoyaleAPI).', 'This data comes from publicly accessible interfaces (APIs) of the game Clash Royale and from third parties (e.g. RoyaleAPI).')}</p>
                <p>{t('Die dargestellten Daten beziehen sich ausschließlich auf öffentlich verfügbare Spielinformationen und lassen in der Regel keinen direkten Rückschluss auf reale Personen zu.', 'The displayed data refers exclusively to publicly available game information and as a rule does not allow direct inferences about real persons.')}</p>
                <p>{t('Beim Aufruf der Website werden zudem technisch notwendige Verbindungsdaten verarbeitet. Dazu gehören insbesondere die IP-Adresse, Datum und Uhrzeit des Zugriffs sowie Informationen zum verwendeten Browser und Endgerät. Diese Daten fallen im Rahmen des Hostings automatisch an.', 'When the website is accessed, technically necessary connection data is also processed. This includes the IP address, date and time of access, and information about the browser and device used. This data is collected automatically as part of hosting.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('3. Zweck der Verarbeitung', '3. Purpose of processing')}</h3>
                <p>{t('Die Verarbeitung der Daten erfolgt zu folgenden Zwecken:', 'Data is processed for the following purposes:')}</p>
                <ul>
                    <li>{t('Darstellung und Analyse der Clan-, Kriegs- und Aktivitätsdaten', 'Display and analysis of clan, war and activity data')}</li>
                    <li>{t('Bereitstellung der Website', 'Provision of the website')}</li>
                    <li>{t('Gewährleistung eines sicheren und stabilen Betriebs', 'Ensuring secure and stable operation')}</li>
                </ul>
            </div>
            <div class="legal-section">
                <h3>{t('4. Rechtsgrundlage der Verarbeitung', '4. Legal basis for processing')}</h3>
                <p>{t('Die Verarbeitung erfolgt auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse).', 'Processing is carried out on the basis of Art. 6 (1) (f) GDPR (legitimate interest).')}</p>
                <p>{t('Das berechtigte Interesse liegt in der Bereitstellung von Clan-Statistiken, der Analyse von Spielaktivitäten sowie der Darstellung von Informationen für die Community.', 'The legitimate interest lies in providing clan statistics, analyzing game activities and displaying information for the community.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('5. Hosting', '5. Hosting')}</h3>
                <p>{t('Diese Website wird über GitHub Pages bereitgestellt.', 'This website is provided via GitHub Pages.')}</p>
                <p>{t('Dabei werden technisch notwendige Daten (z. B. IP-Adresse) verarbeitet, um die Website auszuliefern.', 'Technically necessary data (e.g. IP address) is processed to deliver the website.')}</p>
                <p>{t('Weitere Informationen findest du unter:', 'More information at:')}<br><a href="https://pages.github.com/" target="_blank" rel="noopener noreferrer">https://pages.github.com/</a></p>
                <p>{t('Es gilt die Datenschutzerklärung von GitHub:', "GitHub's privacy policy applies:")}<br><a href="https://docs.github.com/de/site-policy/privacy-policies/github-privacy-statement" target="_blank" rel="noopener noreferrer">https://docs.github.com/de/site-policy/privacy-policies/github-privacy-statement</a></p>
                <p>{t('Dabei kann es zu einer Übertragung personenbezogener Daten in Drittländer (z. B. USA) kommen. GitHub verwendet geeignete Garantien gemäß Art. 46 DSGVO.', 'Personal data may be transferred to third countries (e.g. USA). GitHub uses appropriate safeguards pursuant to Art. 46 GDPR.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('6. Cookies und Tracking', '6. Cookies and tracking')}</h3>
                <p>{t('Diese Website verwendet keine eigenen Cookies, kein Kontaktformular und keine Analyse- oder Tracking-Tools.', 'This website does not use its own cookies, contact form, or analytics/tracking tools.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('7. Versand der Clan-Auswertung per E-Mail', '7. Sending the clan report by email')}</h3>
                <p>{t('Wenn du dich per E-Mail für den Versand der Clan-Auswertung anmeldest, verarbeiten wir deine E-Mail-Adresse sowie ggf. deinen Ingame-Namen ausschließlich zum Zweck des Versands der Auswertung.', 'If you subscribe by email to receive the clan report, we process your email address and, where applicable, your in-game name solely for the purpose of sending the report.')}</p>
                <p>{t('Die Verarbeitung erfolgt auf Grundlage deiner Einwilligung (Art. 6 Abs. 1 lit. a DSGVO).', 'Processing is based on your consent (Art. 6 (1) (a) GDPR).')}</p>
                <p>{t('Die Daten werden ausschließlich für diesen Zweck verwendet und nicht an Dritte weitergegeben. Du kannst deine Einwilligung jederzeit widerrufen, indem du dich vom Verteiler abmeldest.', 'The data is used solely for this purpose and not shared with third parties. You can withdraw your consent at any time by unsubscribing from the list.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('8. Rechte betroffener Personen', '8. Rights of data subjects')}</h3>
                <p>{t('Betroffene Personen haben im Rahmen der gesetzlichen Vorschriften folgende Rechte:', 'Within the framework of statutory provisions, data subjects have the following rights:')}</p>
                <ul>
                    <li>{t('Recht auf Auskunft (Art. 15 DSGVO)', 'Right of access (Art. 15 GDPR)')}</li>
                    <li>{t('Recht auf Berichtigung (Art. 16 DSGVO)', 'Right to rectification (Art. 16 GDPR)')}</li>
                    <li>{t('Recht auf Löschung (Art. 17 DSGVO)', 'Right to erasure (Art. 17 GDPR)')}</li>
                    <li>{t('Recht auf Einschränkung der Verarbeitung (Art. 18 DSGVO)', 'Right to restriction of processing (Art. 18 GDPR)')}</li>
                    <li>{t('Recht auf Widerspruch gegen die Verarbeitung (Art. 21 DSGVO)', 'Right to object to processing (Art. 21 GDPR)')}</li>
                    <li>{t('Recht auf Beschwerde bei einer Datenschutzaufsichtsbehörde', 'Right to lodge a complaint with a supervisory authority')}</li>
                </ul>
                <p>{t('Spieler haben außerdem die Möglichkeit, der Darstellung ihrer Daten auf dieser Website zu widersprechen. In diesem Fall werden die entsprechenden Daten nach Prüfung entfernt.', 'Players can also object to the display of their data on this website. In that case the corresponding data is removed after review.')}</p>
            </div>
            <div class="legal-section">
                <h3>{t('9. Kontakt zum Datenschutz', '9. Privacy contact')}</h3>
                <p>{t('Bei Fragen zum Datenschutz auf dieser Website kannst du dich an die im Impressum angegebene verantwortliche Stelle wenden.', 'For privacy questions about this website, please contact the controller named in the imprint.')}</p>
            </div>
        </div>
    """

    return impressum_html, datenschutz_html


# === 2. API Datenabruf ===

def fetch_and_build_player_csv() -> Tuple[bool, dict]:
    if not API_TOKEN:
        print("❌ Fehler: Bitte trage deinen SUPERCELL_API_TOKEN in die GitHub Secrets ein.")
        return False, {}

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Accept": "application/json"
    }

    print("Schritt 1: Rufe aktuelle Mitgliederliste ab...")
    members_url = f"{BASE_URL}/clans/{CLAN_TAG}/members"
    members_resp = requests.get(members_url, headers=headers, timeout=30)

    if members_resp.status_code != 200:
        print(f"❌ Fehler beim Abruf der Mitglieder: {members_resp.status_code}")
        return False, {}

    # --- SPENDEN-GEDÄCHTNIS LOGIK ---
    memory = {}
    if donations_memory_path.exists():
        try:
            with open(donations_memory_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception as e:
            print(f"⚠️ Gedächtnis konnte nicht geladen werden: {e}")

    now = datetime.now(timezone.utc)
    curr_week = now.isocalendar()[:2]  # (Jahr, Woche) – verhindert Fehler beim Jahreswechsel

    if now.weekday() == 3 and memory.get("last_reset_week") != curr_week:
        print("🧹 Donnerstag: Spenden-Gedächtnis wird für den neuen Krieg zurückgesetzt.")
        memory = {"last_reset_week": curr_week, "players": {}}

    players_memory = memory.get("players", {})
    current_members = {}

    for m in members_resp.json().get("items", []):
        tag = m["tag"]
        api_donations = m.get("donations", 0)
        api_received = m.get("donationsReceived", 0)

        mem_data = players_memory.get(tag, {"donations": 0, "received": 0})

        if api_donations > mem_data["donations"]:
            mem_data["donations"] = api_donations
        if api_received > mem_data["received"]:
            mem_data["received"] = api_received

        players_memory[tag] = mem_data

        current_members[tag] = {
            "name": m["name"],
            "role": m.get("role", "member"),
            "donations": mem_data["donations"],
            "donations_received": mem_data["received"],
            "trophies": m.get("trophies", 0)
        }

    memory["players"] = players_memory
    memory["last_reset_week"] = memory.get("last_reset_week", curr_week)
    with open(donations_memory_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)

    print("Schritt 2: Rufe Warlog (River Races) ab...")
    log_url = f"{BASE_URL}/clans/{CLAN_TAG}/riverracelog"
    log_resp = requests.get(log_url, headers=headers, timeout=30)

    if log_resp.status_code != 200:
        print(f"❌ Fehler beim Abruf des Warlogs: {log_resp.status_code}")
        return False, {}

    races = log_resp.json().get("items", [])
    print(f"✅ {len(races)} Kriege gefunden. Verarbeite Spielerdaten...")

    players_data = {}
    race_ids = []

    for race in races:
        raw_date = race.get("createdDate", "Unknown")
        race_id = raw_date[:8] if len(raw_date) >= 8 else raw_date
        race_ids.append(race_id)

        my_clan = None
        for standing in race.get("standings", []):
            if standing.get("clan", {}).get("tag") == "#Y9YQC8UG":
                my_clan = standing.get("clan", {})
                break

        if my_clan:
            for p in my_clan.get("participants", []):
                ptag = p.get("tag")
                pname = p.get("name")
                decks = p.get("decksUsed", 0)
                fame = p.get("fame", 0)
                boat_attacks = p.get("boatAttacks", 0)

                if ptag not in players_data:
                    is_curr = ptag in current_members
                    role = current_members[ptag]["role"] if is_curr else "unknown"
                    donations = current_members[ptag]["donations"] if is_curr else 0
                    donations_recv = current_members[ptag]["donations_received"] if is_curr else 0
                    trophies = current_members[ptag]["trophies"] if is_curr else 0
                    players_data[ptag] = {
                        "name": pname,
                        "is_current": is_curr,
                        "role": role,
                        "donations": donations,
                        "donations_received": donations_recv,
                        "trophies": trophies,
                        "history": {}
                    }

                players_data[ptag]["history"][race_id] = {"decks": decks, "fame": fame, "boat_attacks": boat_attacks}

    for tag, data in current_members.items():
        if tag not in players_data:
            players_data[tag] = {
                "name": data["name"],
                "is_current": True,
                "role": data["role"],
                "donations": data["donations"],
                "donations_received": data["donations_received"],
                "trophies": data["trophies"],
                "history": {}
            }
        else:
            players_data[tag]["donations"] = data["donations"]
            players_data[tag]["donations_received"] = data["donations_received"]
            players_data[tag]["trophies"] = data["trophies"]

    # Schritt 2b: Aktuellen Krieg live integrieren (currentriverrace)
    # Strategie: Fester Schlüssel "zzzcurrent" – sortiert immer ganz vorne (z > Ziffern).
    # Nur einbauen wenn ein aktiver Krieg läuft (warDay oder colosseum).
    # Kein Datums-Kalkül → kein Konflikt mit Warlog-Einträgen möglich.
    print("Schritt 2b: Lade Live-Daten aus aktuellem Krieg...")
    try:
        cur_resp = requests.get(f"{BASE_URL}/clans/{CLAN_TAG}/currentriverrace", headers=headers, timeout=30)
        if cur_resp.status_code == 200:
            cur_data = cur_resp.json()
            period_type = cur_data.get("periodType", "")

            if period_type in ("warDay", "colosseum"):
                my_clan_live = None
                for c in cur_data.get("clans", []):
                    if c.get("tag") == CLAN_TAG.replace("%23", "#"):
                        my_clan_live = c
                        break

                if my_clan_live:
                    current_race_id = "zzzcurrent"
                    for p in my_clan_live.get("participants", []):
                        ptag = p.get("tag")
                        pname = p.get("name")
                        fame = p.get("fame", 0)        # kumulative Fame im aktuellen Krieg
                        decks = p.get("decksUsed", 0)  # Decks gesamt im aktuellen Krieg
                        ba = p.get("boatAttacks", 0)

                        if ptag not in players_data:
                            is_curr = ptag in current_members
                            players_data[ptag] = {
                                "name": pname,
                                "is_current": is_curr,
                                "role": current_members[ptag]["role"] if is_curr else "unknown",
                                "donations": current_members[ptag]["donations"] if is_curr else 0,
                                "donations_received": current_members[ptag]["donations_received"] if is_curr else 0,
                                "trophies": current_members[ptag]["trophies"] if is_curr else 0,
                                "history": {}
                            }

                        players_data[ptag]["history"][current_race_id] = {
                            "decks": decks, "fame": fame, "boat_attacks": ba
                        }

                    race_ids.append(current_race_id)
                    print(f"✅ Aktiver Krieg ({period_type}) als Live-Spalte 'zzzcurrent' eingefügt.")
                else:
                    print("ℹ️ Unser Clan nicht im aktuellen Rennen gefunden.")
            else:
                print(f"ℹ️ Kein aktiver Krieg (periodType={period_type}) – keine Live-Spalte.")
        else:
            print(f"ℹ️ currentriverrace nicht verfügbar ({cur_resp.status_code}).")
    except Exception as e:
        print(f"⚠️ Live-Kriegsdaten konnten nicht geladen werden: {e}")

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = upload_folder / f"clan_export_{date_str}.csv"

    race_ids = sorted(set(race_ids), reverse=True)
    headers_csv = [
        "player_tag",
        "player_name",
        "player_is_current_member",
        "player_role",
        "player_donations",
        "player_donations_received",
        "player_trophies",
        "player_contribution_count",
        "player_participating_count",
        "player_total_decks_used",
        "player_total_boat_attacks"
    ]

    for rid in race_ids:
        headers_csv.extend([f"s_{rid}_fame", f"s_{rid}_decks_used", f"s_{rid}_boat_attacks"])

    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers_csv)
        total_races = len(race_ids)

        for tag, data in players_data.items():
            total_decks = 0
            total_boat_attacks = 0
            contribution_count = 0
            row_history = []

            for rid in race_ids:
                r_data = data["history"].get(rid, {"decks": 0, "fame": 0, "boat_attacks": 0})
                decks = r_data["decks"]
                fame = r_data["fame"]
                ba = r_data.get("boat_attacks", 0)
                row_history.extend([fame, decks, ba])

                # zzzcurrent ist der laufende Krieg (noch nicht abgeschlossen).
                # Er wird nicht in den Score-Metriken gezählt – unfair, da noch nicht fertig.
                if rid != "zzzcurrent":
                    total_decks += decks
                    total_boat_attacks += ba
                    if decks > 0:
                        contribution_count += 1

            # wars_in_clan: Anzahl Kriege in denen der Spieler laut API teilgenommen hat.
            # Entspricht der tatsaechlichen Clan-Zugehoerigkeit im Auswertungsfenster.
            # Nicht total_races (immer 10), weil neue Spieler die frueheren Kriege schlicht
            # noch nicht kennen konnten. zzzcurrent (laufender Krieg) wird nicht mitgezählt.
            wars_in_clan = len([k for k in data["history"] if k != "zzzcurrent"])

            row = [
                tag,
                data["name"],
                data["is_current"],
                data["role"],
                data.get("donations", 0),
                data.get("donations_received", 0),
                data.get("trophies", 0),
                contribution_count,
                wars_in_clan,
                total_decks,
                total_boat_attacks
            ]
            row.extend(row_history)
            writer.writerow(row)

    print(f"✅ Spieler-Daten erfolgreich exportiert nach: {filename}\n")
    return True, current_members


# === 2.3 Clan-Gesamtdaten abrufen ===

def fetch_clan_overview() -> dict:
    """Ruft Clan-Profil ab: Kriegstrophäen, Spenden/Woche, Mitgliederanzahl, Liga, lokales Ranking."""
    if not API_TOKEN:
        return {}

    headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
    try:
        resp = requests.get(f"{BASE_URL}/clans/{CLAN_TAG}", headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"⚠️ Clan-Profil konnte nicht abgerufen werden: {resp.status_code}")
            return {}

        data = resp.json()
        war_league_name = data.get("warLeague", {}).get("name", "")

        # Lokales Ranking (Deutschland = 57000094)
        local_rank = None
        try:
            our_tag = CLAN_TAG.replace("%23", "#")
            rank_resp = requests.get(f"{BASE_URL}/locations/57000094/rankings/clanwars", headers=headers, timeout=30)
            if rank_resp.status_code == 200:
                for item in rank_resp.json().get("items", []):
                    if item.get("tag") == our_tag:
                        local_rank = item.get("rank")
                        break
        except Exception as e:
            print(f"⚠️ Lokales Ranking konnte nicht abgerufen werden: {e}")

        return {
            "clan_war_trophies": data.get("clanWarTrophies", 0),
            "donations_per_week": data.get("donationsPerWeek", 0),
            "member_count": data.get("members", 0),
            "required_trophies": data.get("requiredTrophies", 0),
            "description": data.get("description", ""),
            "clan_score": data.get("clanScore", 0),
            "war_league_name": war_league_name,
            "local_rank": local_rank,
        }
    except Exception as e:
        print(f"⚠️ Fehler beim Abruf des Clan-Profils: {e}")
        return {}


# === 2.4 Spieler-Profile abrufen ===

def fetch_player_profiles(current_members: dict) -> dict:
    """Ruft erweiterte Spielerprofile ab: Win/Loss, Best Trophies, Level, Lieblingskarte."""
    if not API_TOKEN:
        return {}

    headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
    profiles = {}
    count = 0

    print("Schritt 5: Rufe Spieler-Profile ab (Bitte warten)...")
    for tag in current_members.keys():
        clean_tag = tag.replace("#", "%23")
        try:
            resp = requests.get(f"{BASE_URL}/players/{clean_tag}", headers=headers, timeout=30)
        except Exception:
            time.sleep(0.1)
            continue

        if resp.status_code != 200:
            time.sleep(0.1)
            continue

        data = resp.json()
        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        total_battles = wins + losses

        profiles[tag] = {
            "exp_level": data.get("expLevel", 0),
            "best_trophies": data.get("bestTrophies", 0),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total_battles) * 100) if total_battles > 0 else 0,
            "three_crown_wins": data.get("threeCrownWins", 0),
            "challenge_max_wins": data.get("challengeMaxWins", 0),
            "war_day_wins": data.get("warDayWins", 0),
            "total_donations": data.get("totalDonations", 0),
            "favourite_card": data.get("currentFavouriteCard", {}).get("name", ""),
        }

        count += 1
        if count % 10 == 0:
            print(f"  ... {count}/{len(current_members)} Profile geladen")
        time.sleep(0.1)

    print(f"✅ {len(profiles)} Spieler-Profile geladen.\n")
    return profiles


# === 2.5 Battlelogs analysieren (Top Decks) ===

def update_top_decks(current_members: dict, top_decks_data: dict, player_war_decks: dict) -> tuple[dict, dict, dict]:
    print("Schritt 4: Spioniere Battlelogs für Clan-Meta Decks aus (Bitte warten)...")
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}

    metadata = top_decks_data.get("_metadata", {"last_battles": {}})
    decks = top_decks_data.get("decks", {})
    opponent_decks = top_decks_data.get("_opponent_decks", {})  # Gegner-Deck-Analyse (persistiert)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=DECK_LOOKBACK_DAYS)

    for deck_data in decks.values():
        deck_data.setdefault("recent_matches", [])
        deck_data.setdefault("players", [])
        deck_data.setdefault("tags", [])

    count = 0
    for tag, member_info in current_members.items():
        p_name = member_info["name"]
        clean_tag = tag.replace("#", "%23")

        try:
            resp = requests.get(f"{BASE_URL}/players/{clean_tag}/battlelog", headers=headers, timeout=30)
        except Exception:
            time.sleep(0.1)
            continue

        if resp.status_code != 200:
            time.sleep(0.1)
            continue

        battles = resp.json()
        latest_time_in_log = None
        last_processed_time = metadata["last_battles"].get(tag, "")

        for battle in battles:
            b_time = battle.get("battleTime", "")
            if not latest_time_in_log:
                latest_time_in_log = b_time

            if b_time <= last_processed_time:
                break

            b_type = battle.get("type", "")

            if "riverRace" in b_type:
                raw_tag = tag.replace("#", "")

                # Einzel-Kämpfe sammeln: entweder direkt (team) oder aus Duell-Runden (rounds)
                round_list = []

                if "team" in battle:
                    # Standard-Battle oder Triple Elixir etc.: direkt auswerten
                    round_list.append((battle["team"][0], battle["opponent"][0]))

                elif "rounds" in battle:
                    # Duell-Battle: jede Runde einzeln auswerten (Bo3)
                    for rnd in battle.get("rounds", []):
                        if "team" in rnd and "opponent" in rnd:
                            round_list.append((rnd["team"][0], rnd["opponent"][0]))

                for team, opponent in round_list:
                    cards = team.get("cards", [])

                    if len(cards) == 8:
                        crowns_t = team.get("crowns", 0)
                        crowns_o = opponent.get("crowns", 0)

                        is_win  = crowns_t > crowns_o
                        is_loss = crowns_o > crowns_t

                        if is_win or is_loss:
                            deck_ids = sorted([str(c["id"]) for c in cards])
                            deck_hash = "-".join(deck_ids)

                            if deck_hash not in decks:
                                decks[deck_hash] = {
                                    "cards": [
                                        {
                                            "id": c["id"],
                                            "name": c["name"],
                                            "icon": c.get("iconUrls", {}).get("medium", "")
                                        } for c in cards
                                    ],
                                    "wins": 0,
                                    "losses": 0,
                                    "players": [],
                                    "tags": [],
                                    "recent_matches": []
                                }

                            match_result = "win" if is_win else "loss"
                            existing_matches = decks[deck_hash].setdefault("recent_matches", [])
                            match_key = f"{b_time}|{raw_tag}|{match_result}"
                            if not any(
                                f"{m.get('time', '')}|{m.get('tag', '')}|{m.get('result', '')}" == match_key
                                for m in existing_matches
                            ):
                                existing_matches.append({
                                    "time": b_time,
                                    "result": match_result,
                                    "player": p_name,
                                    "tag": raw_tag
                                })

                            # Spieler-spezifisches Deck-Tracking (inkl. Battle-Typ)
                            if raw_tag not in player_war_decks:
                                player_war_decks[raw_tag] = {"name": p_name, "battles": []}
                            player_war_decks[raw_tag]["name"] = p_name
                            pw_battles = player_war_decks[raw_tag]["battles"]
                            pw_key = f"{b_time}|{deck_hash}|{match_result}"
                            if not any(
                                f"{b.get('time', '')}|{b.get('deck_hash', '')}|{b.get('result', '')}" == pw_key
                                for b in pw_battles
                            ):
                                pw_battles.append({
                                    "time":      b_time,
                                    "result":    match_result,
                                    "type":      b_type,
                                    "deck_hash": deck_hash,
                                    "cards": [
                                        {
                                            "id":   c["id"],
                                            "name": c["name"],
                                            "icon": c.get("iconUrls", {}).get("medium", "")
                                        } for c in cards
                                    ]
                                })

                        # Gegner-Deck-Tracking (vollständige Decks)
                        opp_cards = opponent.get("cards", [])
                        if len(opp_cards) == 8:
                            opp_deck_ids = sorted([str(oc["id"]) for oc in opp_cards])
                            opp_deck_hash = "-".join(opp_deck_ids)
                            if opp_deck_hash not in opponent_decks or not isinstance(opponent_decks[opp_deck_hash], dict) or "cards" not in opponent_decks[opp_deck_hash]:
                                opponent_decks[opp_deck_hash] = {
                                    "cards": [
                                        {
                                            "id":   oc["id"],
                                            "name": oc["name"],
                                            "icon": oc.get("iconUrls", {}).get("medium", "")
                                        } for oc in opp_cards
                                    ],
                                    "seen":   0,
                                    "losses": 0
                                }
                            opponent_decks[opp_deck_hash]["seen"] += 1
                            if is_loss:
                                opponent_decks[opp_deck_hash]["losses"] += 1

        if latest_time_in_log:
            metadata["last_battles"][tag] = latest_time_in_log

        count += 1
        if count % 10 == 0:
            print(f"  ... {count}/50 Spieler gescannt")
        time.sleep(0.1)

    for deck_hash in list(decks.keys()):
        deck_data = decks[deck_hash]
        recent_matches = []
        for match in deck_data.get("recent_matches", []):
            match_dt = parse_battle_time(match.get("time", ""))
            if match_dt and match_dt >= cutoff_dt:
                recent_matches.append(match)

        recent_matches.sort(key=lambda m: m.get("time", ""), reverse=True)
        deck_data["recent_matches"] = recent_matches
        deck_data["wins"] = sum(1 for m in recent_matches if m.get("result") == "win")
        deck_data["losses"] = sum(1 for m in recent_matches if m.get("result") == "loss")

        players_ordered = list(dict.fromkeys(m.get("player", "") for m in recent_matches if m.get("player")))
        tags_ordered = list(dict.fromkeys(m.get("tag", "") for m in recent_matches if m.get("tag")))
        deck_data["players"] = players_ordered
        deck_data["tags"] = tags_ordered

        if not recent_matches:
            del decks[deck_hash]

    # --- DECK CLEANUP (Max 100 Decks behalten, um JSON klein zu halten) ---
    if len(decks) > 100:
        to_remove = heapq.nsmallest(
            len(decks) - 100, decks,
            key=lambda k: (get_deck_winrate(decks[k]), decks[k]["wins"] + decks[k]["losses"], decks[k]["wins"])
        )
        for k in to_remove:
            del decks[k]

    top_decks_data["_metadata"] = metadata
    top_decks_data["decks"] = decks
    top_decks_data["_opponent_decks"] = opponent_decks

    # Spieler-Decks: alte Einträge (> DECK_LOOKBACK_DAYS) entfernen
    for raw_tag in list(player_war_decks.keys()):
        recent = [
            b for b in player_war_decks[raw_tag]["battles"]
            if (dt := parse_battle_time(b.get("time", ""))) and dt >= cutoff_dt
        ]
        if recent:
            player_war_decks[raw_tag]["battles"] = sorted(recent, key=lambda b: b.get("time", ""), reverse=True)
        else:
            del player_war_decks[raw_tag]

    print("✅ Battlelogs erfolgreich gescannt. Top-Decks aktualisiert.\n")
    return top_decks_data, opponent_decks, player_war_decks


def parse_battle_time(battle_time: str) -> datetime | None:
    if not battle_time:
        return None

    for fmt in ("%Y%m%dT%H%M%S.000Z", "%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(battle_time, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_deck_winrate(deck_data: dict) -> float:
    total_matches = deck_data.get("wins", 0) + deck_data.get("losses", 0)
    if total_matches <= 0:
        return 0.0
    return deck_data.get("wins", 0) / total_matches


def is_beginner_friendly_deck(cards: list) -> bool:
    card_names = {c.get("name", "") for c in cards}
    tricky_cards = {
        "X-Bow", "Mortar", "Goblin Barrel", "Skeleton Barrel", "Miner", "Graveyard",
        "Wall Breakers", "Goblin Drill", "Clone", "Mirror", "Freeze", "Tornado"
    }
    if card_names.intersection(tricky_cards):
        return False

    archetype = get_deck_archetype(cards)
    return archetype in {"🛡️ Schwerer Angriff (Beatdown)", "⚡ Schneller Angriff (Rush/Spam)", "⚔️ Hybrid / Allrounder"}


def build_deck_sections(top_decks_data: dict) -> list:
    decks = []
    seen_card_names: set = set()
    for deck_hash, deck_data in top_decks_data.get("decks", {}).items():
        total_matches = deck_data.get("wins", 0) + deck_data.get("losses", 0)
        if total_matches <= 0:
            continue

        # Deduplication by card names (handles evolved card variants with different IDs)
        card_key = frozenset(c["name"] for c in deck_data.get("cards", []))
        if card_key in seen_card_names:
            continue
        seen_card_names.add(card_key)

        deck_copy = dict(deck_data)
        deck_copy["_hash"] = deck_hash
        deck_copy["total_matches"] = total_matches
        deck_copy["winrate"] = int(round(get_deck_winrate(deck_data) * 100))
        deck_copy["archetype"] = get_deck_archetype(deck_data.get("cards", []))
        deck_copy["is_beginner_friendly"] = is_beginner_friendly_deck(deck_data.get("cards", []))
        decks.append(deck_copy)

    meta_decks = sorted(
        [d for d in decks if d["total_matches"] >= DECK_META_MIN_MATCHES],
        key=lambda d: (d["winrate"], d["total_matches"], d["wins"]),
        reverse=True
    )[:10]
    meta_hashes = {d["_hash"] for d in meta_decks}

    solid_decks = sorted(
        [d for d in decks if d["total_matches"] >= DECK_SOLID_MIN_MATCHES and d["winrate"] >= 55],
        key=lambda d: (d["total_matches"], d["winrate"], d["wins"]),
        reverse=True
    )
    solid_decks = [d for d in solid_decks if d["_hash"] not in meta_hashes][:10]
    solid_hashes = {d["_hash"] for d in solid_decks}

    beginner_decks = sorted(
        [
            d for d in decks
            if d["total_matches"] >= DECK_BEGINNER_MIN_MATCHES
            and d["winrate"] >= 50
            and d["is_beginner_friendly"]
        ],
        key=lambda d: (d["winrate"], d["total_matches"], d["wins"]),
        reverse=True
    )
    beginner_decks = [d for d in beginner_decks if d["_hash"] not in meta_hashes and d["_hash"] not in solid_hashes][:10]

    return [
        {
            "title": "🏆 " + t("Meta-Decks", "Meta Decks"),
            "description": t(
                f"Die stärksten und belastbarsten Kriegs-Decks aus den letzten {DECK_LOOKBACK_DAYS} Tagen.",
                f"The strongest and most resilient war decks from the last {DECK_LOOKBACK_DAYS} days.",
            ),
            "decks": meta_decks
        },
        {
            "title": "🛡️ " + t("Solide Decks", "Solid Decks"),
            "description": t(
                f"Verlässliche Decks mit ordentlicher Quote und genug Spielen aus den letzten {DECK_LOOKBACK_DAYS} Tagen.",
                f"Reliable decks with a decent win rate and enough games from the last {DECK_LOOKBACK_DAYS} days.",
            ),
            "decks": solid_decks
        },
        {
            "title": "🎯 " + t("Einsteigerfreundlich", "Beginner-friendly"),
            "description": t(
                "Einfachere Decks für Leute, die ein klares und stabiles Kriegs-Deck suchen.",
                "Simpler decks for players looking for a clear and stable war deck.",
            ),
            "decks": beginner_decks
        }
    ]



def build_top_opponent_decks(opponent_decks: dict, top_n: int = 10) -> list:
    """Findet die Top-N Gegner-Decks gegen die wir am häufigsten verloren haben."""
    valid = [
        (deck_hash, data)
        for deck_hash, data in opponent_decks.items()
        if isinstance(data, dict) and "cards" in data and data.get("losses", 0) > 0
    ]
    if not valid:
        return []

    valid.sort(key=lambda x: (x[1].get("losses", 0), x[1].get("seen", 0)), reverse=True)
    result = []
    for rank, (deck_hash, data) in enumerate(valid[:top_n], start=1):
        seen   = data.get("seen", 0)
        losses = data.get("losses", 0)
        loss_rate = int(round(losses / seen * 100)) if seen > 0 else 0
        result.append({
            "rank":      rank,
            "cards":     data["cards"],
            "seen":      seen,
            "losses":    losses,
            "loss_rate": loss_rate,
            "archetype": get_deck_archetype(data["cards"]),
        })
    return result


def get_signal_state(value: float, green_min: float, yellow_min: float) -> tuple[str, str]:
    if value >= green_min:
        return "stark", "#10b981"
    if value >= yellow_min:
        return "okay", "#fbbf24"
    return "kritisch", "#ef4444"


def calculate_teamplay_score(active_players: list[dict]) -> tuple[int, dict]:
    total_players = len(active_players)
    if total_players == 0:
        return 0, {"donors": 0, "leecher": 0, "sleeper": 0, "donor_share": 0}

    donors = sum(1 for p in active_players if p["donations"] > 0)
    leecher = sum(
        1
        for p in active_players
        if p["donations"] == 0 and p["donations_received"] > 0 and p["teilnahme_int"] > APP_CONFIG["MIN_PARTICIPATION"]
    )
    sleeper = sum(1 for p in active_players if p["donations"] == 0 and p["donations_received"] == 0)

    donor_share = (donors / total_players) * 100
    leecher_share = (leecher / total_players) * 100
    sleeper_share = (sleeper / total_players) * 100

    score = round(max(0, min(100, donor_share - (leecher_share * 0.7) - (sleeper_share * 0.3))))
    return score, {
        "donors": donors,
        "leecher": leecher,
        "sleeper": sleeper,
        "donor_share": round(donor_share)
    }


def get_player_focus(score: float, fame_per_deck: int, donations: int, is_welpenschutz: bool, current_decks: int) -> tuple[str, str]:
    if is_welpenschutz:
        return "<span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span>", "#38bdf8"
    if score >= APP_CONFIG["BADGE_STARK_SCORE"] and fame_per_deck >= APP_CONFIG["BADGE_STARK_FAME"]:
        return "<span class='i18n-de'>⭐ stark</span><span class='i18n-en'>⭐ strong</span>", "#10b981"
    if score >= APP_CONFIG["BADGE_STABIL_SCORE"] and fame_per_deck >= APP_CONFIG["BADGE_STABIL_FAME"]:
        return "<span class='i18n-de'>🛡️ stabil</span><span class='i18n-en'>🛡️ stable</span>", "#38bdf8"
    if score < APP_CONFIG["STRIKE_THRESHOLD"]:
        return "<span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span>", "#f97316"
    if current_decks > 0 and fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"]:
        return "<span class='i18n-de'>👀 auffällig</span><span class='i18n-en'>👀 watch</span>", "#ef4444"
    return "<span class='i18n-de'>🙂 solide</span><span class='i18n-en'>🙂 solid</span>", "#94a3b8"


def get_deck_archetype(cards: list) -> str:
    card_names = [c.get("name", "") for c in cards]
    if any(n in card_names for n in ["Golem", "Lava Hound", "Giant", "Goblin Giant", "Electro Giant", "Elixir Golem"]):
        return "🛡️ " + t("Schwerer Angriff (Beatdown)", "Heavy Push (Beatdown)")
    if any(n in card_names for n in ["X-Bow", "Mortar"]):
        return "🏹 " + t("Belagerung (Siege)", "Siege")
    if any(n in card_names for n in ["Goblin Barrel", "Skeleton Barrel", "Miner", "Graveyard", "Wall Breakers", "Goblin Drill"]):
        return "🗡️ " + t("Nadelstiche (Bait/Control)", "Pinpricks (Bait/Control)")
    if any(n in card_names for n in ["Hog Rider", "Royal Hogs", "Battle Ram", "Ram Rider", "Balloon"]):
        return "⚡ " + t("Schneller Angriff (Rush/Spam)", "Fast Push (Rush/Spam)")
    return "⚔️ " + t("Hybrid / Allrounder", "Hybrid / All-rounder")


# === 3. Dateiverwaltung & Helfer ===

def get_encoded_header_image(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with open(path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded_string}"
    except Exception:
        return ""


def archiviere_alte_dateien(ordner: Path, archiv_ordner: Path, anzahl: int = 2, max_archiv: int = 10) -> None:
    archiv_ordner.mkdir(exist_ok=True, parents=True)
    dateien = sorted(ordner.glob("*.csv"), key=os.path.getctime)
    for datei in dateien[:-anzahl]:
        shutil.move(str(datei), archiv_ordner / datei.name)

    # --- ARCHIV CLEANUP (Physisch löschen) ---
    archiv_dateien = sorted(archiv_ordner.glob("*.csv"), key=os.path.getctime)
    for datei in archiv_dateien[:-max_archiv]:
        try:
            datei.unlink()
        except Exception:
            pass


def finde_neueste_csv(ordner: Path) -> Path:
    csvs = list(ordner.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError("Keine CSV-Datei im Upload-Ordner gefunden.")
    return max(csvs, key=os.path.getctime)


def chunk_list(lst: list, n: int) -> list:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def enforce_chat_limit(message: str, prefix: str = "", limit: int = 255) -> str:
    full_message = f"{prefix}{message}"
    if len(full_message) <= limit:
        return full_message

    allowed_message_len = max(0, limit - len(prefix) - 3)
    trimmed_message = message[:allowed_message_len].rstrip(" ,.;:!-")
    return f"{prefix}{trimmed_message}..."


def escape_for_html(text: str) -> str:
    return html.escape(text, quote=True)


def is_clan_war_period(now_utc: datetime | None = None) -> bool:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    weekday = now_utc.weekday()
    current_minutes = now_utc.hour * 60 + now_utc.minute
    war_boundary_minutes = 10 * 60

    if weekday == 3:
        return current_minutes >= war_boundary_minutes
    if weekday in [4, 5, 6]:
        return True
    if weekday == 0:
        return current_minutes < war_boundary_minutes
    return False


def get_river_race_status_de(now_utc: datetime | None = None) -> str:
    return "Clankrieg" if is_clan_war_period(now_utc) else "Trainingstag"


def load_member_memory() -> dict:
    default_memory = {"current_players": {}, "ever_seen_players": {}, "pending_events": []}
    if not member_memory_path.exists():
        return default_memory

    try:
        with open(member_memory_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                if (
                    "current_players" in loaded and isinstance(loaded["current_players"], dict)
                    and "ever_seen_players" in loaded and isinstance(loaded["ever_seen_players"], dict)
                ):
                    loaded.setdefault("pending_events", [])
                    if not isinstance(loaded["pending_events"], list):
                        loaded["pending_events"] = []
                    return loaded

                # Migration alter Struktur
                if "players" in loaded and isinstance(loaded["players"], dict):
                    return {
                        "current_players": loaded["players"],
                        "ever_seen_players": loaded["players"].copy(),
                        "pending_events": []
                    }
    except Exception as e:
        print(f"⚠️ Warnung: member_memory.json fehlerhaft, fange bei 0 an. ({e})")

    return default_memory


def save_member_memory(member_memory: dict) -> None:
    with open(member_memory_path, "w", encoding="utf-8") as f:
        json.dump(member_memory, f, ensure_ascii=False, indent=4)


# === 4. HTML Templates ===

def render_html_template(
    clan_name,
    heute_datum,
    header_img_src,
    hype_balken_html,
    radar_html,
    mahnwache_html,
    clan_ampel_html,
    weekly_summary_html,
    coach_html,
    clan_avg,
    clan_avg_points_per_deck,
    top_performers,
    top_spender,
    pusher_html,
    pusher_chat,
    records,
    urlaub_html,
    top_aufsteiger,
    top_leecher,
    total_msgs,
    chat_boxes_html,
    table_html,
    deck_html,
    impressum_html,
    datenschutz_html,
    clan_overview_html="",
    opponent_meta_html=""
):
    return f"""
    <html lang="de">
    <head>
        <meta charset='utf-8'>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Auswertung: {clan_name}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
            html[lang="de"] .i18n-en {{ display: none !important; }}
            html[lang="en"] .i18n-de {{ display: none !important; }}
            .lang-toggle {{ position: absolute; top: 16px; right: 16px; display: inline-flex; gap: 0; background: rgba(15,23,42,0.85); border: 1px solid rgba(255,255,255,0.18); border-radius: 999px; padding: 3px; z-index: 5; backdrop-filter: blur(4px); box-shadow: 0 4px 12px rgba(0,0,0,0.4); }}
            .lang-toggle button {{ background: transparent; color: #94a3b8; border: 0; padding: 6px 14px; border-radius: 999px; font-family: inherit; font-weight: 800; font-size: 0.85em; letter-spacing: 0.06em; cursor: pointer; transition: all 0.2s ease; }}
            .lang-toggle button:hover {{ color: #fff; }}
            .lang-toggle button.active {{ background: #38bdf8; color: #0f172a; box-shadow: 0 2px 6px rgba(56,189,248,0.45); }}
            @media (max-width: 600px) {{ .lang-toggle {{ top: 10px; right: 10px; padding: 2px; }} .lang-toggle button {{ padding: 5px 10px; font-size: 0.78em; }} }}
            html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
            body {{ font-family: 'Nunito', sans-serif; margin: 0; padding: 0; background: linear-gradient(rgba(15, 23, 42, 0.85), rgba(15, 23, 42, 0.95)), url('https://images.hdqwalls.com/download/clash-royale-4k-19-1920x1080.jpg') no-repeat center center fixed; background-size: cover; color: #f8fafc; }}
            .container {{ max-width: 1200px; margin: auto; padding: 20px; box-sizing: border-box; }}
            .header-container {{ position: relative; background: linear-gradient(rgba(15, 23, 42, 0.7), rgba(15, 23, 42, 0.9)), url('{header_img_src}') no-repeat center center; background-size: cover; border-radius: 12px; padding: 40px 20px; margin-top: 20px; margin-bottom: 20px; text-align: center; border: 1px solid rgba(255, 255, 255, 0.1); box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3); }}
            .header-title {{ font-weight: 800; color: #ffffff; font-size: 2.2em; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.5); letter-spacing: 1px; }}
            .header-date {{ font-weight: 400; font-size: 0.45em; color: #cbd5e1; display: block; margin-top: 10px; letter-spacing: 0px; }}
            .header-mobile-tip {{ display: block; font-size: 0.55em; color: #f8fafc; margin-top: 15px; font-weight: 800; letter-spacing: 0.5px; text-shadow: 0 2px 4px rgba(0,0,0,0.8); }}

            .tab-container {{ display: flex; gap: 10px; margin-bottom: 30px; border-bottom: 2px solid rgba(255,255,255,0.1); padding-bottom: 15px; position: sticky; top: -1px; background: rgba(15, 23, 42, 0.98); z-index: 1000; padding-top: 15px; overflow-x: auto; white-space: nowrap; scrollbar-width: none; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }}
            .tab-container::-webkit-scrollbar {{ display: none; }}
            .tab-btn {{ flex: 1; background: rgba(30, 41, 59, 0.8); color: #94a3b8; border: 1px solid rgba(255,255,255,0.1); padding: 14px 20px; border-radius: 8px; font-weight: 600; font-size: 1.05em; cursor: pointer; transition: all 0.2s ease; font-family: inherit; min-width: max-content; }}
            .tab-btn:hover {{ background: rgba(56, 189, 248, 0.2); color: #fff; }}
            .tab-btn.active {{ background: #38bdf8; color: #0f172a; border-color: #38bdf8; font-weight: 800; box-shadow: 0 4px 10px rgba(56, 189, 248, 0.3); }}
            .tab-content {{ display: none; animation: fadeIn 0.4s ease-in-out; }}
            .tab-content.active {{ display: block; }}
            @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}

            .welcome-box {{ background: linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95)); border-left: 5px solid #fbbf24; padding: 25px 30px; border-radius: 12px; margin-bottom: 30px; font-size: 1.05em; color: #e2e8f0; line-height: 1.7; box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3); border: 1px solid rgba(251, 191, 36, 0.2); }}
            .welcome-box p {{ margin: 0 0 12px 0; }}
            .welcome-box p:last-child {{ margin: 0; }}
            .welcome-title {{ font-size: 1.4em; color: #fbbf24; margin-top: 0; margin-bottom: 15px; font-weight: 800; display: flex; align-items: center; gap: 10px; }}

            .info-box {{ background: rgba(30, 41, 59, 0.85); border-left: 5px solid #38bdf8; padding: 20px 25px; border-radius: 8px; margin-bottom: 40px; font-size: 1em; color: #e2e8f0; line-height: 1.6; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2); border: 1px solid rgba(255, 255, 255, 0.05); }}
            .signal-board {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }}
            .signal-card {{ background: rgba(30, 41, 59, 0.8); border-radius: 12px; padding: 18px 20px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 4px 15px rgba(0,0,0,0.18); }}
            .signal-card h4 {{ margin: 0 0 8px 0; color: #cbd5e1; font-size: 0.95em; font-weight: 700; }}
            .signal-value {{ font-size: 1.8em; font-weight: 800; margin-bottom: 6px; }}
            .signal-state {{ font-size: 0.9em; font-weight: 700; }}
            .focus-badge {{ display: inline-block; margin-left: 8px; padding: 3px 8px; border-radius: 999px; font-size: 0.72em; font-weight: 800; vertical-align: middle; }}
            .dashboard {{ display: flex; gap: 20px; margin-bottom: 30px; flex-wrap: wrap; }}
            .card {{ flex: 1; min-width: 220px; background: rgba(30, 41, 59, 0.8); padding: 20px 25px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.08); box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2); }}
            .card h3 {{ font-weight: 600; font-size: 1.1em; margin-top: 0; color: #cbd5e1; }}
            .card.avg {{ border-top: 4px solid #38bdf8; }}
            .card.top {{ border-top: 4px solid #fbbf24; }}
            .card.aufsteiger {{ border-top: 4px solid #10b981; }}
            .card.spender {{ border-top: 4px solid #a855f7; }}
            .card.leecher {{ border-top: 4px solid #64748b; }}
            .card.pusher {{ border-top: 4px solid #f97316; }}
            .card.hof {{ border-top: 4px solid #8b5cf6; }}
            .card.urlaub {{ border-top: 4px solid #0ea5e9; }}
            .card.messenger {{ border-top: 4px solid #f1c40f; width: 100%; flex: 100%; }}
            .card h1 {{ font-weight: 800; font-size: 2.5em; margin: 10px 0; color: #38bdf8; }}
            .card ul {{ margin: 0; padding-left: 20px; font-size: 1.05em; line-height: 1.6; color: #f1f5f9; }}

            .deck-slider {{ display: flex; overflow-x: auto; gap: 20px; padding-bottom: 20px; scroll-snap-type: x mandatory; }}
            .deck-slider::-webkit-scrollbar {{ height: 8px; }}
            .deck-slider::-webkit-scrollbar-track {{ background: rgba(0,0,0,0.2); border-radius: 4px; }}
            .deck-slider::-webkit-scrollbar-thumb {{ background: #38bdf8; border-radius: 4px; }}

            .deck-card {{ background: rgba(30, 41, 59, 0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; flex: 0 0 300px; scroll-snap-align: start; box-shadow: 0 4px 15px rgba(0,0,0,0.2); border-top: 4px solid #f97316; display: flex; flex-direction: column; }}
            .archetype-badge {{ display: inline-block; background: rgba(249, 115, 22, 0.15); color: #f97316; padding: 4px 8px; border-radius: 6px; font-size: 0.8em; font-weight: bold; margin-bottom: 15px; border: 1px solid rgba(249, 115, 22, 0.3); text-align: center; }}
            .deck-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px; }}
            .winrate {{ background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 0.85em; margin-left: auto; }}
            .deck-images {{ display: flex; flex-wrap: wrap; justify-content: center; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); }}
            .copy-btn {{ display: block; text-align: center; text-decoration: none; padding: 10px; border-radius: 8px; font-weight: bold; margin-top: 8px; transition: 0.2s; border: 1px solid rgba(255,255,255,0.1); }}
            .copy-btn:hover {{ opacity: 0.8; }}

            .tier-section {{ position: relative; }}
            .tier-title {{ margin: 0; padding: 15px 0 10px 0; font-weight: 800; font-size: 1.4em; color: #fbbf24; border-bottom: 2px solid rgba(255,255,255,0.1); }}
            table {{ width: 100%; table-layout: fixed; border-collapse: collapse; background: rgba(15, 23, 42, 0.9); border-radius: 8px; margin-bottom: 30px; border: 1px solid rgba(255, 255, 255, 0.1); }}
            th:nth-child(1) {{ width: 18%; }}
            th:nth-child(2) {{ width: 12%; text-align: center; }}
            th:nth-child(3) {{ width: 10%; text-align: center; }}
            th:nth-child(4) {{ width: 9%; text-align: center; }}
            th:nth-child(5) {{ width: 10%; text-align: center; }}
            th:nth-child(6) {{ width: 9%; text-align: center; }}
            th:nth-child(7) {{ width: 10%; text-align: center; }}
            th:nth-child(8) {{ width: 9%; text-align: center; }}
            th:nth-child(9) {{ width: 13%; text-align: center; }}
            tr:nth-child(odd) {{ background-color: rgba(0, 0, 0, 0.45); }} tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.15); }} tr:hover {{ background-color: rgba(255, 255, 255, 0.3); }}
            th, td {{ padding: 14px 8px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; vertical-align: middle; }}
            td:nth-child(2), td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {{ text-align: center; }}
            th:nth-child(3), td:nth-child(3) {{ text-align: center; white-space: nowrap; }}

            th {{ position: sticky; top: 128px; background-color: #0f172a; color: #94a3b8; z-index: 800; font-weight: 600; font-size: 0.9em; border-bottom: 1px solid rgba(255,255,255,0.1); line-height: 1.4; box-shadow: 0 4px 5px rgba(0,0,0,0.3); }}
            td {{ border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 1.05em; }}

            .badge-ja {{ background-color: #10b981; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-weight: 800; font-size: 0.8em; margin-left: 8px; }}
            .name-col {{ font-weight: 800; color: #ffffff; }}
            .focus-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 104px; padding: 5px 10px; border-radius: 999px; font-size: 0.8em; font-weight: 800; white-space: nowrap; }}

            .trend-cell {{ font-size: 16px !important; white-space: nowrap; line-height: 1; }}

            .wiki-table {{ width: 100%; table-layout: auto; border-collapse: collapse; background: rgba(0, 0, 0, 0.3); border-radius: 8px; margin: 15px 0; border: 1px solid rgba(255, 255, 255, 0.1); font-size: 0.85em; overflow-x: auto; }}
            .wiki-table th {{ position: static; box-shadow: none; background-color: rgba(0,0,0,0.6); }}
            .wiki-table th, .wiki-table td {{ padding: 8px 5px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
            .wiki-table tr:nth-child(odd) {{ background-color: transparent; }}
            .wiki-table tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.05); }}

            .custom-tooltip {{ position: relative; display: inline-block; cursor: help; }}
            .custom-tooltip.dotted {{ border-bottom: 1px dotted rgba(56, 189, 248, 0.5); }}
            .custom-tooltip .tooltip-text {{ visibility: hidden; width: max-content; background-color: rgba(15, 23, 42, 0.98); color: #fff; text-align: center; border-radius: 6px; padding: 6px 12px; position: absolute; z-index: 9999; bottom: 140%; left: 50%; transform: translateX(-50%); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 10px rgba(0,0,0,0.4); opacity: 0; transition: opacity 0.2s ease-in-out; font-size: 0.9em; font-weight: normal; font-family: 'Nunito', sans-serif; }}
            .custom-tooltip .tooltip-text::after {{ content: ""; position: absolute; top: 100%; left: 50%; margin-left: -5px; border-width: 5px; border-style: solid; border-color: rgba(255, 255, 255, 0.2) transparent transparent transparent; }}
            .custom-tooltip.align-left .tooltip-text {{ left: 0; transform: none; }}
            .custom-tooltip.align-left .tooltip-text::after {{ left: 10px; margin-left: 0; }}
            .custom-tooltip:hover .tooltip-text {{ visibility: visible; opacity: 1; }}

            .accordion-btn {{ background: rgba(30, 41, 59, 0.9); color: #cbd5e1; cursor: pointer; padding: 18px 25px; width: 100%; border: none; text-align: left; outline: none; font-size: 1.1em; font-weight: 600; border-radius: 8px; margin-bottom: 8px; transition: all 0.3s ease; border: 1px solid rgba(255,255,255,0.05); font-family: inherit; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.2); scroll-margin-top: 80px; }}
            .accordion-btn.active, .accordion-btn:hover {{ background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.3); color: #fff; }}
            .accordion-btn::after {{ content: '+'; font-size: 1.5em; color: #38bdf8; font-weight: bold; transition: 0.3s; }}
            .accordion-btn.active::after {{ content: '−'; transform: rotate(180deg); }}
            .accordion-content {{ padding: 0 25px; background: rgba(15, 23, 42, 0.6); max-height: 0; overflow: hidden; transition: max-height 0.3s ease-out; border-radius: 0 0 8px 8px; margin-top: -8px; margin-bottom: 15px; font-size: 1em; line-height: 1.6; color: #94a3b8; border-left: 2px solid #38bdf8; }}
            .accordion-content p, .accordion-content ul {{ padding: 15px 0; margin: 0; }}
            .accordion-content li {{ margin-bottom: 8px; }}

            .name-inline {{ display: inline-flex; align-items: center; flex-wrap: wrap; gap: 6px; }}
            .spenden-cell {{ display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
            .spenden-extra {{ line-height: 1; }}
            .legal-page {{ background: rgba(15, 23, 42, 0.72); padding: 24px 28px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); line-height: 1.7; color: #e2e8f0; }}
            .legal-page h2 {{ margin-top: 0; color: #f8fafc; font-size: 1.8em; }}
            .legal-page h3 {{ color: #38bdf8; margin-bottom: 8px; }}
            .legal-page a {{ color: #38bdf8; }}
            .legal-section {{ margin-top: 24px; }}
            .legal-section p {{ margin: 6px 0; }}
            .legal-warning {{ background: rgba(251, 191, 36, 0.12); border-left: 4px solid #fbbf24; color: #fde68a; padding: 14px 16px; border-radius: 8px; margin-bottom: 20px; }}
            .site-footer {{ margin-top: 40px; padding: 20px 0 10px 0; border-top: 1px solid rgba(255,255,255,0.08); text-align: center; color: #94a3b8; }}
            .footer-links {{ display: flex; justify-content: center; gap: 18px; flex-wrap: wrap; margin-bottom: 10px; }}
            .footer-link {{ color: #38bdf8; text-decoration: none; font-weight: 700; cursor: pointer; }}
            .footer-link:hover {{ color: #7dd3fc; }}

            @media (max-width: 768px) {{
                body {{ background-attachment: scroll; }}
                .container {{ max-width: 100%; padding: 12px; }}
                .header-container {{ padding: 28px 16px; }}
                .header-title {{ font-size: 1.6em; }}
                .tier-title {{ position: static; font-size: 1.15em; padding: 12px 0 10px 0; }}
                table:not(.radar-table), .wiki-table {{
                    width: 100%;
                    table-layout: auto;
                    border: none;
                    background: transparent;
                    margin-bottom: 18px;
                }}
                table:not(.radar-table) th, .wiki-table th {{ display: none; }}
                table:not(.radar-table) tbody, table:not(.radar-table) tr, table:not(.radar-table) td,
                .wiki-table tbody, .wiki-table tr, .wiki-table td {{
                    display: block;
                    width: 100%;
                }}
                table:not(.radar-table) tr, .wiki-table tr {{
                    background: rgba(15, 23, 42, 0.92) !important;
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 14px;
                    margin-bottom: 14px;
                    padding: 10px 12px;
                    box-shadow: 0 4px 14px rgba(0,0,0,0.18);
                }}
                table:not(.radar-table) td, .wiki-table td {{
                    border: none;
                    padding: 8px 0;
                    display: grid;
                    grid-template-columns: 110px 1fr;
                    gap: 12px;
                    align-items: center;
                    text-align: left !important;
                    font-size: 0.98em;
                }}
                table:not(.radar-table) td::before, .wiki-table td::before {{
                    color: #94a3b8;
                    font-weight: 700;
                    font-size: 0.86em;
                    text-transform: none;
                }}
                table:not(.radar-table) td:nth-child(1)::before, .wiki-table td:nth-child(1)::before {{ content: "Spieler"; }}
                table:not(.radar-table) td:nth-child(2)::before, .wiki-table td:nth-child(2)::before {{ content: "Check"; }}
                table:not(.radar-table) td:nth-child(3)::before, .wiki-table td:nth-child(3)::before {{ content: "Status"; }}
                table:not(.radar-table) td:nth-child(4)::before, .wiki-table td:nth-child(4)::before {{ content: "Dabei"; }}
                table:not(.radar-table) td:nth-child(5)::before, .wiki-table td:nth-child(5)::before {{ content: "Deck-Nutzung"; }}
                table:not(.radar-table) td:nth-child(6)::before, .wiki-table td:nth-child(6)::before {{ content: "Ø Fame/Deck"; }}
                table:not(.radar-table) td:nth-child(7)::before, .wiki-table td:nth-child(7)::before {{ content: "Fame gesamt"; }}
                table:not(.radar-table) td:nth-child(8)::before, .wiki-table td:nth-child(8)::before {{ content: "Trend"; }}
                table:not(.radar-table) td:nth-child(9)::before, .wiki-table td:nth-child(9)::before {{ content: "Spenden"; }}
                .wiki-table td {{ font-size: 0.92em; }}
                .name-col {{ font-size: 1.05em; }}
                .focus-pill {{ min-width: 0; width: fit-content; }}
                .trend-cell {{ font-size: 18px !important; }}
                .custom-tooltip .tooltip-text {{ max-width: 220px; width: max-content; white-space: normal; }}
                table:not(.radar-table) td:nth-child(7), .wiki-table td:nth-child(7),
                table:not(.radar-table) td:nth-child(9), .wiki-table td:nth-child(9) {{ white-space: nowrap; }}
                table:not(.radar-table) td:nth-child(7) > *, .wiki-table td:nth-child(7) > *,
                table:not(.radar-table) td:nth-child(9) > *, .wiki-table td:nth-child(9) > * {{ white-space: nowrap; }}
                table:not(.radar-table) td:nth-child(9) .custom-tooltip.dotted,
                .wiki-table td:nth-child(9) .custom-tooltip.dotted {{ border-bottom: none !important; }}
                .spenden-cell .custom-tooltip.dotted {{ border-bottom: none; }}
                .radar-table {{ width: 100%; table-layout: auto !important; font-size: 0.78em !important; }}
                .radar-table colgroup {{ display: none; }}
                .radar-table th {{ display: table-cell; position: static; box-shadow: none; font-size: 0.78em; padding: 6px 3px; }}
                .radar-table tbody {{ display: table-row-group; }}
                .radar-table tr {{ display: table-row; background: transparent !important; border: none; box-shadow: none; padding: 0; }}
                .radar-table td {{ display: table-cell; width: auto; padding: 8px 3px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: center !important; vertical-align: middle; word-break: break-word; }}
                .radar-table td:first-child {{ text-align: left !important; }}
                .radar-table td::before {{ content: none !important; }}
            }}
            @media (orientation: landscape) and (max-width: 1024px) {{
                body {{ background-attachment: scroll; }}
                .container {{ max-width: 100%; padding: 12px 14px; }}
                table:not(.radar-table) {{ table-layout: auto; font-size: 0.82em; }}
                table:not(.radar-table):not(.wiki-table) th {{
                    position: sticky;
                    top: 78px;
                    white-space: nowrap;
                    padding: 8px 5px;
                    font-size: 0.8em;
                }}
                td:not(.radar-table td):not(.wiki-table td) {{ padding: 8px 5px; }}
                .focus-pill {{ min-width: 72px; font-size: 0.72em; padding: 3px 7px; }}
                .name-col {{ font-size: 0.95em; }}
                .tier-title {{ font-size: 1.2em; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-container">
                <div class="lang-toggle" role="group" aria-label="Language">
                    <button type="button" data-lang="de" aria-pressed="true">DE</button>
                    <button type="button" data-lang="en" aria-pressed="false">EN</button>
                </div>
                <h1 class="header-title"><span onclick="toggleChat()" style="cursor: pointer;" title="Chat-Hilfe ein-/ausblenden">📊</span> {t('Clan-Auswertung', 'Clan Report')}: {clan_name} <br>
                <span class="header-date">{t('Stand', 'As of')}: {heute_datum}</span>
                <span class="header-mobile-tip">{t('📱 Tipp: Für die beste Übersicht am Handy bitte quer halten 🔄', '📱 Tip: For the best view on mobile, hold the device sideways 🔄')}</span>
                <span class="header-mobile-tip" style="margin-top: 2px;">{t('🔄 An Kriegstagen wird alle 10 Minuten eine neue Version erstellt – zum Anzeigen der neuesten Daten bitte die Seite manuell neu laden (F5).', '🔄 On war days a new version is generated every 10 minutes – to see the latest data please reload the page manually (F5).')}</span></h1>
            </div>

            <div class="tab-container">
                <button class="tab-btn active" onclick="openTab(event, 'Overview')">🏠 {t('Übersicht', 'Overview')}</button>
                <button class="tab-btn" onclick="openTab(event, 'Table')">📋 {t('Detail-Auswertung', 'Detailed Stats')}</button>
                <button class="tab-btn" onclick="openTab(event, 'Wiki')">📖 {t('Regeln & System', 'Rules & System')}</button>
                <button class="tab-btn" onclick="openTab(event, 'Decks')">🃏 {t('Top-Decks', 'Top Decks')}</button>
            </div>

            <div id="Overview" class="tab-content active">
                <div class="welcome-box">
                    <h2 class="welcome-title">{t('Willkommen bei der HAMBURG-Family! 🤝', 'Welcome to the HAMBURG Family! 🤝')}</h2>
                    <p>{t('Schön, dass du über unsere Clan-Info hierher gefunden hast. Egal ob du schon ewig dabei bist oder gerade erst überlegst, uns beizutreten: Schau dich in Ruhe um!', 'Great that you found us through our clan info. Whether you have been around forever or are just thinking about joining: take a look around!')}</p>
                    <p>{t('Ein starker Clan braucht aktive Mitglieder. Auf dieser Seite tracken wir jede Woche transparent unseren Erfolg im Clankrieg und unsere Spendenbereitschaft.', 'A strong clan needs active members. On this page we transparently track our clan war success and donation behavior every week.')}</p>
                    <p>{t('Wir sind eine entspannte, aber ehrgeizige Truppe. Bei uns zählt Verlässlichkeit mehr als reine Trophäen. Wenn du einen dauerhaft aktiven Clan suchst und deine 4 Decks verlässlich spielst, bist du bei uns genau <b>richtig</b>! 🛡️', 'We are a relaxed but ambitious crew. Reliability matters more here than raw trophies. If you are looking for a persistently active clan and you reliably play your 4 decks, you are in exactly the <b>right</b> place! 🛡️')}</p>
                </div>

                {hype_balken_html}

                {radar_html}
                {mahnwache_html}
                {clan_overview_html}
                {clan_ampel_html}
                {weekly_summary_html}
                {coach_html}

                <div class="dashboard">
                    <div class="card avg">
                        <h3>📈 {t('Clan-Durchschnitt', 'Clan Average')}</h3>
                        <h1>{clan_avg}%</h1>
                    </div>
                    <div class="card avg">
                        <h3>⚔️ {t('Clan-Ø Punkte', 'Clan Avg Points')}</h3>
                        <h1>{clan_avg_points_per_deck}</h1>
                    </div>
                    <div class="card top">
                        <h3>🏆 {t('Top 3 Performer', 'Top 3 Performers')}</h3>
                        <ul>{top_performers}</ul>
                    </div>
                    <div class="card spender">
                        <h3>🃏 {t('Top 3 Spender', 'Top 3 Donors')}</h3>
                        <ul>{top_spender}</ul>
                    </div>
                    <div class="card pusher">
                        <h3>🚀 {t('Trophäen-Pusher', 'Trophy Pushers')}</h3>
                        <ul>{pusher_html}</ul>
                    </div>
                    <div class="card hof">
                        <h3>📖 {t('Hall of Fame (Ewig)', 'Hall of Fame (All-Time)')}</h3>
                        <ul style="font-size: 0.95em;">
                            <li><b>{t('Spenden-Gott', 'Donation God')}:</b> {records['donations']['name']} ({records['donations']['val']})</li>
                            <li><b>{t('Max Trophäen', 'Max Trophies')}:</b> {records['trophies']['name']} ({records['trophies']['val']} 🏆)</li>
                            <li><b>{t('Mega-Comeback', 'Mega Comeback')}:</b> {records['delta']['name']} (+{records['delta']['val']}%)</li>
                        </ul>
                    </div>
                    <div class="card urlaub">
                        <h3>🏖️ {t('Aktuell im Urlaub', 'On Vacation')}</h3>
                        <ul style="font-size: 0.95em;">{urlaub_html}</ul>
                    </div>
                    <div class="card aufsteiger">
                        <h3>🚀 {t('Größte Aufsteiger', 'Top Risers')}</h3>
                        <ul>{top_aufsteiger}</ul>
                    </div>
                    <div class="card leecher">
                        <h3>📦 {t('Spenden auffällig', 'Notable Donations')}</h3>
                        <ul>{top_leecher}</ul>
                    </div>

                    <div id="admin-chat-container" style="display: none; width: 100%;">
                        <div class="card messenger">
                            <h3 style="color: #f1c40f; margin-bottom: 10px;">🎮 {t('Chat-Hilfe', 'Chat Helper')} ({total_msgs}-{t('Teiler', 'parts')})</h3>
                            <p style="font-size: 0.9em; color: #cbd5e1; margin-top: 0; margin-bottom: 15px;">{t('Klicke oben auf das 📊-Symbol, um diese Hilfe ein- oder auszublenden. Wähle den passenden Tonfall und kopiere dann die', 'Click the 📊 symbol above to toggle this helper. Pick the matching tone, then copy the')} {total_msgs} {t('Texte nacheinander in den Chat.', 'texts one by one into the chat.')}</p>
                            {chat_boxes_html}
                        </div>
                    </div>

                </div>
            </div>

            <div id="Table" class="tab-content">
                <div style="background: rgba(30, 41, 59, 0.8); padding: 20px; border-radius: 8px; margin-bottom: 25px; font-size: 0.95em; border: 1px solid rgba(255,255,255,0.05); box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                    <h4 style="margin-top: 0; color: #38bdf8; margin-bottom: 5px;">📌 {t('Schnelle Symbol-Legende:', 'Quick Symbol Legend:')}</h4>
                    <p style="margin: 0 0 15px 0; font-size: 0.9em; color: #94a3b8; font-style: italic;">{t('Weitere Infos unter', 'More info under')} <b>📖 {t('Regeln & System', 'Rules & System')}</b>.</p>
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; color: #cbd5e1;">
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🌱 {t('Welpenschutz', 'Pup Protection')}:</b> {t('Erster Clankrieg geschützt – danach volle Bewertung', 'First clan war protected – full scoring afterwards')}</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>❌ 1/1:</b> {t('Interner Hinweis bei Inaktivität → sofortige Maßnahme', 'Internal flag on inactivity → immediate action')}</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>📦 {t('Spenden auffällig', 'Notable donations')}:</b> {t('Fordert, spendet aber 0', 'Requests but donates 0')}</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>💤 {t('Spenden inaktiv', 'Donations inactive')}:</b> {t('Spendet 0, fordert 0', 'Donates 0, requests 0')}</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>⚠️ {t('Ø Punkte', 'Avg points')}:</b> {t('Auffällig niedriger Punkteschnitt pro Deck', 'Notably low points-per-deck average')} (&lt;130)</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🔥 Streak:</b> {t('Mehrere Wochen 100% Score', 'Multiple weeks at 100% score')}</div>
                    </div>
                </div>

                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 30px; color: #ffffff;">📋 {t('Detail-Auswertung', 'Detailed Stats')}</h2>
                {table_html}
            </div>

            <div id="Wiki" class="tab-content">
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 30px; color: #8b5cf6;">📖 {t('Clan-Wiki: Regeln & System', 'Clan Wiki: Rules & System')}</h2>

                <button class="accordion-btn">📬 {t('Die Montags-Auswertung per E-Mail', 'The Monday Report by Email')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Willst du diese Auswertung jeden Montag ganz bequem und automatisch in dein Postfach bekommen?</span><span class="i18n-en">Want this report delivered to your inbox every Monday, automatically?</span></p>
                    <ul>
                        <li><b><span class="i18n-de">Anmelden:</span><span class="i18n-en">Subscribe:</span></b> <span class="i18n-de">Schreib einfach eine kurze E-Mail mit deinem In-Game-Namen an:</span><span class="i18n-en">Send a short email with your in-game name to:</span> <b>strike2005-Hamburg_Royal@yahoo.com</b>. <span class="i18n-de">Mit deiner Anmeldung erklärst du dich damit einverstanden, dass wir deine E-Mail-Adresse zum Versand der wöchentlichen Clan-Auswertung speichern und verwenden.</span><span class="i18n-en">By subscribing you agree that we store and use your email address to send the weekly clan report.</span></li>
                        <li>🔒 <b><span class="i18n-de">Datenschutz:</span><span class="i18n-en">Privacy:</span></b> <span class="i18n-de">Deine E-Mail-Adresse wird ausschließlich für den Versand der Auswertung genutzt und nicht an Dritte weitergegeben. Der Versand erfolgt ausschließlich per <b>Blindkopie (BCC)</b>, sodass keine anderen Empfänger sichtbar sind.</span><span class="i18n-en">Your email is used solely for sending the report and never shared with third parties. Delivery is by <b>BCC</b> only, so other recipients stay hidden.</span></li>
                        <li><b><span class="i18n-de">Abmelden:</span><span class="i18n-en">Unsubscribe:</span></b> <span class="i18n-de">Eine kurze Nachricht reicht, und deine E-Mail-Adresse wird aus dem Verteiler entfernt.</span><span class="i18n-en">A short note is enough, and your email is removed from the list.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">⚖️ {t('Regeln bei Inaktivität (❌)', 'Rules on Inactivity (❌)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Wer sich nicht abmeldet und im Clankrieg zu wenig beiträgt (zu wenig Kriege dabei oder Decks nicht gespielt), erhält sofort einen internen Hinweis (❌). Bereits ein einzelner Hinweis löst Konsequenzen aus — kein langer Vorlauf, klare Ansage.</span><span class="i18n-en">Anyone who doesn't register absence and contributes too little in the Clan War (too few wars attended or decks not played) immediately receives an internal flag (❌). Even a single flag triggers consequences — no long run-up, clear message.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler A </span><span class='i18n-en'>Player A </span><span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 1/1</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>95/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>179</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>14.320</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>303</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler B </span><span class='i18n-en'>Player B </span><span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 1/1</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>4/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>28/64</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>100</span> ⚠️<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>3.200</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> 💤</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>Die zweite Chance (Degradierung):</b> Wer als <i>Anführer</i>, <i>Vize</i> oder <i>Ältester</i> einen internen Hinweis ansammelt, wird nicht sofort entfernt, sondern genau <b>eine Rang-Stufe tiefer</b> gesetzt und bekommt so eine Bewährungschance.</span><span class="i18n-en"><b>The second chance (demotion):</b> Anyone with a <i>Leader</i>, <i>Co-leader</i> or <i>Elder</i> role who accumulates an internal flag is not immediately removed, but is demoted exactly <b>one rank</b> as a probation chance.</span></li>
                        <li><span class="i18n-de"><b>Die letzte Stufe:</b> Wenn ein normales <i>Mitglied</i> (wie <b>Spieler B</b> oben) einen internen Hinweis erhält, trennen wir uns. So bleibt Platz für verlässliche, aktive Spieler.</span><span class="i18n-en"><b>The final step:</b> If a regular <i>Member</i> (like <b>Player B</b> above) receives an internal flag, we part ways. This keeps room for reliable, active players.</span></li>
                        <li><span class="i18n-de"><b>Wieder ins Gleichgewicht kommen:</b> Wer nach einem internen Hinweis wieder anzieht und in der Folgewoche aktiv teilnimmt und Decks spielt, baut diesen Eintrag automatisch wieder ab.</span><span class="i18n-en"><b>Getting back on track:</b> Anyone who picks up again after an internal flag and actively participates and plays their decks the following week automatically clears the flag.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🎯 {t('Dabei & Welpenschutz (Zuverlässigkeit)', 'Attendance & Pup Protection (Reliability)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Die <b>Dabei</b>-Spalte zeigt auf einen Blick, wie zuverlässig du bist — in wie vielen der verfügbaren Kriege du aktiv dabei warst.</span><span class="i18n-en">The <b>Present</b> column shows at a glance how reliable you are — in how many of the available wars you were actively participating.</span></p>
                    <p><span class="i18n-de">Die Zahl <b>X/Y</b> bedeutet: Du warst in X von Y Kriegen aktiv dabei.</span><span class="i18n-en">The number <b>X/Y</b> means: You were actively present in X out of Y wars.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Anwesenheit:</b> In wie vielen Kriegen seit deinem Beitritt warst du aktiv dabei? <br><span style="color:#94a3b8; font-size:0.9em;">Beispiel: 8/10 bedeutet du hast 8 von 10 möglichen Kriegen mitgespielt. Die Kriege vor deinem Beitritt zählen nie gegen dich.</span></span><span class="i18n-en"><b>Attendance:</b> In how many wars since you joined were you actively present? <br><span style="color:#94a3b8; font-size:0.9em;">Example: 8/10 means you participated in 8 out of 10 possible wars. Wars before you joined never count against you.</span></span></li>
                        <li><span class="i18n-de"><b>Farben:</b> 🟢 ≥ 80% Anwesenheit, 🟡 ≥ 50%, 🔴 unter 50%, 🔵 Welpenschutz (nur erster Clankrieg)</span><span class="i18n-en"><b>Colors:</b> 🟢 ≥ 80% attendance, 🟡 ≥ 50%, 🔴 below 50%, 🔵 Pup protection (first clan war only)</span></li>
                    </ul>
                    <p style="color:#94a3b8; font-size:0.9em;"><span class="i18n-de">Im Hintergrund läuft ein gewichtetes Bewertungs-System aus drei Faktoren: <b>50% Deck-Nutzung</b> (hast du alle Decks gespielt?), <b>30% Dabei-Quote</b> (warst du in den Kriegen dabei?) und <b>20% Qualität</b> (wie viele Punkte pro Deck?). Dieser Score ist die Grundlage für Strikes und Beförderungen.</span><span class="i18n-en">Behind the scenes, a weighted scoring system runs on three factors: <b>50% Deck Usage</b> (did you play all your decks?), <b>30% Attendance Rate</b> (were you present in the wars?) and <b>20% Quality</b> (how many points per deck?). This score is the basis for strikes and promotions.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler C </span><span class='i18n-en'>Player C </span><span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥 4</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'><span class='i18n-de'>🛡️ stabil</span><span class='i18n-en'>🛡️ stable</span></span></td><td><span class='i18n-de'>Vize</span><span class='i18n-en'>Co-leader</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>160/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>131</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>10.480</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>146</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler D </span><span class='i18n-en'>Player D </span><span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#60a5fa;'>1/10</span><br><span style='font-size:0.75em; color:#60a5fa;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>16/16</span><br><span style='font-size:0.75em; color:#60a5fa;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>200</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>1.600</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>10/10 + Streak 🔥:</b> Perfekt dabei und alle Decks gespielt. Wer das mehrere Wochen in Folge schafft, bekommt das Flammen-Symbol (wie <b>Spieler C</b> oben mit 4 Wochen am Stück!).</span><span class="i18n-en"><b>10/10 + Streak 🔥:</b> Perfectly present and all decks played. Anyone who manages this for several weeks in a row gets the flame symbol (like <b>Player C</b> above with 4 weeks in a row!).</span></li>
                        <li><span class="i18n-de"><b>8/10 🟢:</b> Zwei Kriege verpasst – trotzdem guter Wert, solange die Ø Fame/Deck stimmt.</span><span class="i18n-en"><b>8/10 🟢:</b> Two wars missed — still a good value as long as the Avg Fame/Deck is decent.</span></li>
                        <li><span class="i18n-de"><b>5/10 🟡:</b> Genau die Hälfte dabei – mittelmäßige Anwesenheit, hier ist Luft nach oben.</span><span class="i18n-en"><b>5/10 🟡:</b> Exactly half present — mediocre attendance, room for improvement here.</span></li>
                        <li><span class="i18n-de"><b>Welpenschutz (🌱):</b> Dein erster Clankrieg (wie <b>Spieler D</b> oben) ist geschützt — keine Strafen, keine Bewertung. Ab dem zweiten Krieg bist du vollwertiges Mitglied und wirst wie alle anderen bewertet.</span><span class="i18n-en"><b>Pup protection (🌱):</b> Your first clan war (like <b>Player D</b> above) is protected — no penalties, no scoring. From the second war onwards you are a full member and rated like everyone else.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🃏 {t('Deck-Nutzung (Dein größter Hebel)', 'Deck Usage (Your Biggest Lever)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Die <b>Deck-Nutzung</b>-Spalte zeigt, wie viele deiner möglichen Kriegs-Decks du tatsächlich gespielt hast — das ist der <b>wichtigste Einzelfaktor</b> im Bewertungs-System (50% des Scores).</span><span class="i18n-en">The <b>Deck Usage</b> column shows how many of your available war decks you actually played — this is the <b>most important single factor</b> in the scoring system (50% of the score).</span></p>
                    <p><span class="i18n-de">Die Zahl <b>X/Y</b> bedeutet: Du hast X von maximal Y Decks gespielt. <br><span style="color:#94a3b8; font-size:0.9em;">Y = Anzahl der Kriege, in denen du dabei warst × 16 (= 4 Decks pro Tag × 4 Kriegstage).</span></span><span class="i18n-en">The number <b>X/Y</b> means: You played X out of a maximum of Y decks. <br><span style="color:#94a3b8; font-size:0.9em;">Y = number of wars you participated in × 16 (= 4 decks per day × 4 war days).</span></span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Farben:</b> 🟢 ≥ 90% gespielt, 🟡 ≥ 70%, 🔴 unter 70%</span><span class="i18n-en"><b>Colors:</b> 🟢 ≥ 90% played, 🟡 ≥ 70%, 🔴 below 70%</span></li>
                        <li><span class="i18n-de"><b>Warum so wichtig?</b> Jedes nicht gespielte Deck kostet den Clan direkt Medaillen. Wer zuverlässig alle Decks einsetzt, ist für das Team wertvoller als jemand, der zwar hervorragende Einzelkämpfe liefert, aber oft Decks stehen lässt.</span><span class="i18n-en"><b>Why so important?</b> Every unplayed deck directly costs the clan medals. Anyone who reliably plays all decks is more valuable to the team than someone who delivers outstanding battles but often leaves decks unused.</span></li>
                        <li><span class="i18n-de"><b>Beispiel:</b> 160/160 🟢 = Alle Decks in allen Kriegen gespielt. Perfekt!</span><span class="i18n-en"><b>Example:</b> 160/160 🟢 = All decks played in all wars. Perfect!</span></li>
                        <li><span class="i18n-de"><b>Beispiel:</b> 95/160 🔴 = Trotz voller Anwesenheit wurden viele Decks nicht gespielt — hier liegt der größte Verbesserungshebel.</span><span class="i18n-en"><b>Example:</b> 95/160 🔴 = Despite full attendance many decks were not played — this is where the biggest room for improvement lies.</span></li>
                    </ul>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler X</span><span class='i18n-en'>Player X</span></td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'><span class='i18n-de'>⭐ stark</span><span class='i18n-en'>⭐ strong</span></span></td><td><span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>160/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>185</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>14.800</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>180</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler Y</span><span class='i18n-en'>Player Y</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>95/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>175</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>11.875</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟡🟡🔴🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>60</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><i>Spieler X</i>: Alle 160 Decks gespielt — das ist der Idealfall. Trotz nicht außergewöhnlichem Ø Fame/Deck ist dieser Spieler ein echter Rückhalt für den Clan.</span><span class="i18n-en"><i>Player X</i>: All 160 decks played — that is the ideal case. Despite a not exceptional Avg Fame/Deck, this player is a real backbone for the clan.</span></li>
                        <li><span class="i18n-de"><i>Spieler Y</i>: Immer dabei, aber 65 Decks liegen gelassen. Trotz guter Kampfqualität (175 Punkte/Deck) kostet das den Score deutlich — weil jedes ungespielte Deck dem Clan fehlt.</span><span class="i18n-en"><i>Player Y</i>: Always present, but 65 decks left unplayed. Despite good battle quality (175 points/deck) this significantly costs the score — because every unplayed deck is missing for the clan.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🟢🟡🔴 {t('Der Trend (Deine Konstanz)', 'The Trend (Your Consistency)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Die Ampel-Punkte zeigen deine Zuverlässigkeit der letzten <b>6 Wochen</b> auf einen Blick. Jeder Punkt steht für eine Woche, wobei der <b>Punkt ganz rechts die aktuellste Auswertung</b> ist.</span><span class="i18n-en">The traffic light dots show your reliability over the last <b>6 weeks</b> at a glance. Each dot represents a week, with the <b>rightmost dot being the most recent evaluation</b>.</span></p>
                    <p style="color:#94a3b8; font-size:0.9em;"><span class="i18n-de">6 Wochen sind bewusst gewählt: Das Strike-System arbeitet über mehrere Wochen – der Trend soll den vollen Kontext zeigen, über den Strikes entstehen oder sich abbauen.</span><span class="i18n-en">6 weeks is a deliberate choice: the strike system works over several weeks — the trend is meant to show the full context over which strikes develop or clear up.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler E</span><span class='i18n-en'>Player E</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>8/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>100/128</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>180</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>11.520</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟡🟡🟡🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>150</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler F</span><span class='i18n-en'>Player F</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'><span class='i18n-de'>🛡️ stabil</span><span class='i18n-en'>🛡️ stable</span></span></td><td><span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>6/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>80/96</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>7.680</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴🔴🟡🟢🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>200</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>🟢 Grün (Zuverlässig):</b> Hohe Anwesenheit und Decks gut ausgespielt.</span><span class="i18n-en"><b>🟢 Green (Reliable):</b> High attendance and decks well played.</span></li>
                        <li><span class="i18n-de"><b>🟡 Gelb (Mittelfeld):</b> Akzeptable Teilnahme, aber noch Luft nach oben.</span><span class="i18n-en"><b>🟡 Yellow (Mid-range):</b> Acceptable participation, but still room to grow.</span></li>
                        <li><span class="i18n-de"><b>🔴 Rot (Kritisch):</b> Zu wenig Anwesenheit oder zu viele liegen gelassene Decks.</span><span class="i18n-en"><b>🔴 Red (Critical):</b> Too little attendance or too many unplayed decks.</span></li>
                        <li><span class="i18n-de"><i>Beispiel Spieler E:</i> War früher stark, aber die letzten vier Wochen gehen zunehmend nach unten – das ist genau der Kontext, den das Strike-System benötigt.</span><span class="i18n-en"><i>Example Player E:</i> Was strong before, but the last four weeks are increasingly going downwards — this is exactly the context the strike system needs.</span></li>
                        <li><span class="i18n-de"><i>Beispiel Spieler F:</i> Hat sich nach einem schwachen Start klar erholt. Drei grüne Wochen in Folge rechts zeigen, dass der Trend stimmt.</span><span class="i18n-en"><i>Example Player F:</i> Has clearly recovered after a weak start. Three consecutive green weeks on the right show that the trend is correct.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🏷️ {t('Check-Spalte (Orientierung)', 'Check Column (Orientation)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Die <b>Check</b>-Spalte ist eine kurze, leicht lesbare Orientierung auf einen Blick. Sie ersetzt keine Zahlen, sondern hilft nur dabei, Spieler schneller einzuordnen.</span><span class="i18n-en">The <b>Check</b> column is a short, easily readable orientation at a glance. It doesn't replace numbers, but only helps to classify players more quickly.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler P</span><span class='i18n-en'>Player P</span></td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'><span class='i18n-de'>⭐ stark</span><span class='i18n-en'>⭐ strong</span></span></td><td><span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>160/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>182</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>14.560</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>220</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler Q</span><span class='i18n-en'>Player Q</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'><span class='i18n-de'>🛡️ stabil</span><span class='i18n-en'>🛡️ stable</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>9/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>130/144</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>142</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>10.224</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟡🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>95</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler R</span><span class='i18n-en'>Player R</span></td><td><span class='focus-pill' style='background:#94a3b822; color:#94a3b8; border:1px solid #94a3b855;'><span class='i18n-de'>🙂 solide</span><span class='i18n-en'>🙂 solid</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>7/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>95/112</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>150</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>8.400</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟡🟡🟡🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>70</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler S</span><span class='i18n-en'>Player S</span></td><td><span class='focus-pill' style='background:#ef444422; color:#ef4444; border:1px solid #ef444455;'><span class='i18n-de'>👀 auffällig</span><span class='i18n-en'>👀 watch</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>9/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>138/144</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>102</span> ⚠️<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>7.344</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟡🟡🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>40</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler T</span><span class='i18n-en'>Player T</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>4/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>40/64</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>140</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>4.480</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴🔴🟡🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>30</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler U </span><span class='i18n-en'>Player U </span><span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#60a5fa;'>2/10</span><br><span style='font-size:0.75em; color:#60a5fa;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>32/32</span><br><span style='font-size:0.75em; color:#60a5fa;'><span class='i18n-de'>neu dabei</span><span class='i18n-en'>newcomer</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>170</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>2.720</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>35</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>⭐ stark:</b> Sehr verlässlich und gleichzeitig stark bei den Punkten pro Deck.</span><span class="i18n-en"><b>⭐ strong:</b> Very reliable and at the same time strong in points per deck.</span></li>
                        <li><span class="i18n-de"><b>🛡️ stabil:</b> Gute, solide Leistung ohne große Schwächen. Genau solche Spieler tragen einen Clan langfristig.</span><span class="i18n-en"><b>🛡️ stable:</b> Good, solid performance without major weaknesses. Exactly these players carry a clan in the long run.</span></li>
                        <li><span class="i18n-de"><b>🙂 solide:</b> Nicht auffällig schlecht, aber auch noch nicht ganz oben. Hier ist noch Luft nach oben.</span><span class="i18n-en"><b>🙂 solid:</b> Not noticeably bad, but not quite at the top either. There is still room for improvement.</span></li>
                        <li><span class="i18n-de"><b>👀 auffällig:</b> Die Teilnahme kann okay sein, aber die Punkte pro Deck fallen gerade eher schwach aus. Hier lohnt ein genauerer Blick.</span><span class="i18n-en"><b>👀 watch:</b> Participation may be okay, but the points per deck are currently rather weak. A closer look is worthwhile here.</span></li>
                        <li><span class="i18n-de"><b>⚠️ ausbaufähig:</b> Die Teilnahme ist im Moment klar verbesserungswürdig. Diese Spieler liegen beim Score schon im unteren Bereich.</span><span class="i18n-en"><b>⚠️ room to grow:</b> Participation is clearly in need of improvement at the moment. These players are already in the lower range of the score.</span></li>
                        <li><span class="i18n-de"><b>neu dabei:</b> Spieler befindet sich im ersten Clankrieg (Welpenschutz). Ab dem zweiten Krieg gilt die volle Bewertung.</span><span class="i18n-en"><b>newcomer:</b> Player is in their first clan war (pup protection). From the second war onwards the full scoring applies.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ {t('Ø Punkte (Der Qualitäts-Check)', 'Avg Points (The Quality Check)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Hier schauen wir, wie effektiv du deine Decks einsetzt. Das System teilt deine gesammelten Kriegspunkte durch die Anzahl deiner gespielten Decks – und das als <b>rollierender Schnitt über die letzten 3–4 Kriege</b>.</span><span class="i18n-en">Here we look at how effectively you use your decks. The system divides your total war points by the number of decks you played — as a <b>rolling average over the last 3–4 wars</b>.</span></p>
                    <p style="color:#94a3b8; font-size:0.9em;"><span class="i18n-de">Warum mehrere Kriege? Ein einzelner Krieg kann durch starke oder schwache Gegner verzerrt sein. Der Schnitt über 3–4 Wochen gibt ein faireres, stabileres Bild deiner tatsächlichen Kampfqualität.</span><span class="i18n-en">Why multiple wars? A single war can be skewed by strong or weak opponents. The average over 3–4 weeks gives a fairer, more stable picture of your actual battle quality.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler J </span><span class='i18n-en'>Player J </span><span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'><span class='i18n-de'>⚠️ ausbaufähig</span><span class='i18n-en'>⚠️ room to grow</span></span></td><td><span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>8/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>125/128</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#ef4444;'>100</span> ⚠️<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>6.400</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🔴🔴🔴🔴🔴🔴</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>72</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>Orientierungswerte:</b> Ein normaler Spieler mit einem Mix aus Siegen und Niederlagen landet bei etwa <b>162 Punkten pro Deck</b>. Wer fast alle Kämpfe gewinnt kommt auf bis zu <b>225</b>. Wer fast alles verliert landet bei etwa <b>112</b>.</span><span class="i18n-en"><b>Reference values:</b> A normal player with a mix of wins and losses lands at around <b>162 points per deck</b>. Those who win almost all battles reach up to <b>225</b>. Those who lose almost everything land at around <b>112</b>.</span></li>
                        <li><span class="i18n-de"><b>⚠️ Auffälliger Bereich (&lt; 130 Punkte):</b> Wer dauerhaft unter 130 liegt, kämpft deutlich schlechter als ein normaler Spieler. Häufige Ursachen: Bootsangriffe statt normaler Kämpfe, oder konsequent schlechte Decks. Duelle sind besonders lukrativ – ein 2-0 Duellsieg bringt ~250 Punkte pro Spiel.</span><span class="i18n-en"><b>⚠️ Notable range (&lt; 130 points):</b> Anyone consistently below 130 fights significantly worse than a normal player. Common causes: boat attacks instead of regular battles, or consistently poor decks. Duels are particularly lucrative — a 2-0 duel win gives ~250 points per game.</span></li>
                        <li><span class="i18n-de"><b>Ein einzelner schwacher Krieg reicht nicht für eine Warnung:</b> Der Schnitt läuft über die letzten 3–4 Kriege. Ausreißer durch Pech beim Matchmaking werden so herausgefiltert.</span><span class="i18n-en"><b>A single weak war is not enough for a warning:</b> The average runs over the last 3–4 wars. Outliers due to bad matchmaking luck are filtered out this way.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">📊 {t('Clan-Durchschnitt & ⚔️ Clan-Ø Punkte', 'Clan Average & ⚔️ Clan Avg Points')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">In der Übersicht seht ihr zwei Clan-Werte, die absichtlich zwei verschiedene Fragen beantworten: <b>Wie zuverlässig spielen wir unsere Decks aus?</b> und <b>wie stark kämpfen wir pro Deck?</b></span><span class="i18n-en">In the overview you see two clan values that intentionally answer two different questions: <b>How reliably do we play our decks?</b> and <b>how strongly do we fight per deck?</b></span></p>
                    <ul>
                        <li><span class="i18n-de"><b>📈 Clan-Durchschnitt:</b> Zeigt den Durchschnitt des gewichteten Scores aller aktiven Mitglieder (50% Deck-Nutzung, 30% Anwesenheit, 20% Kampfqualität). Beispiel: <b>90%+</b> ist stark, weil fast alle ihre Decks sauber spielen. Ein Wert um <b>60%</b> oder darunter zeigt, dass dem Clan viele Decks fehlen.</span><span class="i18n-en"><b>📈 Clan Average:</b> Shows the average of the weighted score of all active members (50% deck usage, 30% attendance, 20% battle quality). Example: <b>90%+</b> is strong because almost everyone plays their decks cleanly. A value around <b>60%</b> or below shows that the clan is missing many decks.</span></li>
                        <li><span class="i18n-de"><b>⚔️ Clan-Ø Punkte:</b> Dieser Wert teilt die <b>gesamten aktuellen Kriegspunkte</b> des Clans durch die <b>gesamt gespielten Decks</b> der aktiven Mitglieder. Er zeigt also, wie stark der Clan pro eingesetztem Deck kämpft. Beispiel: Ein Wert von <b>185+</b> ist stark (viele Siege). <b>162</b> ist ein solider Durchschnitt. Werte unter <b>130</b> sind auffällig schwach und deuten auf Bootsangriffe oder viele Niederlagen hin.</span><span class="i18n-en"><b>⚔️ Clan Avg Points:</b> This value divides the <b>total current war points</b> of the clan by the <b>total decks played</b> by active members. It shows how strongly the clan fights per deployed deck. Example: A value of <b>185+</b> is strong (many wins). <b>162</b> is a solid average. Values below <b>130</b> are notably weak and indicate boat attacks or many losses.</span></li>
                        <li><span class="i18n-de"><b>Verteilungsampel (🟢 🟡 🔴):</b> Direkt unter dem Clan-Ø Punkte-Wert seht ihr wie viele aktive Spieler in welchem Bereich liegen: 🟢 stark (≥ 162 Punkte/Deck), 🟡 solide (130–161), 🔴 auffällig (&lt; 130). So sieht man auf einen Blick, ob ein niedriger Clan-Wert an wenigen Ausreißern oder am gesamten Clan liegt.</span><span class="i18n-en"><b>Distribution traffic light (🟢 🟡 🔴):</b> Directly below the Clan Avg Points value you can see how many active players are in which range: 🟢 strong (≥ 162 points/deck), 🟡 solid (130–161), 🔴 notable (&lt; 130). This shows at a glance whether a low clan value is due to a few outliers or the entire clan.</span></li>
                        <li><span class="i18n-de"><b>Trend-Pfeil (▲ / ▼):</b> Zeigt die Veränderung des Clan-Ø Punkte-Werts gegenüber der Vorwoche. Erscheint ab dem zweiten Weekly Run nach einem Update.</span><span class="i18n-en"><b>Trend arrow (▲ / ▼):</b> Shows the change of the Clan Avg Points value compared to the previous week. Appears from the second weekly run after an update.</span></li>
                        <li><span class="i18n-de"><b>Unterschied:</b> Ein hoher Clan-Durchschnitt heißt, dass viele Leute ihre Decks spielen. Ein hoher Clan-Ø Punkte heißt, dass diese Decks auch qualitativ gute Punkte holen. Beides zusammen ist ideal.</span><span class="i18n-en"><b>Difference:</b> A high Clan Average means that many people play their decks. A high Clan Avg Points means that these decks also score good quality points. Both together is ideal.</span></li>
                        <li><span class="i18n-de"><b>Die Urlaubs-Regel:</b> Wenn jemand offiziell im Urlaub (🏖️) ist und pausiert, wird er aus beiden Clan-Werten komplett herausgenommen.</span><span class="i18n-en"><b>The vacation rule:</b> When someone is officially on vacation (🏖️) and pausing, they are completely removed from both clan values.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🃏 {t('Spenden-Verhalten (Teamplay)', 'Donation Behavior (Teamplay)')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Ein starker Clan hilft sich gegenseitig beim Leveln der Karten. Deshalb schauen wir auch auf das Spendenverhalten im Clan.</span><span class="i18n-en">A strong clan helps each other leveling up cards. That is why we also look at donation behavior in the clan.</span></p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th><th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th><th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th><th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th><th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th><th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th><th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th><th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th><th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler K</span><span class='i18n-en'>Player K</span></td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'><span class='i18n-de'>⭐ stark</span><span class='i18n-en'>⭐ strong</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>10/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>160/160</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#10b981;'>200</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>16.000</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>📦</span></td></tr>
                            <tr><td class='name-col'><span class='i18n-de'>Spieler L</span><span class='i18n-en'>Player L</span></td><td><span class='focus-pill' style='background:#94a3b822; color:#94a3b8; border:1px solid #94a3b855;'><span class='i18n-de'>🙂 solide</span><span class='i18n-en'>🙂 solid</span></span></td><td><span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>5/10</span><br><span style='font-size:0.75em; color:#64748b;'><span class="i18n-de">Kriege aktiv</span><span class="i18n-en">Wars active</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>72/80</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span></td><td style='white-space:nowrap;'><span style='font-weight:800; color:#fbbf24;'>150</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span></td><td style='white-space:nowrap;'><span style='font-weight:700; color:#c4b5fd;'>6.000</span><br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span></td><td class='trend-cell'>🟡🟡🟡🟡</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>💤</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><span class="i18n-de"><b>📦 Spenden auffällig:</b> Jemand fordert regelmäßig Karten an, spendet aber selbst nichts zurück.</span><span class="i18n-en"><b>📦 Notable donations:</b> Someone regularly requests cards but donates nothing back.</span></li>
                        <li><span class="i18n-de"><b>💤 Spenden inaktiv:</b> Jemand spendet nicht und fordert auch nichts an.</span><span class="i18n-en"><b>💤 Donations inactive:</b> Someone does not donate and does not request anything either.</span></li>
                        <li><span class="i18n-de"><b>Wichtig:</b> Diese Hinweise sollen nicht bloßstellen, sondern zeigen, wo im Clan noch etwas mehr Mitziehen helfen würde.</span><span class="i18n-en"><b>Important:</b> These notes are not meant to expose anyone, but to show where a little more participation in the clan would help.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">🔧 {t('Tools', 'Tools')}</button>
                <div class="accordion-content">
                    <ul>
                        <li><b><a href="https://deckai.app/" target="_blank" style="color: #38bdf8;">DeckAI</a></b> — <span class="i18n-de">Analyse- und Deckbau-Tool für Clash Royale. Hilft beim Bewerten von Decks, zeigt Matchups, schlägt Kartenwechsel vor, erstelle einen optimierten Satz Clan-War-Decks mit deinen besten Karten und Vorlieben (Beatdown, Cycle, Control, Bridge Spam, Siege, Bait) und gibt Hinweise zu sinnvollen Upgrades. Nützlich für Spieler, die ihre Decks verbessern und gezielter für Ladder, Duelle und Clan-Krieg bauen wollen.</span><span class="i18n-en">Analysis and deck-building tool for Clash Royale. Helps evaluate decks, shows matchups, suggests card swaps, creates an optimized set of Clan War decks with your best cards and preferences (Beatdown, Cycle, Control, Bridge Spam, Siege, Bait) and gives hints for useful upgrades. Useful for players who want to improve their decks and build more purposefully for Ladder, Duels and Clan War.</span></li>
                        <li><b><a href="https://www.noff.gg/clash-royale/" target="_blank" style="color: #38bdf8;">NOFF</a></b> — <span class="i18n-de">In der Art wie DeckAI, nur in Englisch.</span><span class="i18n-en">Similar to DeckAI, but in English.</span></li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ {t('Clash Royale Angriffsarten', 'Clash Royale Attack Types')}</button>
                <div class="accordion-content">
                    <p><span class="i18n-de">Diese Decks repräsentieren die Kerntaktiken der jeweiligen Angriffsarten. Je nach aktueller „Meta" können einzelne Karten variieren, aber das strategische Prinzip bleibt gleich.</span><span class="i18n-en">These decks represent the core tactics of the respective attack types. Depending on the current "meta", individual cards may vary, but the strategic principle remains the same.</span></p>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">1. Beatdown (Der Dampfwalzen-Angriff)</span><span class="i18n-en">1. Beatdown (The Steamroller Push)</span></h4>
                    <p><span class="i18n-de">Das Ziel ist ein massiver Angriff mit einem Tank an der Spitze, der kaum aufzuhalten ist.</span><span class="i18n-en">The goal is a massive attack with a tank at the front that is nearly unstoppable.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Ein Tank mit hohen Trefferpunkten wird hinten platziert, um Elixier für Unterstützungstruppen zu sammeln.</span><span class="i18n-en"><b>Approach:</b> A tank with high hit points is placed at the back to collect elixir for support troops.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (Golem Night Witch):</b> Golem, Nachthexe, Baby-Drache, Blitzeinschlag, Der Stamm (Log), Tornado, Holzfäller, Megaminion.</span><span class="i18n-en"><b>Example deck (Golem Night Witch):</b> Golem, Night Witch, Baby Dragon, Lightning, The Log, Tornado, Lumberjack, Mega Minion.</span>
                        <br><a href="https://royaleapi.com/decks/stats/golem,night-witch,baby-dragon,lightning,the-log,tornado,lumberjack,mega-minion" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">2. Cycle / Chip Damage (Die Nadelstiche)</span><span class="i18n-en">2. Cycle / Chip Damage (The Pinpricks)</span></h4>
                    <p><span class="i18n-de">Man versucht, den gegnerischen Turm durch viele schnelle, kostengünstige Angriffe langsam zu zermürben.</span><span class="i18n-en">The goal is to slowly wear down the opponent's tower through many quick, cheap attacks.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Schnelle Kartenrotation, um die eigene Win-Condition öfter auszuspielen, als der Gegner kontern kann.</span><span class="i18n-en"><b>Approach:</b> Fast card rotation to play your win condition more often than the opponent can counter.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (2.6 Hog Cycle):</b> Hog Rider, Eisgeist, Skelette, Eis-Golem, Kanone, Feuerball, Der Stamm (Log), Musketierin.</span><span class="i18n-en"><b>Example deck (2.6 Hog Cycle):</b> Hog Rider, Ice Spirit, Skeletons, Ice Golem, Cannon, Fireball, The Log, Musketeer.</span>
                        <br><a href="https://royaleapi.com/decks/stats/hog-rider,ice-spirit,skeletons,ice-golem,cannon,fireball,the-log,musketeer" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">3. Control / Counter-Push (Aus der Defensive glänzen)</span><span class="i18n-en">3. Control / Counter-Push (Shine From Defense)</span></h4>
                    <p><span class="i18n-de">Ein reaktiver Stil, bei dem die überlebenden Verteidigungstruppen sofort zum Gegenangriff genutzt werden.</span><span class="i18n-en">A reactive style where surviving defensive troops are immediately used for a counter-attack.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Den Gegner effizient abwehren und den daraus resultierenden Elixier-Vorteil bestrafen.</span><span class="i18n-en"><b>Approach:</b> Defend against the opponent efficiently and punish the resulting elixir advantage.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (P.E.K.K.A. Bridge Spam):</b> P.E.K.K.A., Kampfholzfäller, Königsgeist, Magieschütze, Kampframme, Gift, Zap, Elektromagier.</span><span class="i18n-en"><b>Example deck (P.E.K.K.A. Bridge Spam):</b> P.E.K.K.A., Lumberjack, Royal Ghost, Magic Archer, Battle Ram, Poison, Zap, Electro Wizard.</span>
                        <br><a href="https://royaleapi.com/decks/stats/pekka,lumberjack,royal-ghost,magic-archer,battle-ram,poison,zap,electro-wizard" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">4. Bridge Spam (Tempo-Druck)</span><span class="i18n-en">4. Bridge Spam (Tempo Pressure)</span></h4>
                    <p><span class="i18n-de">Truppen werden direkt an der Brücke platziert, um den Gegner zu sofortigen und oft hektischen Reaktionen zu zwingen.</span><span class="i18n-en">Troops are placed directly at the bridge to force the opponent into immediate and often hectic reactions.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Karten mit hoher Geschwindigkeit nutzen, sobald der Gegner wenig Elixier hat oder eine teure Karte hinten spielt.</span><span class="i18n-en"><b>Approach:</b> Use high-speed cards as soon as the opponent has little elixir or plays an expensive card at the back.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (Ram Rider Spam):</b> Ram Rider, Dunkler Prinz, Banditin, Infernodrache, Elektro-Geist, Barbarenfass, Riesenschneeball, Blitz.</span><span class="i18n-en"><b>Example deck (Ram Rider Spam):</b> Ram Rider, Dark Prince, Bandit, Inferno Dragon, Electro Spirit, Barbarian Barrel, Giant Snowball, Lightning.</span>
                        <br><a href="https://royaleapi.com/decks/stats/ram-rider,dark-prince,bandit,inferno-dragon,electro-spirit,barbarian-barrel,giant-snowball,lightning" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">5. Siege (Belagerung)</span><span class="i18n-en">5. Siege</span></h4>
                    <p><span class="i18n-de">Angriffe erfolgen von der eigenen Spielfeldhälfte aus, ohne die Brücke zu überqueren.</span><span class="i18n-en">Attacks are launched from your own side of the field without crossing the bridge.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Gebäude wie den X-Bogen an der Brücke platzieren und diese mit allen Mitteln verteidigen.</span><span class="i18n-en"><b>Approach:</b> Place buildings like the X-Bow at the bridge and defend them by any means.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (X-Bow 3.0):</b> X-Bogen, Tesla, Ritter, Bogenschützen, Eisgeist, Skelette, Feuerball, Der Stamm (Log).</span><span class="i18n-en"><b>Example deck (X-Bow 3.0):</b> X-Bow, Tesla, Knight, Archers, Ice Spirit, Skeletons, Fireball, The Log.</span>
                        <br><a href="https://royaleapi.com/decks/stats/x-bow,tesla,knight,archers,ice-spirit,skeletons,fireball,the-log" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>

                    <h4 style="color: #f97316; margin-top: 18px;"><span class="i18n-de">6. Bait (Die Köder-Taktik)</span><span class="i18n-en">6. Bait (The Bait Tactic)</span></h4>
                    <p><span class="i18n-de">Den Gegner dazu verleiten, seine Zauber für weniger wichtige Karten zu verschwenden, um dann mit der eigentlichen Gefahr zuzuschlagen.</span><span class="i18n-en">Lure the opponent into wasting their spells on less important cards, then strike with the actual threat.</span></p>
                    <ul>
                        <li><span class="i18n-de"><b>Vorgehensweise:</b> Karten wie die Prinzessin nutzen, um „Log" oder „Arrows" zu erzwingen, und dann das Koboldfass werfen.</span><span class="i18n-en"><b>Approach:</b> Use cards like Princess to force out "Log" or "Arrows", then throw the Goblin Barrel.</span></li>
                        <li><span class="i18n-de"><b>Beispiel-Deck (Classic Log Bait):</b> Koboldfass, Prinzessin, Koboldgang, Infernoturm, Ritter, Eisgeist, Rakete, Der Stamm (Log).</span><span class="i18n-en"><b>Example deck (Classic Log Bait):</b> Goblin Barrel, Princess, Goblin Gang, Inferno Tower, Knight, Ice Spirit, Rocket, The Log.</span>
                        <br><a href="https://royaleapi.com/decks/stats/goblin-barrel,princess,goblin-gang,inferno-tower,knight,ice-spirit,rocket,the-log" target="_blank" style="color: #38bdf8;">🔗 <span class="i18n-de">Auf RoyaleAPI öffnen</span><span class="i18n-en">Open on RoyaleAPI</span></a></li>
                    </ul>
                </div>

            </div>

            <div id="Decks" class="tab-content">
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 10px; color: #ffffff;">🃏 {t('Clan-Meta: Die besten Kriegs-Decks', 'Clan Meta: The Best War Decks')}</h2>
                <p style="text-align: center; color: #94a3b8; margin-bottom: 30px;">{t('Das System analysiert die Clankriegs-Kämpfe der letzten 30 Tage und sortiert sie für euch in starke Meta-Decks, solide Allrounder und einsteigerfreundliche Optionen.', 'The system analyzes clan war battles from the last 30 days and sorts them into strong meta decks, solid all-rounders and beginner-friendly options.')}</p>
                <div>
                    {deck_html}
                </div>
                {opponent_meta_html}
            </div>

            <div id="Impressum" class="tab-content">
                {impressum_html}
            </div>

            <div id="Datenschutz" class="tab-content">
                {datenschutz_html}
            </div>

            <footer class="site-footer">
                <div class="footer-links">
                    <a class="footer-link" onclick="openTabByName('Impressum')">{t('Impressum', 'Imprint')}</a>
                    <a class="footer-link" onclick="openTabByName('Datenschutz')">{t('Datenschutz', 'Privacy')}</a>
                </div>
            </footer>
        </div>

        <script>
            (function initLanguage() {{
                var stored = null;
                try {{ stored = localStorage.getItem('clanLang'); }} catch (e) {{}}
                var supported = ['de', 'en'];
                var initial = supported.indexOf(stored) !== -1
                    ? stored
                    : ((navigator.language || 'de').toLowerCase().indexOf('en') === 0 ? 'en' : 'de');
                setLanguage(initial);
                document.addEventListener('DOMContentLoaded', function () {{
                    var btns = document.querySelectorAll('.lang-toggle button[data-lang]');
                    btns.forEach(function (btn) {{
                        btn.addEventListener('click', function () {{
                            setLanguage(btn.getAttribute('data-lang'));
                        }});
                    }});
                    syncToggleUI(document.documentElement.lang);
                }});
            }})();

            function setLanguage(lang) {{
                if (lang !== 'de' && lang !== 'en') lang = 'de';
                document.documentElement.lang = lang;
                try {{ localStorage.setItem('clanLang', lang); }} catch (e) {{}}
                syncToggleUI(lang);
            }}

            function syncToggleUI(lang) {{
                var btns = document.querySelectorAll('.lang-toggle button[data-lang]');
                btns.forEach(function (btn) {{
                    var active = btn.getAttribute('data-lang') === lang;
                    btn.classList.toggle('active', active);
                    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
                }});
            }}

            function toggleChat() {{
                var el = document.getElementById("admin-chat-container");
                if (!el) return;
                if (el.style.display === "none" || el.style.display === "") {{
                    el.style.display = "block";
                }} else {{
                    el.style.display = "none";
                }}
            }}

            function openTab(evt, tabName) {{
                var i, tabcontent, tablinks;
                tabcontent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabcontent.length; i++) {{
                    tabcontent[i].style.display = "none";
                    tabcontent[i].classList.remove("active");
                }}
                tablinks = document.getElementsByClassName("tab-btn");
                for (i = 0; i < tablinks.length; i++) {{
                    tablinks[i].classList.remove("active");
                }}
                document.getElementById(tabName).style.display = "block";
                setTimeout(() => document.getElementById(tabName).classList.add("active"), 10);
                evt.currentTarget.classList.add("active");
                window.scrollTo({{top: 0, behavior: 'smooth'}});
            }}

            function openTabByName(tabName) {{
                var i, tabcontent, tablinks;
                tabcontent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabcontent.length; i++) {{
                    tabcontent[i].style.display = "none";
                    tabcontent[i].classList.remove("active");
                }}
                tablinks = document.getElementsByClassName("tab-btn");
                for (i = 0; i < tablinks.length; i++) {{
                    tablinks[i].classList.remove("active");
                    var onclickAttr = tablinks[i].getAttribute("onclick") || "";
                    if (onclickAttr.indexOf("'" + tabName + "'") !== -1) {{
                        tablinks[i].classList.add("active");
                    }}
                }}
                document.getElementById(tabName).style.display = "block";
                setTimeout(() => document.getElementById(tabName).classList.add("active"), 10);
                window.scrollTo({{top: 0, behavior: 'smooth'}});
            }}

            (function enableMobileSwipeNavigation() {{
                var swipeTabs = ["Overview", "Table", "Wiki", "Decks"];
                var startX = null;
                var startY = null;
                var startTarget = null;
                var minSwipeDistance = 70;
                var maxVerticalDrift = 50;

                function isMobileWidth() {{
                    return window.matchMedia("(max-width: 768px)").matches;
                }}

                function shouldIgnoreSwipe(target) {{
                    if (!target || !target.closest) return false;
                    return !!target.closest(".tab-container, .deck-slider, .accordion-btn, .accordion-content, textarea, input, select, a, button, .copy-btn");
                }}

                function getActiveSwipeTab() {{
                    for (var i = 0; i < swipeTabs.length; i++) {{
                        var el = document.getElementById(swipeTabs[i]);
                        if (el && el.classList.contains("active")) {{
                            return swipeTabs[i];
                        }}
                    }}
                    return "Overview";
                }}

                document.addEventListener("touchstart", function(e) {{
                    if (!isMobileWidth() || !e.touches || e.touches.length !== 1) return;
                    startTarget = e.target;
                    if (shouldIgnoreSwipe(startTarget)) {{
                        startX = null;
                        startY = null;
                        return;
                    }}
                    startX = e.touches[0].clientX;
                    startY = e.touches[0].clientY;
                }}, {{ passive: true }});

                document.addEventListener("touchend", function(e) {{
                    if (!isMobileWidth() || startX === null || !e.changedTouches || e.changedTouches.length !== 1) return;
                    var endX = e.changedTouches[0].clientX;
                    var endY = e.changedTouches[0].clientY;
                    var deltaX = endX - startX;
                    var deltaY = endY - startY;

                    startX = null;
                    startY = null;

                    if (Math.abs(deltaX) < minSwipeDistance || Math.abs(deltaY) > maxVerticalDrift) return;
                    if (shouldIgnoreSwipe(startTarget)) return;

                    var currentTab = getActiveSwipeTab();
                    var currentIndex = swipeTabs.indexOf(currentTab);
                    if (currentIndex === -1) return;

                    if (deltaX < 0 && currentIndex < swipeTabs.length - 1) {{
                        openTabByName(swipeTabs[currentIndex + 1]);
                    }} else if (deltaX > 0 && currentIndex > 0) {{
                        openTabByName(swipeTabs[currentIndex - 1]);
                    }}
                }}, {{ passive: true }});
            }})();

            var acc = document.getElementsByClassName("accordion-btn");
            for (var i = 0; i < acc.length; i++) {{
                acc[i].addEventListener("click", function() {{
                    var isActive = this.classList.contains("active");

                    for (var j = 0; j < acc.length; j++) {{
                        acc[j].classList.remove("active");
                        acc[j].nextElementSibling.style.maxHeight = null;
                    }}

                    if (!isActive) {{
                        this.classList.add("active");
                        setTimeout(() => {{
                            this.scrollIntoView({{behavior: "smooth", block: "start"}});
                        }}, 300);
                        this.nextElementSibling.style.maxHeight = this.nextElementSibling.scrollHeight + "px";
                    }}
                }});
            }}
        </script>
    </body>
    </html>
    """


def generate_html_report(
    df_active: pd.DataFrame,
    df_history: pd.DataFrame,
    fame_spalte: str,
    heute_datum: str,
    header_img_src: str,
    radar_clans: list,
    records: dict,
    strikes_data: dict,
    race_state_de: str,
    raw_mahnwache: list,
    top_decks_data: dict,
    echte_neulinge: list,
    rueckkehrer: list,
    warn_rueckkehrer: list,
    kicked_players: dict,
    is_weekly_run: bool,
    clan_overview: dict = None,
    player_profiles: dict = None,
    opponent_decks: dict = None,
    player_war_decks: dict = None,
    current_war_participants: dict = None,
) -> Tuple[str, pd.DataFrame, str, dict, dict, dict]:
    player_stats = []
    urlauber_liste = []

    if urlaub_path.exists():
        with urlaub_path.open("r", encoding="utf-8") as f:
            urlauber_liste = [line.strip() for line in f if line.strip()]
    urlauber_liste_lower = [u.lower() for u in urlauber_liste]

    role_map = {
        "member":   ("<span class='i18n-de'>Mitglied</span><span class='i18n-en'>Member</span>",   "Member"),
        "elder":    ("<span class='i18n-de'>Ältester</span><span class='i18n-en'>Elder</span>",     "Elder"),
        "coleader": ("<span class='i18n-de'>Vize</span><span class='i18n-en'>Co-leader</span>",     "Co-leader"),
        "leader":   ("<span class='i18n-de'>Anführer</span><span class='i18n-en'>Leader</span>",    "Leader"),
        "unknown":  ("<span class='i18n-de'>Ehemalig</span><span class='i18n-en'>Former</span>",    "Former"),
    }

    strikes = strikes_data.get("players", {})
    last_strike_week = strikes_data.get("last_strike_week", 0)

    curr_week = datetime.now(timezone.utc).isocalendar()[:2]  # (Jahr, Woche) – verhindert Fehler beim Jahreswechsel

    apply_strikes_now = False
    if is_weekly_run:
        if last_strike_week != curr_week:
            apply_strikes_now = True
            strikes_data["last_strike_week"] = curr_week
            strikes_data["demoted_this_week"] = []
            strikes_data["kicked_this_week"] = []

    # Vorhandene Historie vorbereiten
    if df_history.empty:
        df_history = pd.DataFrame(columns=["player_name", "score", "date", "trophies"])

    # Loop-invariante Spalten einmal vor der Schleife berechnen
    _all_cols = df_active.columns
    fame_columns_all = sorted(
        [col for col in _all_cols if str(col).startswith("s_") and str(col).endswith("_fame")],
        reverse=True
    )
    fame_cols_rolling  = fame_columns_all[:4]
    decks_cols_rolling = [col.replace("_fame", "_decks_used") for col in fame_cols_rolling]
    aktueller_decks_spalte = fame_spalte.replace("_fame", "_decks_used")
    _player_profiles   = player_profiles or {}

    for row in df_active.itertuples(index=False):
        raw_role = str(getattr(row, "player_role", "unknown") or "unknown").strip().lower()
        if raw_role == "unknown":
            continue

        name = getattr(row, "player_name", "Unbekannt") or "Unbekannt"
        role_de = role_map.get(raw_role, (raw_role.capitalize(), raw_role.capitalize()))[0]
        is_urlaub = name.lower() in urlauber_liste_lower

        wars_with_participation = int(getattr(row, "player_contribution_count", 0) or 0)
        wars_in_history_window  = int(getattr(row, "player_participating_count", 0) or 0)
        decks_total             = int(getattr(row, "player_total_decks_used", 0) or 0)
        donations               = int(getattr(row, "player_donations", 0) or 0)
        donations_received      = int(getattr(row, "player_donations_received", 0) or 0)
        aktueller_trophy        = int(getattr(row, "player_trophies", 0) or 0)
        total_boat_attacks      = int(getattr(row, "player_total_boat_attacks", 0) or 0)

        # Spieler-Profil (wenn vorhanden)
        player_tag = str(getattr(row, "player_tag", "") or "")
        profile = _player_profiles.get(player_tag, {})

        # Score-Logik: Gewichteter 3-Faktor-Score
        # 50% Deck-Vollstaendigkeit: Wie viele der moeglichen Decks wurden gespielt?
        # 30% Dabei-Quote (Anwesenheit): In wie vielen Kriegen war der Spieler dabei?
        # 20% Qualitaet: Normierter Ø Fame/Deck-Wert (75 = min, 225 = max)
        anwesenheits_rate = (wars_with_participation / wars_in_history_window) if wars_in_history_window > 0 else 0.0
        max_moegliche_decks   = wars_with_participation * 16
        deck_vollstaendigkeit = (decks_total / max_moegliche_decks) if max_moegliche_decks > 0 else 0.0

        total_war_points   = sum(int(getattr(row, col, 0) or 0) for col in fame_columns_all)
        aktueller_fame     = int(getattr(row, fame_spalte, 0) or 0)
        aktueller_decks    = int(getattr(row, aktueller_decks_spalte, 0) or 0)

        # Ø Punkte: rollierender Schnitt ueber die letzten 3-4 Kriege.
        # Glaettet Ausreisser durch Pech beim Matchmaking für ein faireres Bild.
        rolling_fame  = sum(int(getattr(row, c, 0) or 0) for c in fame_cols_rolling)
        rolling_decks = sum(int(getattr(row, c, 0) or 0) for c in decks_cols_rolling)
        fame_per_deck = round(rolling_fame / rolling_decks) if rolling_decks > 0 else 0

        # Score-Berechnung: 50% Deck-Vollständigkeit + 30% Dabei-Quote + 20% Qualität
        qualitaet = max(0.0, min(1.0, (fame_per_deck - 75) / 150)) if fame_per_deck > 0 else 0.0
        score = round(
            50 * deck_vollstaendigkeit +
            30 * anwesenheits_rate +
            20 * qualitaet,
            2
        )

        leecher_warnung = ""
        if 0 < fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"]:
            leecher_warnung = (
                " <span class='custom-tooltip'>⚠️"
                "<span class='tooltip-text'>Auffällig niedriger Ertrag pro Deck "
                "(Schnitt der letzten 3–4 Kriege, bitte Spielweise prüfen)</span></span>"
            )

        historie_spieler = df_history[df_history["player_name"] == name].copy()
        historie_spieler = historie_spieler.sort_values("date")
        vergangene_scores = historie_spieler.tail(5)["score"].tolist()  # 5 vergangene + aktuelle = 6 Punkte im Trend

        past_trophy = aktueller_trophy
        if not historie_spieler.empty and "trophies" in historie_spieler.columns:
            try:
                past_trophy = int(historie_spieler.tail(1)["trophies"].values[0])
            except Exception:
                past_trophy = aktueller_trophy

        trophy_push = aktueller_trophy - past_trophy
        delta = round(score - vergangene_scores[-1], 2) if vergangene_scores else 0.0

        if donations > records.setdefault("donations", {"name": "-", "val": 0})["val"]:
            records["donations"] = {"name": name, "val": donations}
        if delta > records.setdefault("delta", {"name": "-", "val": 0})["val"]:
            records["delta"] = {"name": name, "val": delta}
        if aktueller_trophy > records.setdefault("trophies", {"name": "-", "val": 0})["val"]:
            records["trophies"] = {"name": name, "val": aktueller_trophy}

        trend_scores = vergangene_scores + [score]
        trend_str = "".join(
            ["🟢" if s >= APP_CONFIG["TIER_SOLIDE"] else "🟡" if s >= APP_CONFIG["STRIKE_THRESHOLD"] else "🔴" for s in trend_scores[-6:]]
        )

        # Streak-Logik: alle Decks in allen Kriegen seit Clan-Beitritt gespielt
        # Bedingung: kein Krieg verpasst UND immer alle 16 Decks gespielt, mind. 3 Kriege
        streak_badge = ""
        if (
            wars_with_participation >= 3
            and wars_with_participation == wars_in_history_window
            and decks_total == wars_with_participation * 16
        ):
            streak_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥 {wars_with_participation}"
                f"<span class='tooltip-text'>{wars_with_participation}x alle Decks gespielt – ohne Ausnahme!</span></span>"
            )

        # Verwarnungen nur bei mehr als MIN_PARTICIPATION und nicht im Urlaub
        if apply_strikes_now:
            if not is_urlaub and wars_with_participation > APP_CONFIG["MIN_PARTICIPATION"]:
                if score < APP_CONFIG["STRIKE_THRESHOLD"]:
                    strikes[name] = strikes.get(name, 0) + 1
                else:
                    if strikes.get(name, 0) > 0:
                        strikes[name] -= 1

        strike_val = strikes.get(name, 0)

        if apply_strikes_now and strike_val >= 1:
            if not is_urlaub:
                if raw_role in ["leader", "coleader", "elder"]:
                    strikes_data.setdefault("demoted_this_week", []).append(name)
                    strikes[name] = 0
                elif raw_role == "member":
                    strikes_data.setdefault("kicked_this_week", []).append(name)
                    kicked_players[name] = heute_datum
                    strikes[name] = 1

        strike_badge = ""
        if name in strikes_data.get("demoted_this_week", []):
            strike_badge = (
                " <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 1/1"
                "<span class='tooltip-text'>Wurde degradiert! Bewährungschance aktiv.</span></span>"
            )
        elif name in strikes_data.get("kicked_this_week", []):
            strike_badge = (
                " <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 1/1"
                "<span class='tooltip-text'>1 interner Hinweis: interne Maßnahme erfolgt.</span></span>"
            )
        elif strike_val > 0:
            strike_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ {strike_val}/1"
                "<span class='tooltip-text'>Interner Hinweis. Bei 1/1 folgen interne Maßnahmen.</span></span>"
            )

        # Welpenschutz-Logik
        is_welpenschutz = wars_with_participation <= APP_CONFIG["MIN_PARTICIPATION"] and not is_urlaub
        welpenschutz_badge = ""
        if is_welpenschutz:
            welpenschutz_badge = (
                " <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱"
                "<span class='tooltip-text'>Erster Clankrieg – Welpenschutz aktiv. Ab dem 2. Krieg volle Bewertung.</span></span>"
            )
            # Trend bei Welpenschutz leeren - alte History-Einträge aus früheren
            # Aufenthalten würden sonst ein irreführendes Bild erzeugen.
            trend_str = "🟢" * wars_with_participation if score >= APP_CONFIG["TIER_SOLIDE"] else "🟡" * wars_with_participation if score >= APP_CONFIG["STRIKE_THRESHOLD"] else "🔴" * wars_with_participation

        focus_label, focus_color = get_player_focus(
            score=score,
            fame_per_deck=fame_per_deck,
            donations=donations,
            is_welpenschutz=is_welpenschutz,
            current_decks=aktueller_decks
        )
        focus_badge = (
            f"<span class='focus-pill' style='background:{focus_color}22; color:{focus_color}; border:1px solid {focus_color}55;'>{focus_label}</span>"
            if focus_label else
            "<span style='color:#64748b;'>-</span>"
        )

        if is_urlaub:
            status_html = "🏖️ " + t("Urlaub", "Vacation")
            tier = "🏖️ " + t("Abgemeldet / Im Urlaub (Pausiert)", "Logged Off / On Vacation (Paused)")
        else:
            status_html = (
                f"{role_de} <span class='badge-ja'>➔ BEFÖRDERN</span>"
                if raw_role == "member" and aktueller_fame >= 2800
                else role_de
            )

            if score >= APP_CONFIG["TIER_SEHR_STARK"]:
                tier = t("Sehr stark", "Very Strong")
            elif score >= APP_CONFIG["TIER_SOLIDE"]:
                tier = t("Solide Basis", "Solid Base")
            elif score >= APP_CONFIG["STRIKE_THRESHOLD"]:
                tier = t("Mehr drin", "Underperforming")
            else:
                tier = t("Ausbaufaehig", "Room to Grow")

        player_stats.append({
            "name": name,
            "status": status_html,
            "score": score,
            "delta": delta,
            "teilnahme": f"{wars_with_participation}/{wars_in_history_window}",
            "teilnahme_int": wars_with_participation,
            "fame": aktueller_fame,
            "current_decks": aktueller_decks,
            "war_points_total": total_war_points,
            "donations": donations,
            "donations_received": donations_received,
            "tier": tier,
            "is_urlaub": is_urlaub,
            "is_welpenschutz": is_welpenschutz,
            "trend_str": trend_str,
            "fame_per_deck": fame_per_deck,
            "leecher_warnung": leecher_warnung,
            "trophy_push": trophy_push,
            "trophies": aktueller_trophy,
            "streak_badge": streak_badge,
            "strike_badge": strike_badge,
            "welpenschutz_badge": welpenschutz_badge,
            "focus_badge": focus_badge,
            "raw_role": raw_role,
            "boat_attacks": total_boat_attacks,
            "exp_level": profile.get("exp_level", 0),
            "best_trophies": profile.get("best_trophies", 0),
            "win_rate": profile.get("win_rate", 0),
            "challenge_max_wins": profile.get("challenge_max_wins", 0),
            "war_day_wins": profile.get("war_day_wins", 0),
            "favourite_card": profile.get("favourite_card", ""),
            "tag": player_tag,
            "total_decks": decks_total,
            "deck_vollstaendigkeit": deck_vollstaendigkeit,
            "max_moegliche_decks": max_moegliche_decks,
            "wars_in_window": wars_in_history_window,
        })

        if is_weekly_run:
            # Nur schreiben wenn für diesen Spieler noch kein Eintrag mit diesem Datum existiert.
            # Verhindert Doppeleinträge falls der Weekly-Run versehentlich mehrfach läuft.
            already_written = (
                (df_history["player_name"] == name) & (df_history["date"] == heute_datum)
            ).any()
            if not already_written:
                df_history = pd.concat([
                    df_history,
                    pd.DataFrame([{
                        "player_name": name,
                        "score": score,
                        "date": heute_datum,
                        "trophies": aktueller_trophy
                    }])
                ], ignore_index=True)

    player_stats_path = BASE_DIR / "player_stats.json"
    with open(player_stats_path, "w", encoding="utf-8") as f:
        json.dump([
            {
                "tag": p["tag"],
                "name": p["name"],
                "role": p["raw_role"],
                "score": p["score"],
                "trophies": p["trophies"],
                "fame_per_deck": p["fame_per_deck"],
                "participation_count": p["teilnahme_int"],
                "total_decks": p["total_decks"],
                "wars_in_window": p["wars_in_window"],
                "war_points_total": p["war_points_total"],
                "donations": p["donations"],
                "donations_received": p["donations_received"],
            }
            for p in player_stats
        ], f, ensure_ascii=False, indent=2)

    aktive_spieler = [p for p in player_stats if not p["is_urlaub"]]

    # Einen Durchlauf für alle Clan-Aggregate
    _score_sum = _fame_sum = _decks_sum = 0
    quality_green = quality_yellow = quality_red = 0
    wf_gruen = wf_gelb = wf_rot = 0
    _n = len(aktive_spieler)
    for _p in aktive_spieler:
        _score_sum += _p["score"]
        if _p["current_decks"] > 0:
            _fame_sum  += _p["fame"]
            _decks_sum += _p["current_decks"]
            _fpd = _p["fame_per_deck"]
            if   _fpd >= 162:           quality_green  += 1
            elif _fpd >= 130:           quality_yellow += 1
            elif _fpd >  0:             quality_red    += 1
        _s = _p["score"]
        if   _s >= TIER_SOLIDE:         wf_gruen += 1
        elif _s >= STRIKE_THRESHOLD:    wf_gelb  += 1
        else:                           wf_rot   += 1

    clan_avg              = round(_score_sum / _n, 2) if _n else 0
    clan_total_fame       = _fame_sum
    clan_total_decks      = _decks_sum
    clan_avg_points_per_deck = round(clan_total_fame / clan_total_decks) if clan_total_decks > 0 else 0
    clan_teamplay, teamplay_details = calculate_teamplay_score(aktive_spieler)

    # --- KAMPFQUALITÄT: Verteilung & Trend ---

    prev_quality = records.get("clan_quality", {}).get("val", 0)
    quality_delta = clan_avg_points_per_deck - prev_quality if prev_quality > 0 else None

    if is_weekly_run:
        records["clan_quality"] = {"val": clan_avg_points_per_deck}

    # --- HISTORIE CLEANUP (Nur aktive behalten & max. die letzten 6 Wochen) ---
    aktive_namen_set = set(df_active["player_name"].tolist())
    df_history = df_history[df_history["player_name"].isin(aktive_namen_set)]
    df_history = df_history.groupby("player_name").tail(6).reset_index(drop=True)

    top_performers_list = heapq.nlargest(3, aktive_spieler,
        key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]))

    top_aufsteiger_list = heapq.nlargest(3,
        (p for p in aktive_spieler if p["delta"] > 0),
        key=lambda x: x["delta"])

    top_spender_list = heapq.nlargest(3,
        (p for p in aktive_spieler if p["donations"] > 0),
        key=lambda x: x["donations"])

    top_leecher_list = heapq.nlargest(3,
        (p for p in aktive_spieler if p["teilnahme_int"] > MIN_PARTICIPATION and p["donations"] == 0 and p["donations_received"] > 0),
        key=lambda x: x["donations_received"])

    top_performers_html = "".join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in top_performers_list])
    top_aufsteiger_html = "".join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger_list]) if top_aufsteiger_list else "<li>Keine Verbesserungen</li>"
    top_spender_html = "".join([f"<li><b>{p['name']}</b> ({p['donations']})</li>" for p in top_spender_list]) if top_spender_list else "<li>Keine Spenden</li>"
    top_leecher_html = "".join([f"<li><b>{p['name']}</b> ({p['donations']} gesp. / {p['donations_received']} empf.)</li>" for p in top_leecher_list]) if top_leecher_list else f"<li>{t('Keine Auffälligkeiten', 'No issues')} 🎉</li>"

    reliability_state, reliability_color = get_signal_state(clan_avg, APP_CONFIG["CLAN_RELIABLE_GREEN"], APP_CONFIG["CLAN_RELIABLE_YELLOW"])
    quality_state, quality_color = get_signal_state(clan_avg_points_per_deck, APP_CONFIG["BADGE_STARK_FAME"], APP_CONFIG["BADGE_STABIL_FAME"])
    teamplay_state, teamplay_color = get_signal_state(clan_teamplay, 60, 35)

    _signal_label = {"stark": t("STARK", "STRONG"), "okay": "OKAY", "kritisch": t("KRITISCH", "CRITICAL")}
    reliability_label = _signal_label.get(reliability_state, reliability_state.upper())
    teamplay_label    = _signal_label.get(teamplay_state,    teamplay_state.upper())

    if quality_delta is None:
        quality_trend_html = ""
    elif quality_delta > 0:
        quality_trend_html = f"<div style='color:#10b981; font-size:0.88em; margin-top:2px;'>▲ +{quality_delta} {t('zur Vorwoche', 'vs last week')}</div>"
    elif quality_delta < 0:
        quality_trend_html = f"<div style='color:#ef4444; font-size:0.88em; margin-top:2px;'>▼ {quality_delta} {t('zur Vorwoche', 'vs last week')}</div>"
    else:
        quality_trend_html = f"<div style='color:#94a3b8; font-size:0.88em; margin-top:2px;'>→ {t('unverändert', 'unchanged')}</div>"

    quality_dist_html = f"<div style='font-size:0.88em; margin-top:6px; letter-spacing:1px;'>🟢 {quality_green}&nbsp;&nbsp;🟡 {quality_yellow}&nbsp;&nbsp;🔴 {quality_red}</div>"

    clan_ampel_html = f"""
    <div class='signal-board'>
        <div class='signal-card'>
            <h4>📈 {t('Zuverlässigkeit', 'Reliability')}</h4>
            <div class='signal-value' style='color:{reliability_color};'>{reliability_label}</div>
            <div style='color:#94a3b8; font-size:0.92em;'>{t('Bewertung des Clan-Durchschnitts', 'Assessment of clan average')}</div>
            <div class='signal-state' style='color:{reliability_color};'>{reliability_state.upper()}</div>
        </div>
        <div class='signal-card'>
            <h4>⚔️ {t('Kampfqualität', 'Battle Quality')}</h4>
            <div class='signal-value' style='color:{quality_color};'>{clan_avg_points_per_deck}</div>
            {quality_trend_html}
            {quality_dist_html}
            <div style='color:#94a3b8; font-size:0.8em; margin-top:4px;'>{t('Ø Punkte pro Deck', 'Avg points per deck')}</div>
        </div>
        <div class='signal-card'>
            <h4>🤝 {t('Teamplay', 'Teamplay')}</h4>
            <div class='signal-value' style='color:{teamplay_color};'>{teamplay_label}</div>
            <div style='color:#94a3b8; font-size:0.92em;'>{teamplay_details['donors']} {t('von', 'of')} {len(aktive_spieler)} {t('Aktiven spenden mit', 'active members donate')}</div>
            <div class='signal-state' style='color:{teamplay_color};'>{teamplay_label}</div>
        </div>
    </div>
    """

    summary_lines = []

    # 1. Zuverlässigkeit
    if clan_avg >= APP_CONFIG["CLAN_RELIABLE_GREEN"]:
        summary_lines.append(t("Der Clan spielt seine Decks sehr zuverlässig aus.", "The clan plays its decks very reliably."))
    elif clan_avg >= APP_CONFIG["CLAN_RELIABLE_YELLOW"]:
        summary_lines.append(t("Die Zuverlässigkeit ist okay, aber es bleiben noch zu viele Decks liegen.", "Reliability is okay, but too many decks are still left unplayed."))
    else:
        summary_lines.append(t("Beim Ausspielen der Decks verlieren wir aktuell zu viel Boden.", "We are losing too much ground on deck usage right now."))

    # 2. Kampfqualität + Trend
    if clan_avg_points_per_deck >= APP_CONFIG["BADGE_STARK_FAME"]:
        quality_text = t("Die Kampfqualität ist stark – der Clan gewinnt deutlich mehr als er verliert.", "Battle quality is strong – the clan wins significantly more than it loses.")
    elif clan_avg_points_per_deck >= APP_CONFIG["BADGE_STABIL_FAME"]:
        quality_text = t("Die Kampfqualität ist solide, hat aber noch Luft nach oben.", "Battle quality is solid but still has room to grow.")
    else:
        quality_text = t("Die Kämpfe bringen aktuell zu wenig Ertrag pro Deck – mehr normale Kämpfe und Duelle helfen.", "Battles currently yield too little per deck – more normal battles and duels help.")
    if quality_delta is not None and quality_delta > 0:
        quality_text += f" <span style='color:#10b981;'>▲ +{quality_delta} {t('zur Vorwoche', 'vs last week')}.</span>"
    elif quality_delta is not None and quality_delta < 0:
        quality_text += f" <span style='color:#ef4444;'>▼ {quality_delta} {t('zur Vorwoche', 'vs last week')}.</span>"
    summary_lines.append(quality_text)

    # 3. Teamplay
    if teamplay_state == "kritisch":
        summary_lines.append(t("Beim Spenden und Unterstützen im Clan ist gerade noch Luft nach oben.", "There is still room to improve donations and clan support."))
    elif teamplay_state == "okay":
        summary_lines.append(t("Beim Teamplay ist schon was da, aber noch nicht jeder zieht mit.", "Some teamplay is there, but not everyone is pulling their weight yet."))
    else:
        summary_lines.append(t("Auch beim Teamplay wirkt der Clan im Moment sehr geschlossen.", "Teamplay-wise the clan currently looks very tight-knit."))

    # 4. Tier-Verteilung (wf_gruen/gelb/rot aus dem Aggregations-Loop oben)
    summary_lines.append(f"📊 {t('Tier-Verteilung:', 'Tier distribution:')} 🟢 {wf_gruen} {t('stark', 'strong')} &nbsp; 🟡 {wf_gelb} {t('solide', 'solid')} &nbsp; 🔴 {wf_rot} {t('auffällig', 'notable')}.")

    # 5. Deutschland-Ranking
    if clan_overview:
        current_rank = clan_overview.get("local_rank")
        if current_rank:
            prev_rank = records.get("clan_war_rank", {}).get("rank")
            if prev_rank and prev_rank > 0:
                rank_delta = prev_rank - current_rank  # positiv = aufgestiegen
                if rank_delta > 0:
                    summary_lines.append(f"🏅 {t('Deutschland-Ranking:', 'Germany ranking:')} <b>{t('Platz', 'Rank')} #{current_rank}</b> — <span style='color:#10b981;'>↑ {rank_delta} {t('Plätze besser als letzte Woche!', 'places better than last week!')}</span>")
                elif rank_delta < 0:
                    summary_lines.append(f"🏅 {t('Deutschland-Ranking:', 'Germany ranking:')} <b>{t('Platz', 'Rank')} #{current_rank}</b> — <span style='color:#ef4444;'>↓ {abs(rank_delta)} {t('Plätze schlechter als letzte Woche.', 'places worse than last week.')}</span>")
                else:
                    summary_lines.append(f"🏅 {t('Deutschland-Ranking:', 'Germany ranking:')} <b>{t('Platz', 'Rank')} #{current_rank}</b> — {t('unverändert zur Vorwoche.', 'unchanged from last week.')}")
            else:
                summary_lines.append(f"🏅 {t('Deutschland-Ranking:', 'Germany ranking:')} <b>{t('Platz', 'Rank')} #{current_rank}</b>")

    # 6. Aufsteiger (top 3 mit delta > 0)
    if top_aufsteiger_list:
        names_str = ", ".join(f"<b>{p['name']}</b> <span style='color:#10b981;'>(+{p['delta']}%)</span>" for p in top_aufsteiger_list)
        summary_lines.append(f"🚀 {t('Stärkste Verbesserung:', 'Biggest improvement:')} {names_str}")

    # 6. Absteiger (top 3 mit delta < 0, keine Neulinge)
    top_absteiger_list = sorted(
        [p for p in aktive_spieler if p["delta"] < 0 and not p["is_welpenschutz"]],
        key=lambda x: x["delta"]
    )[:3]
    if top_absteiger_list:
        names_str = ", ".join(f"<b>{p['name']}</b> <span style='color:#ef4444;'>({p['delta']}%)</span>" for p in top_absteiger_list)
        summary_lines.append(f"⚠️ {t('Stärkster Rückgang:', 'Biggest decline:')} {names_str}")

    # 7+8. Nur an Kampftagen (nicht Trainingstag, da dort bereits in Coach-Ecke)
    if race_state_de in ("Clankrieg", "Colosseum"):
        streak_players = sorted(
            [p for p in aktive_spieler if p.get("streak_badge") and not p["is_welpenschutz"]],
            key=lambda x: x["score"], reverse=True
        )[:3]
        if streak_players:
            names_str = ", ".join(f"<b>{p['name']}</b>" for p in streak_players)
            summary_lines.append(f"🔥 {t('Konstant stark:', 'Consistently strong:')} {names_str}")

        kurz_vor_aufstieg = sorted(
            [p for p in aktive_spieler
             if not p["is_welpenschutz"] and not p["is_urlaub"]
             and p["score"] < APP_CONFIG["TIER_SOLIDE"]
             and p["score"] >= APP_CONFIG["TIER_SOLIDE"] - 8],
            key=lambda x: x["score"], reverse=True
        )
        if kurz_vor_aufstieg:
            names_str = ", ".join(f"<b>{p['name']}</b> ({p['score']}%)" for p in kurz_vor_aufstieg)
            summary_lines.append(f"⚡ {t('Fast im grünen Bereich:', 'Almost in the green zone:')} {names_str} – {t('noch ein paar Kämpfe!', 'a few more battles!')}")

    weekly_summary_html = f"<div class='info-box' style='border-left-color: #fbbf24;'><h3 style='margin-top:0; color:#fbbf24;'>🧭 {t('Wochenfazit', 'Weekly Summary')}</h3><ul style='margin:0;'>" + "".join([f"<li>{line}</li>" for line in summary_lines]) + "</ul></div>"

    aktive_namen_set = set(df_active["player_name"].tolist())
    preliminary_open_decks = sum(
        m["offen"]
        for m in raw_mahnwache
        if m["name"].lower() not in urlauber_liste_lower and m["name"] in aktive_namen_set
    )

    coach_items = []
    low_quality_count = sum(1 for p in aktive_spieler if p["current_decks"] > 0 and p["fame_per_deck"] < APP_CONFIG["DROPPER_THRESHOLD"])
    low_score_count = sum(1 for p in aktive_spieler if p["score"] < APP_CONFIG["TIER_SOLIDE"])
    newbie_count = sum(1 for p in aktive_spieler if p["is_welpenschutz"])

    # ── Trainingstag: motivierende Coach-Ecke ────────────────────────────────
    if race_state_de == "Trainingstag":
        training_items = []

        # Clan-Gesamtstärke
        if clan_avg >= APP_CONFIG["CLAN_RELIABLE_GREEN"]:
            training_items.append(
                f"<li><b>💪 Starke Clan-Performance!</b> Unser Clan-Durchschnitt liegt bei <b>{clan_avg}%</b> — das ist ein richtig solides Fundament. Weiter so!</li>"
            )
        elif clan_avg >= APP_CONFIG["CLAN_RELIABLE_YELLOW"]:
            training_items.append(
                f"<li><b>📈 Auf gutem Kurs!</b> Clan-Schnitt: <b>{clan_avg}%</b>. Noch ein Schritt und wir sind auf Top-Niveau — der nächste Krieg ist unsere Chance.</li>"
            )
        else:
            training_items.append(
                f"<li><b>🔥 Jetzt angreifen!</b> Clan-Schnitt liegt bei <b>{clan_avg}%</b>. Der Trainingstag ist die perfekte Zeit, neue Decks zu testen und sich für den nächsten Krieg bereit zu machen.</li>"
            )

        # Aufsteiger shoutout
        aufsteiger = sorted(
            [p for p in aktive_spieler if p["delta"] > 0],
            key=lambda x: x["delta"], reverse=True
        )[:3]
        if aufsteiger:
            names_str = ", ".join(
                f"<b>{p['name']}</b> <span style='color:#10b981;'>+{p['delta']}%</span>"
                for p in aufsteiger
            )
            training_items.append(
                f"<li><b>🚀 Shoutout an unsere Aufsteiger!</b> {names_str} — diese Spieler haben sich zuletzt besonders verbessert. Top!</li>"
            )

        # Streak-Highlights (3+ grüne Kriege)
        streak_players = sorted(
            [p for p in aktive_spieler if p.get("streak_badge") and not p["is_welpenschutz"]],
            key=lambda x: x["score"], reverse=True
        )[:3]
        if streak_players:
            names_str = ", ".join(f"<b>{p['name']}</b>" for p in streak_players)
            training_items.append(
                f"<li><b>🔥 Konstanz zahlt sich aus!</b> {names_str} liefern Krieg für Krieg ab — genau das trägt den Clan nach vorne.</li>"
            )

        # Spieler kurz vor Tier-Aufstieg
        kurz_vor_aufstieg = sorted(
            [p for p in aktive_spieler
             if not p["is_welpenschutz"] and not p["is_urlaub"]
             and p["score"] < APP_CONFIG["TIER_SOLIDE"]
             and p["score"] >= APP_CONFIG["TIER_SOLIDE"] - 8],
            key=lambda x: x["score"], reverse=True
        )
        if kurz_vor_aufstieg:
            names_str = ", ".join(
                f"<b>{p['name']}</b> ({p['score']}%)"
                for p in kurz_vor_aufstieg[:3]
            )
            grenze = APP_CONFIG["TIER_SOLIDE"]
            training_items.append(
                f"<li><b>⚡ Fast da!</b> {names_str} stehen kurz vor dem Sprung in die <i>Solide Basis</i> (ab {grenze}%). Noch ein guter Krieg reicht!</li>"
            )

        # Neulinge willkommen
        neulinge = [p for p in aktive_spieler if p["is_welpenschutz"]]
        if neulinge:
            namen = ", ".join(f"<b>{p['name']}</b>" for p in neulinge[:4])
            training_items.append(
                f"<li><b>👋 Willkommen im Team!</b> {namen} — schön, euch dabei zu haben. Einfach Decks spielen, ausprobieren, Spaß haben. Der Rest kommt von alleine.</li>"
            )

        # Allgemeiner Motivations-Abschluss
        training_items.append(
            "<li><b>🎯 Trainingstag-Tipp:</b> Jetzt ist der beste Moment, neue Deck-Ideen auszuprobieren — ohne Druck, ohne Konsequenzen. Wer den nächsten Krieg stark starten will, nutzt diese Zeit zum Testen.</li>"
        )

        coach_html = (
            "<div class='info-box' style='border-left-color: #a78bfa;'>"
            f"<h3 style='margin-top:0; color:#a78bfa;'>🧠 {t('Coach-Ecke', 'Coach Corner')}</h3>"
            f"<p style='margin-top:0;'>{t('Trainingstag — Zeit zum Durchatmen, Ausprobieren und Vorbereiten:', 'Training day — time to breathe, experiment and prepare:')}</p>"
            "<ul style='margin-bottom:0;'>" + "".join(training_items[:6]) + "</ul>"
            "</div>"
        )
    else:
        # ── Sieg-Prognose aus Radar-Daten ─────────────────────────────────────
        if race_state_de in ("Clankrieg", "Colosseum") and len(radar_clans) >= 2:
            us = next((c for c in radar_clans if c["is_us"]), None)
            if us:
                def get_eff(c):
                    mh = c.get("medals_heute")
                    if mh is not None and c["decks_used"] > 0:
                        return round(mh / c["decks_used"])
                    if c["decks_used"] > 0:
                        return round(c["medals"] / c["decks_used"])
                    return None

                played = [c for c in radar_clans if c["decks_used"] > 0]
                eff_values = [get_eff(c) for c in played if get_eff(c) is not None]
                fallback_eff = round(sum(eff_values) / len(eff_values)) if eff_values else 160
                fallback_eff = max(75, min(250, fallback_eff))

                def project_rank_asymmetric(clans, our_eff: int):
                    results = []
                    for c in clans:
                        remaining = max(0, c["max_decks"] - c["decks_used"])
                        if c["is_us"]:
                            eff = max(75, min(250, our_eff))
                        else:
                            eff = get_eff(c) or fallback_eff
                            eff = max(75, min(250, eff))
                        projected = c["medals"] + remaining * eff
                        results.append({"name": c["name"], "is_us": c["is_us"],
                                        "projected": int(projected), "remaining": remaining, "eff": eff})
                    results.sort(key=lambda x: x["projected"], reverse=True)
                    our_entry = next(r for r in results if r["is_us"])
                    rank = results.index(our_entry) + 1
                    return rank, int(our_entry["projected"])

                real_projections = []
                for c in radar_clans:
                    eff = get_eff(c) or fallback_eff
                    eff = max(75, min(250, eff))
                    remaining = max(0, c["max_decks"] - c["decks_used"])
                    real_projections.append({"name": c["name"], "is_us": c["is_us"],
                                             "projected": int(c["medals"] + remaining * eff),
                                             "remaining": remaining, "eff": eff})
                real_projections.sort(key=lambda x: x["projected"], reverse=True)
                our_real = next(r for r in real_projections if r["is_us"])
                rank_real = real_projections.index(our_real) + 1

                rank_worst, medals_worst = project_rank_asymmetric(radar_clans, 75)
                rank_best,  medals_best  = project_rank_asymmetric(radar_clans, 200)
                medals_real = our_real["projected"]

                def rank_badge_de(r):
                    return {1: "🥇 Platz 1", 2: "🥈 Platz 2", 3: "🥉 Platz 3"}.get(r, f"Platz {r}")

                def rank_badge_en(r):
                    return {1: "🥇 Place 1", 2: "🥈 Place 2", 3: "🥉 Place 3"}.get(r, f"Place {r}")

                row_worst = t(
                    f"🔴 Worst Case <i>(wir 75/Deck, Gegner ihr Schnitt)</i>: <b>{rank_badge_de(rank_worst)}</b> — ~{medals_worst:,} Punkte",
                    f"🔴 Worst Case <i>(us 75/deck, opponents their avg)</i>: <b>{rank_badge_en(rank_worst)}</b> — ~{medals_worst:,} pts"
                )
                row_real = t(
                    f"🟡 Realistisch <i>(alle auf aktuellem Schnitt, wir ~{our_real['eff']}/Deck)</i>: <b>{rank_badge_de(rank_real)}</b> — ~{medals_real:,} Punkte",
                    f"🟡 Realistic <i>(all at current avg, us ~{our_real['eff']}/deck)</i>: <b>{rank_badge_en(rank_real)}</b> — ~{medals_real:,} pts"
                )
                row_best = t(
                    f"🟢 Best Case <i>(wir 200/Deck, Gegner ihr Schnitt)</i>: <b>{rank_badge_de(rank_best)}</b> — ~{medals_best:,} Punkte",
                    f"🟢 Best Case <i>(us 200/deck, opponents their avg)</i>: <b>{rank_badge_en(rank_best)}</b> — ~{medals_best:,} pts"
                )

                if rank_worst == 1:
                    fazit = t("Selbst wenn wir alle Decks verlieren, halten wir <b>Platz 1</b>. Einfach alle Decks spielen!",
                              "Even if we lose all decks, we hold <b>Place 1</b>. Just play all decks!")
                elif rank_best == 1 and rank_worst <= 2:
                    fazit = t(f"Zwischen <b>Platz {rank_worst}</b> und <b>Platz 1</b> – unsere Kampfqualität entscheidet!",
                              f"Between <b>Place {rank_worst}</b> and <b>Place 1</b> – our battle quality decides!")
                elif rank_best == 1:
                    fazit = t("Platz 1 ist möglich – aber nur wenn wir deutlich besser kämpfen als aktuell. Alle Siege zählen!",
                              "Place 1 is possible – but only if we fight significantly better than now. Every win counts!")
                elif rank_real == 1 and rank_worst >= 2:
                    fazit = t(f"Realistisch <b>Platz 1</b>, aber bei schlechten Kämpfen droht <b>Platz {rank_worst}</b>. Qualität halten!",
                              f"Realistically <b>Place 1</b>, but poor battles risk <b>Place {rank_worst}</b>. Keep up the quality!")
                elif rank_best <= 2:
                    fazit = t(f"<b>Platz {rank_best}</b> ist das beste erreichbare Ergebnis heute. Alle Decks spielen!",
                              f"<b>Place {rank_best}</b> is the best achievable result today. Play all decks!")
                else:
                    fazit = t("Platz 1 oder 2 ist heute nicht mehr erreichbar. Alle Decks spielen für maximale Trophäen.",
                              "Place 1 or 2 is no longer reachable today. Play all decks for maximum trophies.")

                prognose_item = (
                    f"<li><b>📊 {t('Sieg-Prognose – 3 Szenarien', 'Victory Forecast – 3 Scenarios')}</b> ({us['decks_used']}/{us['max_decks']} {t('Decks gespielt heute', 'decks played today')}):"
                    f"<ul style='margin: 6px 0 4px 0; padding-left: 18px; font-size: 0.95em;'>"
                    f"<li>{row_worst}</li><li>{row_real}</li><li>{row_best}</li>"
                    f"</ul><span style='color:#94a3b8; font-size:0.9em;'>→ {fazit}</span></li>"
                )
                coach_items.append(prognose_item)

        if preliminary_open_decks > 0:
            open_de = f"Heute sind noch <b>{preliminary_open_decks}</b> Decks offen. Konstanz bringt uns im Moment am schnellsten nach vorne."
            open_en = f"<b>{preliminary_open_decks}</b> decks still open today. Consistency moves us forward fastest right now."
            coach_items.append(f"<li><b>{t('Offene Decks zuerst dicht machen:', 'Close out open decks first:')}</b> {t(open_de, open_en)}</li>")
        if low_quality_count > 0:
            dropper = APP_CONFIG["DROPPER_THRESHOLD"]
            quality_de = f"Bei <b>{low_quality_count}</b> Spielern liegt der Ø-Wert unter {dropper}. Lieber normale Kämpfe als Bootsangriffe verschwenden."
            quality_en = f"<b>{low_quality_count}</b> players have an average below {dropper}. Prefer normal battles over wasting boat attacks."
            coach_items.append(f"<li><b>{t('Kämpfe sauber ausspielen:', 'Play battles cleanly:')}</b> {t(quality_de, quality_en)}</li>")
        if teamplay_details["leecher"] > 0 or teamplay_details["sleeper"] > 0:
            leecher_n = teamplay_details["leecher"]
            sleeper_n = teamplay_details["sleeper"]
            team_de = f"Aktuell haben wir <b>{leecher_n}</b> Spieler mit auffaelligem Spendenverhalten und <b>{sleeper_n}</b> spendeninaktive Spieler. Ein paar Spenden mehr machen den Clan direkt runder."
            team_en = f"We currently have <b>{leecher_n}</b> players with notable donation behavior and <b>{sleeper_n}</b> donation-inactive players. A few more donations make the clan instantly more rounded."
            coach_items.append(f"<li><b>{t('Mehr Teamplay hilft sofort:', 'More teamplay helps immediately:')}</b> {t(team_de, team_en)}</li>")
        if newbie_count > 0 or low_score_count > 0:
            coach_items.append(f"<li><b>{t('Sauber statt kompliziert:', 'Clean instead of complicated:')}</b> {t('Auch mit Erfahrung bringen im Krieg oft klar aufgebaute, verlaesslich spielbare Decks mehr Konstanz als sehr spezielle Listen. Erst sauber ausspielen, dann experimentieren.', 'Even with experience, clearly built, reliably playable decks often bring more consistency in war than very special lists. Play cleanly first, then experiment.')}</li>")

        coach_html = ""
        if coach_items:
            coach_html = f"<div class='info-box' style='border-left-color: #10b981;'><h3 style='margin-top:0; color:#10b981;'>🧠 {t('Coach-Ecke', 'Coach Corner')}</h3><p style='margin-top:0;'>{t('Hinweise und Prognose für den aktuellen Stand:', 'Notes and forecast for the current state:')}</p><ul style='margin-bottom:0;'>" + "".join(coach_items[:6]) + "</ul></div>"

    kandidaten_demote = strikes_data.get("demoted_this_week", [])
    kandidaten_kick = strikes_data.get("kicked_this_week", [])

    top_pusher_list = sorted(
        [p for p in aktive_spieler if p["trophy_push"] > 0],
        key=lambda x: x["trophy_push"],
        reverse=True
    )[:3]
    if top_pusher_list:
        pusher_html = "".join([f"<li><b>{p['name']}</b> (+{p['trophy_push']} 🏆)</li>" for p in top_pusher_list])
        pusher_chat = f"🚀 Top-Pusher: {top_pusher_list[0]['name']} (+{top_pusher_list[0]['trophy_push']}🏆)"
    else:
        pusher_html = "<li>Niemand</li>"
        pusher_chat = ""

    urlaub_html = "<li>Niemand</li>"
    if urlauber_liste:
        urlaub_html = "".join([f"<li>🏖️ <b>{u}</b></li>" for u in urlauber_liste])

    radar_html = ""
    if radar_clans:
        _state_i18n = {
            "Clankrieg":   t("Clankrieg",   "Clan War"),
            "Colosseum":   "Colosseum",
            "Trainingstag": t("Trainingstag", "Training Day"),
        }
        radar_hint = f" <span style='font-size:0.8em; opacity:0.8; font-weight:normal;'>(Status: {_state_i18n.get(race_state_de, race_state_de)})</span>"
        radar_html = f"<div class='info-box' style='border-left-color: #f43f5e; background: rgba(159, 18, 57, 0.15); margin-bottom: 25px;'><h3 style='margin-top: 0; color: #f43f5e; margin-bottom: 12px; font-size: 1.2em;'>📡 {t('Live Kriegs-Radar', 'Live War Radar')}{radar_hint}</h3>"
        radar_html += "<div style='overflow-x: auto;'><table class='radar-table' style='width: 100%; border-collapse: collapse; font-size: 0.95em; table-layout: fixed;'>"
        radar_html += "<colgroup><col style='width:30%'><col style='width:14%'><col style='width:18%'><col style='width:18%'><col style='width:20%'></colgroup>"
        radar_html += f"<tr style='border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-weight: 600; text-align: left;'><td style='padding-bottom: 8px; border: none; text-align: left;'>{t('Clan', 'Clan')}</td><td style='padding-bottom: 8px; border: none; text-align: center;'>⛵ {t('Boot', 'Boat')}</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🥇 {t('Medaille', 'Medal')}</td><td style='padding-bottom: 8px; border: none; text-align: center;'>⚡ {t('Effizienz', 'Efficiency')}</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🏆 {t('Trophäe', 'Trophy')}</td></tr>"

        for idx, c in enumerate(radar_clans):
            bold_name = f"<b style='color:#fff;'>{c['name']} (WIR)</b>" if c["is_us"] else c["name"]
            bg_color = "rgba(255,255,255,0.05)" if idx % 2 == 0 else "transparent"
            medals_heute = c.get("medals_heute")
            if medals_heute is not None and c['decks_used'] > 0:
                effizienz = round(medals_heute / c['decks_used'])
                effizienz_str = str(effizienz)
            elif medals_heute is None and c['decks_used'] > 0:
                effizienz_str = "<span style='color:#64748b; font-size:0.85em;'>~</span>"
            else:
                effizienz_str = "–"
            radar_html += f"<tr style='background: {bg_color}; border-bottom: 1px solid rgba(255,255,255,0.02);'>"
            radar_html += f"<td style='padding: 10px 5px;'>{bold_name}<br><span style='font-size: 0.8em; color: #cbd5e1;'>🃏 {c['decks_used']} / {c.get('max_decks', 200)} Decks</span></td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #f8fafc;'>{c['boat_attacks']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #fbbf24;'>{c['medals']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #22d3ee;'>{effizienz_str}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #c084fc;'>{c['trophies']}</td>"
            radar_html += "</tr>"
        radar_html += "</table></div></div>"

    mahnwache_html = ""
    ist_kampftag = race_state_de in ("Clankrieg", "Colosseum")

    total_active_players = len(aktive_spieler)
    total_decks_today = total_active_players * 4
    total_open_decks = 0
    hype_balken_html = ""

    if ist_kampftag:
        aktive_namen_list = df_active["player_name"].tolist()
        raw_mahnwache.sort(key=lambda x: x["offen"], reverse=True)
        gefilterte_mahnwache = []
        mahnwache_colors = MAHNWACHE_COLORS
        mahnwache_idx = 0
        for m in raw_mahnwache:
            if m["name"].lower() not in urlauber_liste_lower and m["name"] in aktive_namen_list:
                name_color = mahnwache_colors[mahnwache_idx % len(mahnwache_colors)]
                offen_label = t(f"({m['offen']} offen)", f"({m['offen']} open)")
                gefilterte_mahnwache.append(
                    f"<span style='color:{name_color}; font-weight:800;'>{m['name']}</span> "
                    f"<span style='color:#ffffff;'>{offen_label}</span>"
                )
                mahnwache_idx += 1
                total_open_decks += m["offen"]

        if gefilterte_mahnwache:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #ef4444; background: rgba(239, 68, 68, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #ef4444; margin-bottom: 8px;'>⏰ {t('Mahnwache (Noch offene Decks heute):', 'Vigil (Decks still open today):')}</h4><p style='margin: 0; font-size: 0.95em;'>{', '.join(gefilterte_mahnwache)}</p></div>"
        else:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #10b981; background: rgba(16, 185, 129, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #10b981; margin-bottom: 0;'>✅ {t('Alle aktiven Spieler haben ihre Decks für heute gespielt!', 'All active players have played their decks for today!')}</h4></div>"

        played_decks_today = total_decks_today - total_open_decks
        hype_percentage = int((played_decks_today / total_decks_today) * 100) if total_decks_today > 0 else 0
        hype_color = "#ef4444" if hype_percentage < 50 else "#fbbf24" if hype_percentage < 90 else "#10b981"

        tagesziel_titel = ("🎯 " + t("Tagesziel: Trainings-Kämpfe", "Daily Goal: Training Battles")) if "Training" in race_state_de else ("🎯 " + t("Tagesziel: Clan-Kriegs Kämpfe", "Daily Goal: Clan War Battles"))

        hype_balken_html = f"""
        <div style='background: rgba(30, 41, 59, 0.8); border-radius: 12px; padding: 20px; margin-bottom: 25px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 15px rgba(0,0,0,0.2);'>
            <div style='display: flex; justify-content: space-between; margin-bottom: 10px; align-items: baseline;'>
                <h3 style='margin: 0; color: #f8fafc; font-size: 1.1em;'>{tagesziel_titel}</h3>
                <span style='font-weight: bold; color: {hype_color}; font-size: 1.1em;'>{played_decks_today} / {total_decks_today} {t('Decks', 'decks')} ({hype_percentage}%)</span>
            </div>
            <div style='background: rgba(0,0,0,0.5); border-radius: 8px; height: 14px; width: 100%; overflow: hidden;'>
                <div style='background: {hype_color}; width: {hype_percentage}%; height: 100%; border-radius: 8px; transition: width 1s ease-in-out;'></div>
            </div>
        </div>
        """

    cr_top_names = ", ".join([p["name"] for p in top_performers_list])
    top_spender_names = ", ".join([p["name"] for p in top_spender_list][:2])
    echte_leecher = [p for p in top_leecher_list if p["donations"] == 0 and p["donations_received"] > 0]
    leecher_names = ", ".join([p["name"] for p in echte_leecher][:2]) if echte_leecher else ""

    chat_blocks = []

    for chunk in chunk_list(echte_neulinge, 3):
        names_str = ", ".join(chunk)
        welcome_vars = {
            "Sachlich": f"👋 Moin {names_str}, willkommen bei uns im Clan. Alles Wichtige findet ihr unter {CLAN_URL}",
            "Motivierend": f"🎉 Moin {names_str}, herzlich willkommen in der {CLAN_NAME}-Family! Alles Wichtige findet ihr unter {CLAN_URL}",
            "Kurz & Knackig": f"👋 Moin {names_str}, willkommen im Clan! Alles Wichtige: {CLAN_URL}"
        }
        chat_blocks.append(welcome_vars)

    for chunk in chunk_list(rueckkehrer, 3):
        names_str = ", ".join(chunk)
        rueckkehrer_vars = {
            "Sachlich": f"👋 Moin {names_str}, willkommen zurück. Schön, dass ihr wieder da seid.",
            "Motivierend": f"🎉 Moin {names_str}, nice dass ihr wieder am Start seid! Willkommen zurück in der HAMBURG-Family.",
            "Kurz & Knackig": f"👋 Willkommen zurück {names_str}! Schön, euch wieder im Clan zu haben."
        }
        chat_blocks.append(rueckkehrer_vars)

    for chunk in chunk_list(warn_rueckkehrer, 3):
        names_str = ", ".join(chunk)
        rueckkehrer_vars = {
            "Sachlich": f"⚠️ Info an die Vizes: {names_str} ist wieder da. Bitte die Aktivität in den nächsten Wochen etwas im Blick behalten.",
            "Motivierend": f"👀 {names_str} ist wieder am Start. Geben wir der Sache eine faire neue Chance und schauen auf die Aktivität.",
            "Kurz & Knackig": f"⚠️ Hinweis: {names_str} ist wieder da. Aktivität bitte im Auge behalten."
        }
        chat_blocks.append(rueckkehrer_vars)

    msg_1_vars = {
        "Sachlich": f"📊 Clan-Ø: {clan_avg}%. MVPs: {cr_top_names} 🏆 {pusher_chat}",
        "Motivierend": f"🔥 Super Leistung! Clan-Ø: {clan_avg}%. Ein dickes Danke an unsere MVPs: {cr_top_names}! {pusher_chat}",
        "Kurz & Knackig": f"⚔️ Auswertung da! Schnitt: {clan_avg}%. Top 3: {cr_top_names}. {pusher_chat}"
    }
    chat_blocks.append(msg_1_vars)

    msg_2_sachlich = f"🃏 Ein Lob an unsere Top-Spender: {top_spender_names}! 🤝" if top_spender_list else "🃏 Kaum Spenden diese Woche. Ein Clan lebt vom Geben UND Nehmen! 🤝"
    if echte_leecher:
        msg_2_sachlich += f" | 📦 Spenden auffällig: {leecher_names}."
    msg_2_motiv = f"💚 Wahnsinn, was ihr spendet! Top-Supporter: {top_spender_names}. Danke fürs Karten teilen!" if top_spender_list else "💚 Vergesst das Spenden nicht, Team! Jeder braucht mal Karten."
    msg_2_streng = f"⚠️ Spenden-Check: Danke an {top_spender_names}." if top_spender_list else "⚠️ Null Spenden-Moral diese Woche!"
    if echte_leecher:
        msg_2_streng += f" Spenden auffällig: {leecher_names}. Bitte wieder etwas mehr mitgeben."

    msg_2_vars = {
        "Sachlich": msg_2_sachlich,
        "Motivierend": msg_2_motiv,
        "Kurz & Knackig": msg_2_streng
    }
    chat_blocks.append(msg_2_vars)

    dropper_names = [
        p["name"] for p in aktive_spieler
        if 0 < p["fame_per_deck"] < APP_CONFIG["DROPPER_THRESHOLD"] and not p["is_urlaub"]
    ]
    if dropper_names:
        names_str = ", ".join(dropper_names)
        dropper_vars = {
            "Sachlich": f"⚠️ Hinweis an {names_str}: Euer Punkteschnitt pro Deck ist aktuell auffällig niedrig (<{APP_CONFIG['DROPPER_THRESHOLD']}). Bitte setzt eure Decks möglichst in normalen Kämpfen oder Duellen ein. Jeder Punkt hilft dem Clan. ⚔️",
            "Motivierend": f"💡 Kleiner Tipp an {names_str}: Normale Kämpfe oder Duelle bringen dem Clan meist deutlich mehr als Spezialangriffe. Spielt eure Decks am besten sauber in den Standard-Modi aus. 💪",
            "Kurz & Knackig": f"⚠️ Hinweis an {names_str}: Bitte Decks möglichst in normalen Kämpfen oder Duellen ausspielen. Das bringt dem Clan meist mehr Punkte."
        }
        chat_blocks.append(dropper_vars)

    for chunk in chunk_list(kandidaten_demote, 4):
        names_str = ", ".join(chunk)
        demote_vars = {
            "Sachlich": f"👇 Interne Maßnahme: {names_str}. Grund: über längere Zeit zu wenig Kriegsaktivität. Jetzt gilt eine neue Bewährungsphase. ⚔️",
            "Motivierend": f"👇 Bei {names_str} ziehen wir intern eine Stufe nach unten, damit wieder mehr Verlässlichkeit reinkommt. Jetzt zählt die nächste Phase. ⚔️",
            "Kurz & Knackig": f"👇 Interner Hinweis: {names_str} werden intern eine Stufe tiefer eingeordnet. ⚔️"
        }
        chat_blocks.append(demote_vars)

    for chunk in chunk_list(kandidaten_kick, 4):
        names_str = ", ".join(chunk)
        kick_vars = {
            "Sachlich": f"👋 Verabschiedung: {names_str}. Grund: über längere Zeit zu wenig Kriegsaktivität. Wir wünschen euch alles Gute! ✌️",
            "Motivierend": f"👋 Wir verabschieden {names_str} und wünschen alles Gute. Danke für die gemeinsame Zeit! ✌️",
            "Kurz & Knackig": f"👋 Verabschiedung: {names_str}. Alles Gute! ✌️"
        }
        chat_blocks.append(kick_vars)

    if not kandidaten_demote and not kandidaten_kick:
        nokick_vars = {
            "Sachlich": "🛡️ Info: Keine Kicks oder Degradierungen! Alle haben zuverlässig gekämpft oder sich fair abgemeldet. Starkes Team! 💪",
            "Motivierend": "🌟 Großartig! Niemand auf der Kick-Liste diese Woche. Danke für eure Disziplin und Zuverlässigkeit! 💪",
            "Kurz & Knackig": "🛡️ Alles sauber: Keine Kicks diese Woche! 💪"
        }
        chat_blocks.append(nokick_vars)

    total_msgs = len(chat_blocks)
    colors = CHAT_COLORS
    chat_boxes_html = ""

    for i, block_vars in enumerate(chat_blocks):
        color = colors[i % len(colors)]
        options_html = ""
        prefix = f"{i + 1}/{total_msgs} "
        for style_name, text_content in block_vars.items():
            final_text = enforce_chat_limit(text_content, prefix=prefix)
            safe_text = escape_for_html(final_text)
            options_html += f'<option value="{safe_text}">{style_name}</option>'

        default_text = enforce_chat_limit(list(block_vars.values())[0], prefix=prefix)

        chat_boxes_html += f"""
        <div style="margin-bottom: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                <label style="color: {color}; font-weight: bold; font-size: 0.9em;">💬 Teil {i+1}/{total_msgs}:</label>
                <select onchange="document.getElementById('chatbox_{i}').value = this.value" style="background: rgba(30, 41, 59, 0.9); color: #cbd5e1; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 2px 6px; font-family: inherit; font-size: 0.85em; cursor: pointer;">
                    {options_html}
                </select>
            </div>
            <textarea id="chatbox_{i}" readonly style="width: 100%; height: 50px; background: rgba(0,0,0,0.4); color: #fff; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 8px; font-family: inherit; font-size: 0.95em; resize: none;">{default_text}</textarea>
        </div>
        """

    deck_html = ""
    deck_sections = build_deck_sections(top_decks_data)
    has_any_decks = any(section["decks"] for section in deck_sections)

    if not has_any_decks:
        deck_html = f"<div class='info-box' style='border-left-color: #64748b;'><p style='margin: 0;'><b>Noch nicht genug Daten gesammelt.</b><br>Das System wertet Kriegs-Decks aus den letzten {DECK_LOOKBACK_DAYS} Tagen aus. Schau in ein paar Tagen wieder vorbei, dann füllen sich hier Meta-, solide und einsteigerfreundliche Decks.</p></div>"
    else:
        for section in deck_sections:
            if not section["decks"]:
                continue

            section_cards_html = ""
            for idx, d in enumerate(section["decks"], start=1):
                players_str = ", ".join(d["players"][:3]) + ("..." if len(d["players"]) > 3 else "")
                api_names = [c["name"].lower().replace(".", "").replace(" ", "-") for c in d["cards"]]
                royaleapi_link = f"https://royaleapi.com/decks/stats/{','.join(api_names)}"

                images_html = "".join([
                    f"<img src='{c['icon']}' style='width: 23%; border-radius: 4px; margin: 1%;' title='{c['name']}'>"
                    for c in d["cards"]
                ])

                section_cards_html += f"""
                <div class="deck-card">
                    <div class="archetype-badge">{d['archetype']}</div>
                    <div class="deck-header">
                        <h3 style="margin: 0; color: #f97316; font-size: 1.1em; font-weight: 800;">{section['title']} #{idx}</h3>
                        <span class="winrate">🔥 {d['winrate']}% Win</span>
                    </div>
                    <div class="deck-images">
                        {images_html}
                    </div>
                    <p style="font-size: 0.85em; color: #94a3b8; margin: 10px 0;">{d['wins']} {t('Siege', 'wins')} / {d['losses']} {t('Niederlagen', 'losses')} {t('in', 'in')} {d['total_matches']} {t('Spielen', 'games')}<br><span style="color:#e2e8f0; font-weight:bold;">{t('Oft gewonnen von:', 'Often won by:')} {players_str}</span></p>
                    <div style="margin-top: auto; display: flex; flex-direction: column; gap: 8px;">
                        <a href="{royaleapi_link}" class="copy-btn" style="background: #38bdf8; color: #0f172a;" target="_blank">🔗 {t('Auf RoyaleAPI öffnen & kopieren', 'Open & copy on RoyaleAPI')}</a>
                    </div>
                </div>
                """

            deck_html += f"""
            <div style="margin-bottom: 30px;">
                <h3 style="color: #f8fafc; margin-bottom: 8px; font-size: 1.3em;">{section['title']}</h3>
                <p style="color: #94a3b8; margin-top: 0; margin-bottom: 18px; font-size: 0.95em;">{section['description']}</p>
                <div class="deck-slider">
                    {section_cards_html}
                </div>
            </div>
            """


    tiers = [
        t("Sehr stark", "Very Strong"),
        t("Solide Basis", "Solid Base"),
        t("Mehr drin", "Underperforming"),
        t("Ausbaufaehig", "Room to Grow"),
        "🏖️ " + t("Abgemeldet / Im Urlaub (Pausiert)", "Logged Off / On Vacation (Paused)")
    ]

    table_html = ""
    for tier_name in tiers:
        players_in_tier = sorted(
            [p for p in player_stats if p["tier"] == tier_name],
            key=lambda x: (x["teilnahme_int"], x["fame_per_deck"], x["war_points_total"]),
            reverse=True
        )
        if players_in_tier:
            table_html += "<div class='tier-section'>"
            table_html += f"<div class='tier-title'>{tier_name}</div>"
            table_html += """<table>
                <thead>
                <tr>
                    <th><span class="i18n-de">Spieler</span><span class="i18n-en">Player</span></th>
                    <th><span class="i18n-de">Check</span><span class="i18n-en">Check</span></th>
                    <th><span class="i18n-de">Status</span><span class="i18n-en">Status</span></th>
                    <th><span class="i18n-de">Dabei</span><span class="i18n-en">Present</span></th>
                    <th><span class="i18n-de">Deck-Nutzung</span><span class="i18n-en">Deck Usage</span></th>
                    <th><span class="i18n-de">Ø Fame/Deck</span><span class="i18n-en">Avg Fame/Deck</span></th>
                    <th><span class="i18n-de">Fame gesamt</span><span class="i18n-en">Total Fame</span></th>
                    <th><span class="i18n-de">Trend</span><span class="i18n-en">Trend</span></th>
                    <th>🃏 <span class="i18n-de">Spenden</span><span class="i18n-en">Donations</span></th>
                </tr>
                </thead>
                <tbody>"""

            for p in players_in_tier:
                spenden_warnung = ""
                if p["donations"] == 0 and p["teilnahme_int"] > APP_CONFIG["MIN_PARTICIPATION"] and not p["is_urlaub"]:
                    if p["donations_received"] > 0:
                        spenden_warnung = f" <span class='custom-tooltip' style='font-size: 1.1em;'>📦<span class='tooltip-text'>Spenden auffällig (0 gespendet, aber {p['donations_received']} erhalten)</span></span>"
                    else:
                        spenden_warnung = " <span class='custom-tooltip' style='font-size: 1.1em;'>💤<span class='tooltip-text'>Spenden inaktiv (0 gespendet, 0 erhalten)</span></span>"

                spenden_zelle = f"<span class='custom-tooltip dotted'>{p['donations']}<span class='tooltip-text'>Gespendet: {p['donations']} | Empfangen: {p['donations_received']}</span></span>"
                spenden_block = f"<span class='spenden-cell'><span>{spenden_zelle}</span><span class='spenden-extra'>{spenden_warnung}</span></span>" if spenden_warnung else spenden_zelle

                # Boot-Angriff-Badge
                boat_badge = ""
                if p.get("boat_attacks", 0) > 0:
                    boat_badge = f" <span class='custom-tooltip' style='font-size: 0.9em;'>⛵<span class='tooltip-text'>Boot-Angriffe: {p['boat_attacks']}</span></span>"

                # Spieler-Profil-Tooltip
                profile_tooltip = ""
                if p.get("win_rate", 0) > 0 or p.get("best_trophies", 0) > 0:
                    tt_parts = []
                    if p.get("exp_level", 0) > 0:
                        tt_parts.append(f"Level: {p['exp_level']}")
                    if p.get("best_trophies", 0) > 0:
                        tt_parts.append(f"Best: {p['best_trophies']} 🏆")
                    if p.get("win_rate", 0) > 0:
                        tt_parts.append(f"Winrate: {p['win_rate']}%")
                    if p.get("challenge_max_wins", 0) > 0:
                        tt_parts.append(f"Challenge-Max: {p['challenge_max_wins']}")
                    if p.get("war_day_wins", 0) > 0:
                        tt_parts.append(f"Kriegssiege: {p['war_day_wins']}")
                    if p.get("favourite_card"):
                        tt_parts.append(f"Lieblingskarte: {p['favourite_card']}")
                    if tt_parts:
                        profile_tooltip = f" <span class='custom-tooltip' style='font-size: 0.85em; cursor: help;'>ℹ️<span class='tooltip-text'>{'<br>'.join(tt_parts)}</span></span>"

                name_cell = f"{p['name']}{p['welpenschutz_badge']}{p['streak_badge']}{p['strike_badge']}{boat_badge}{profile_tooltip}"

                # Dabei-Farbe: grün wenn volle Teilnahme, gelb wenn ok, rot wenn wenig
                dabei_wars  = p["teilnahme_int"]
                dabei_total = p["wars_in_window"]
                dabei_rate  = (dabei_wars / dabei_total) if dabei_total > 0 else 0
                dabei_color = "#10b981" if dabei_rate >= 0.8 else "#fbbf24" if dabei_rate >= 0.5 else "#ef4444"
                if p["is_welpenschutz"]:
                    dabei_color = "#60a5fa"

                # Ø Fame/Deck Farbe
                fpd = p["fame_per_deck"]
                fpd_color = "#10b981" if fpd >= APP_CONFIG.get("BADGE_STARK_FAME", 162) else "#fbbf24" if fpd >= APP_CONFIG.get("DROPPER_THRESHOLD", 130) else "#ef4444"

                # Fame gesamt formatiert
                fame_total = p.get("war_points_total", 0)
                fame_total_str = f"{fame_total:,}".replace(",", ".")

                # Deck-Nutzung: gespielt / maximum | Farbe: >=90%=grün, >=70%=gelb, sonst rot
                deck_vollst = p.get("deck_vollstaendigkeit", 0.0)
                max_decks = p.get("max_moegliche_decks", 0)
                total_decks_played = p.get("total_decks", 0)
                deck_color = "#10b981" if deck_vollst >= 0.90 else "#fbbf24" if deck_vollst >= 0.70 else "#ef4444"
                deck_label = "Decksets" if max_decks > 0 else "-"

                table_html += (
                    f"<tr>"
                    f"<td class='name-col'><span class='name-inline'>{name_cell}</span></td>"
                    f"<td>{p['focus_badge']}</td>"
                    f"<td>{p['status']}</td>"
                    f"<td style='white-space:nowrap;'>"
                    f"<span style='font-weight:800; color:{dabei_color};'>{dabei_wars}/{dabei_total}</span>"
                    f"<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Kriege aktiv</span><span class='i18n-en'>Wars active</span></span>"
                    f"</td>"
                    f"<td style='white-space:nowrap;'>"
                    f"<span style='font-weight:800; color:{deck_color};'>{total_decks_played}/{max_decks}</span>"
                    f"<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Decks gespielt</span><span class='i18n-en'>Decks played</span></span>"
                    f"</td>"
                    f"<td style='white-space:nowrap;'>"
                    f"<span style='font-weight:800; color:{fpd_color};'>{fpd}</span>{p['leecher_warnung']}"
                    f"<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>Ø pro Deck</span><span class='i18n-en'>Avg per deck</span></span>"
                    f"</td>"
                    f"<td style='white-space:nowrap;'>"
                    f"<span style='font-weight:700; color:#c4b5fd;'>{fame_total_str}</span>"
                    f"<br><span style='font-size:0.75em; color:#64748b;'><span class='i18n-de'>30 Tage</span><span class='i18n-en'>30 days</span></span>"
                    f"</td>"
                    f"<td class='trend-cell'>{p['trend_str']}</td>"
                    f"<td style='color:#38bdf8; font-weight:bold;'>{spenden_block}</td>"
                    f"</tr>"
                )

            table_html += "</tbody></table></div>"

    keys_to_delete = []
    for s_name in strikes.keys():
        if s_name not in aktive_namen_set:
            keys_to_delete.append(s_name)
    for k in keys_to_delete:
        del strikes[k]

    impressum_html, datenschutz_html = build_legal_pages()

    # ── Clan-Steckbrief (clan_overview_html) ──
    clan_overview_html = ""
    if clan_overview:
        co = clan_overview

        # Ranking-Trend berechnen
        local_rank = co.get("local_rank")
        prev_rank_data = records.get("clan_war_rank", {})
        prev_rank = prev_rank_data.get("rank")
        rank_html = ""
        if local_rank:
            rank_trend = ""
            if prev_rank and prev_rank > 0:
                rank_delta = prev_rank - local_rank  # positiv = aufgestiegen
                if rank_delta > 0:
                    rank_trend = f"<div style='color: #10b981; font-size: 0.8em;'>↑ +{rank_delta} {t('Plätze', 'places')}</div>"
                elif rank_delta < 0:
                    rank_trend = f"<div style='color: #ef4444; font-size: 0.8em;'>↓ {rank_delta} {t('Plätze', 'places')}</div>"
                else:
                    rank_trend = f"<div style='color: #94a3b8; font-size: 0.8em;'>→ {t('unverändert', 'unchanged')}</div>"
            rank_html = f"""
                <div style="text-align: center;">
                    <div style="font-size: 1.6em; font-weight: 800; color: #c084fc;">#{local_rank}</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">🏅 {t('Rang (DE)', 'Rank (DE)')}</div>
                    {rank_trend}
                </div>"""

        # Liga-Anzeige
        league_name = co.get("war_league_name", "")
        league_html = ""
        if league_name:
            league_html = f"""
                <div style="text-align: center;">
                    <div style="font-size: 1.2em; font-weight: 700; color: #fbbf24;">{league_name}</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">Kriegsliga</div>
                </div>"""

        # Ranking beim Weekly Run speichern
        if is_weekly_run and local_rank:
            records["clan_war_rank"] = {"rank": local_rank, "trophies": co.get("clan_war_trophies", 0)}

        clan_overview_html = f"""
        <div class="info-box" style="border-left-color: #c084fc; background: rgba(192, 132, 252, 0.08); margin-bottom: 25px; padding: 20px 25px;">
            <h3 style="margin-top: 0; color: #c084fc; margin-bottom: 15px; font-size: 1.2em;">🏰 {t('Clan-Steckbrief', 'Clan Profile')}</h3>
            <div style="display: grid; grid-template-columns: repeat({'4' if local_rank else '3'}, 1fr); gap: 12px;">
                <div style="text-align: center;">
                    <div style="font-size: 1.6em; font-weight: 800; color: #f97316;">{co.get('clan_war_trophies', 0)}</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">{t('Kriegstrophäen', 'War Trophies')}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 1.6em; font-weight: 800; color: #38bdf8;">{co.get('donations_per_week', 0)}</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">{t('Spenden/Woche', 'Donations/week')}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 1.6em; font-weight: 800; color: #10b981;">{co.get('member_count', 0)}/50</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">{t('Mitglieder', 'Members')}</div>
                </div>
                {rank_html}
            </div>
            <div style="margin-top: 12px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;">
                <div style="text-align: center;">
                    <div style="font-size: 1.2em; font-weight: 700; color: #e2e8f0;">{co.get('clan_score', 0)}</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">{t('Clan-Score', 'Clan Score')}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 1.2em; font-weight: 700; color: #e2e8f0;">{co.get('required_trophies', 0)} 🏆</div>
                    <div style="color: #94a3b8; font-size: 0.85em;">{t('Min. Trophäen', 'Min. Trophies')}</div>
                </div>
                {league_html}
            </div>
        </div>
        """

    # ── Gegner-Decks gegen die wir am häufigsten verlieren ──
    opponent_meta_html = ""
    top_opp = build_top_opponent_decks(opponent_decks, top_n=10)
    if top_opp:
        rank_medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        opp_decks_html = ""
        for opp in top_opp:
            medal = rank_medals.get(opp["rank"], f"#{opp['rank']}")
            images_html = "".join([
                f"<img src='{c['icon']}' style='width: 23%; border-radius: 4px; margin: 1%;' title='{c['name']}'>"
                for c in opp["cards"]
            ])
            api_names = [c["name"].lower().replace(".", "").replace(" ", "-") for c in opp["cards"]]
            royaleapi_link = f"https://royaleapi.com/decks/stats/{','.join(api_names)}"
            opp_decks_html += f"""
            <div style="margin-bottom: 30px; border-left: 3px solid #ef4444; padding-left: 16px;">
                <h4 style="color: #fca5a5; margin: 0 0 4px 0; font-size: 1.1em;">{medal} {t('Platz', 'Rank')} {opp['rank']} <span style="color:#64748b; font-weight:400; font-size:0.9em;">— {opp['losses']} {t('Niederlagen', 'losses')} / {opp['seen']} {t('Kämpfe', 'battles')} ({opp['loss_rate']}% {t('Verlustrate', 'loss rate')})</span></h4>
                <div class="deck-slider">
                    <div class="deck-card">
                        <div class="archetype-badge">{opp['archetype']}</div>
                        <div class="deck-header">
                            <h3 style="margin: 0; color: #ef4444; font-size: 1.1em; font-weight: 800;">{t('Gegner-Deck', 'Opponent Deck')} #{opp['rank']}</h3>
                            <span class="winrate" style="background: rgba(239,68,68,0.15); color: #fca5a5;">💀 {opp['loss_rate']}% Loss</span>
                        </div>
                        <div class="deck-images">{images_html}</div>
                        <p style="font-size: 0.85em; color: #94a3b8; margin: 10px 0;">{opp['losses']} {t('Niederlagen', 'losses')} / {opp['seen']} {t('Kämpfe gegen dieses Deck', 'battles vs this deck')}</p>
                        <div style="margin-top: auto;">
                            <a href="{royaleapi_link}" class="copy-btn" style="background: #ef4444; color: #fff;" target="_blank">🔗 {t('Auf RoyaleAPI öffnen', 'Open on RoyaleAPI')}</a>
                        </div>
                    </div>
                </div>
            </div>
            """
        opponent_meta_html = f"""
        <div style="margin-bottom: 30px;">
            <h3 style="color: #fca5a5; margin-bottom: 8px; font-size: 1.3em;">🛡️ {t('Top 10 Gegner-Decks', 'Top 10 Opponent Decks')}</h3>
            <p style="color: #94a3b8; margin-top: 0; margin-bottom: 18px; font-size: 0.95em;">
                {t('Gegner-Decks gegen die unser Clan im Krieg am häufigsten verliert. Nutzt das als Hinweis, um eure Decks gezielt anzupassen.', 'Opponent decks our clan loses to most often in war. Use as a hint to adjust your decks accordingly.')}
            </p>
            {opp_decks_html}
        </div>
        """

    anzeige_stand = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y, %H:%M Uhr")

    html = render_html_template(
        clan_name=CLAN_NAME,
        heute_datum=anzeige_stand,
        header_img_src=header_img_src,
        hype_balken_html=hype_balken_html,
        radar_html=radar_html,
        mahnwache_html=mahnwache_html,
        clan_ampel_html=clan_ampel_html,
        weekly_summary_html=weekly_summary_html,
        coach_html=coach_html,
        clan_avg=clan_avg,
        clan_avg_points_per_deck=clan_avg_points_per_deck,
        top_performers=top_performers_html,
        top_spender=top_spender_html,
        pusher_html=pusher_html,
        pusher_chat=pusher_chat,
        records=records,
        urlaub_html=urlaub_html,
        top_aufsteiger=top_aufsteiger_html,
        top_leecher=top_leecher_html,
        total_msgs=total_msgs,
        chat_boxes_html=chat_boxes_html,
        table_html=table_html,
        deck_html=deck_html,
        impressum_html=impressum_html,
        datenschutz_html=datenschutz_html,
        clan_overview_html=clan_overview_html,
        opponent_meta_html=opponent_meta_html
    )

    default_mail_texts = [list(block.values())[0] for block in chat_blocks]
    mail_chat_text = "\n\n".join([
        enforce_chat_limit(text, prefix=f"{i + 1}/{total_msgs} ")
        for i, text in enumerate(default_mail_texts)
    ])

    strikes_data["players"] = strikes
    return html, df_history, mail_chat_text, records, strikes_data, kicked_players

def write_static_legal_pages(impressumhtml: str, datenschutzhtml: str) -> None:
    def wrap_legal_page(title: str, body_html: str) -> str:
        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: Arial, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      line-height: 1.7;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      background: rgba(15, 23, 42, 0.92);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      padding: 28px;
      box-sizing: border-box;
    }}
    .legal-page {{
      background: transparent;
      padding: 0;
      border: 0;
      border-radius: 0;
      color: #e2e8f0;
    }}
    .legal-page h2 {{
      margin-top: 0;
      color: #f8fafc;
    }}
    .legal-page h3 {{
      color: #38bdf8;
    }}
    .legal-page a {{
      color: #38bdf8;
    }}
    .legal-section {{
      margin-top: 24px;
    }}
    .legal-warning {{
      background: rgba(251, 191, 36, 0.12);
      border-left: 4px solid #fbbf24;
      color: #fde68a;
      padding: 14px 16px;
      border-radius: 8px;
      margin-bottom: 20px;
    }}
  </style>
</head>
<body>
  <main class="container">
    {body_html}
  </main>
</body>
</html>"""

    impressum_path = BASE_DIR / "impressum.html"
    datenschutz_path = BASE_DIR / "datenschutz.html"

    with impressum_path.open("w", encoding="utf-8") as f:
        f.write(wrap_legal_page("Impressum", impressumhtml))

    with datenschutz_path.open("w", encoding="utf-8") as f:
        f.write(wrap_legal_page("Datenschutzerklärung", datenschutzhtml))


def speichere_html_bericht(
    html_content: str,
    df_history: pd.DataFrame,
    records: dict,
    strikes_data: dict,
    file_suffix: str,
    top_decks_data: dict,
    kicked_players: dict,
    impressumhtml: str,
    datenschutzhtml: str,
    player_war_decks: dict = None
) -> Path:
    html_path = output_folder / f"auswertung_{file_suffix}.html"
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html_content)

    index_path = BASE_DIR / "index.html"
    with index_path.open("w", encoding="utf-8") as f:
        f.write(html_content)

    df_history.to_csv(score_history_path, index=False)

    with open(records_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=4)

    with open(strikes_path, "w", encoding="utf-8") as f:
        json.dump(strikes_data, f, ensure_ascii=False, indent=4)

    with open(top_decks_path, "w", encoding="utf-8") as f:
        json.dump(top_decks_data, f, ensure_ascii=False, indent=4)

    if player_war_decks is not None:
        with open(player_war_decks_path, "w", encoding="utf-8") as f:
            json.dump(player_war_decks, f, ensure_ascii=False, indent=4)

    with open(kicked_players_path, "w", encoding="utf-8") as f:
        json.dump(kicked_players, f, ensure_ascii=False, indent=4)

    write_static_legal_pages(impressumhtml, datenschutzhtml)

    return html_path


def archiviere_alte_auswertungen(output_dir: Path, anzahl: int = 2, max_archiv: int = 10):
    archiv_output = output_dir / "archiv"
    archiv_output.mkdir(exist_ok=True, parents=True)
    alte_htmls = sorted(output_dir.glob("auswertung_*.html"), key=os.path.getctime)
    for file in alte_htmls[:-anzahl]:
        shutil.move(str(file), archiv_output / file.name)

    # --- ARCHIV CLEANUP (Physisch löschen) ---
    archiv_dateien = sorted(archiv_output.glob("auswertung_*.html"), key=os.path.getctime)
    for datei in archiv_dateien[:-max_archiv]:
        try:
            datei.unlink()
        except Exception:
            pass


def sende_bericht_per_mail(
    absender: str,
    empfaenger: str,
    smtp_server: str,
    port: int,
    passwort: str,
    html_path: Path,
    all_chat_texts: str
):
    pass


def main():
    upload_folder.mkdir(parents=True, exist_ok=True)
    archiv_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)
    run_mode = os.environ.get("RUN_MODE", "radar").strip().lower()
    is_weekly_run = run_mode == "weekly"

    print("=== STARTE CLAN-DATEN ABRUF ===")
    success, current_members = fetch_and_build_player_csv()
    if not success:
        return

    _, opted_out_tags, opted_out_names = load_website_opt_outs()

    kicked_players = {}
    if kicked_players_path.exists():
        try:
            with open(kicked_players_path, "r", encoding="utf-8") as f:
                kicked_players = json.load(f)
        except Exception as e:
            print(f"⚠️ Warnung: kicked_players.json fehlerhaft ({e})")

    member_memory = load_member_memory()
    current_known_players = member_memory.get("current_players", {})
    ever_seen_players = member_memory.get("ever_seen_players", {})
    pending_events = member_memory.get("pending_events", [])
    now_utc = datetime.now(timezone.utc)
    pending_cutoff = now_utc - timedelta(hours=JOIN_EVENT_TTL_HOURS)

    neue_tags = [tag for tag in current_members.keys() if tag not in current_known_players]
    pending_event_keys = {
        (event.get("tag"), event.get("type"))
        for event in pending_events
        if isinstance(event, dict)
    }

    fresh_pending_events = []
    for event in pending_events:
        if not isinstance(event, dict):
            continue
        event_tag = event.get("tag")
        event_type = event.get("type")
        detected_at = event.get("detected_at")
        if event_tag not in current_members or event_type not in {"new", "returning", "warn_returning"}:
            continue
        try:
            detected_dt = datetime.strptime(detected_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if detected_dt >= pending_cutoff:
            fresh_pending_events.append({
                "tag": event_tag,
                "name": current_members[event_tag]["name"],
                "type": event_type,
                "detected_at": detected_at
            })

    echte_neulinge = []
    rueckkehrer = []
    warn_rueckkehrer = []
    for event in fresh_pending_events:
        player_name = event["name"]
        if event["type"] == "warn_returning":
            warn_rueckkehrer.append(player_name)
        elif event["type"] == "returning":
            rueckkehrer.append(player_name)
        elif event["type"] == "new":
            echte_neulinge.append(player_name)

    for tag in neue_tags:
        player_name = current_members[tag]["name"]
        if player_name in kicked_players:
            if (tag, "warn_returning") not in pending_event_keys:
                fresh_pending_events.append({
                    "tag": tag,
                    "name": player_name,
                    "type": "warn_returning",
                    "detected_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                })
            warn_rueckkehrer.append(player_name)
        elif tag in ever_seen_players:
            if (tag, "returning") not in pending_event_keys:
                fresh_pending_events.append({
                    "tag": tag,
                    "name": player_name,
                    "type": "returning",
                    "detected_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                })
            rueckkehrer.append(player_name)
        else:
            if (tag, "new") not in pending_event_keys:
                fresh_pending_events.append({
                    "tag": tag,
                    "name": player_name,
                    "type": "new",
                    "detected_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                })
            echte_neulinge.append(player_name)

    updated_current_players = {}
    updated_ever_seen_players = dict(ever_seen_players)
    for tag, data in current_members.items():
        previous_entry = current_known_players.get(tag, ever_seen_players.get(tag, {}))
        player_entry = {
            "name": data["name"],
            "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "first_seen": previous_entry.get("first_seen", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        }
        updated_current_players[tag] = player_entry
        updated_ever_seen_players[tag] = player_entry

    save_member_memory({
        "current_players": updated_current_players,
        "ever_seen_players": updated_ever_seen_players,
        "pending_events": fresh_pending_events
    })

    print("Schritt 3: Rufe Live-Radar (Current River Race) ab...")
    radar_clans = []
    race_state_de = get_river_race_status_de()
    raw_mahnwache = []
    current_war_participants = {}  # tag → decksUsedToday

    try:
        headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
        race_resp = requests.get(f"{BASE_URL}/clans/{CLAN_TAG}/currentriverrace", headers=headers, timeout=30)
        if race_resp.status_code == 200:
            data = race_resp.json()

            # Echten Status aus API lesen statt Wochentag-Schätzung
            period_type = data.get("periodType", "")
            if period_type == "colosseum":
                race_state_de = "Colosseum"
            elif period_type == "warDay":
                race_state_de = "Clankrieg"
            else:
                race_state_de = "Trainingstag"

            clans_in_race = data.get("clans", [])
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            radar_cache = load_war_radar_cache()
            new_radar_cache = {}

            for c in clans_in_race:
                is_us = c.get("tag") == CLAN_TAG.replace("%23", "#")
                clan_tag_raw = c.get("tag", "")

                trophies = c.get("clanScore", 0)
                participants = c.get("participants", [])
                # Colosseum: periodPoints ist immer 0, Fame steckt in participants[].fame
                # Regulärer Clankrieg: periodPoints = Punkte des aktuellen Tages (setzt täglich zurück)
                period_points = c.get("periodPoints", 0)
                if period_type == "colosseum" and period_points == 0:
                    medals = sum(p.get("fame", 0) for p in participants)
                else:
                    medals = period_points
                boat_attacks = sum(p.get("boatAttacks", 0) for p in participants)
                decks_used = sum(p.get("decksUsedToday", 0) for p in participants)

                # Colosseum: kein täglicher Reset → medals direkt als Gesamtwert verwenden
                if period_type == "colosseum":
                    medals_heute = medals  # Gesamte Fame seit Colosseum-Start
                    new_radar_cache[clan_tag_raw] = {"date": today_str, "baseline": 0}
                else:
                    # Delta-Effizienz: medals_heute = periodPoints - Tagesbasis
                    cache_entry = radar_cache.get(clan_tag_raw, {})
                    if cache_entry.get("date") != today_str:
                        # Erster Run des Tages → Tagesbasis setzen
                        medals_heute = None  # noch unbekannt
                        new_radar_cache[clan_tag_raw] = {"date": today_str, "baseline": medals}
                    else:
                        baseline = cache_entry.get("baseline", medals)
                        medals_heute = max(0, medals - baseline)
                        new_radar_cache[clan_tag_raw] = cache_entry  # unverändert behalten

                if is_us:
                    member_count = len(current_members)
                else:
                    try:
                        clan_tag_encoded = clan_tag_raw.replace("#", "%23")
                        clan_resp = requests.get(f"{BASE_URL}/clans/{clan_tag_encoded}", headers=headers, timeout=15)
                        if clan_resp.status_code == 200:
                            member_count = clan_resp.json().get("members", 50)
                        else:
                            member_count = min(len(participants), 50)
                    except Exception:
                        member_count = min(len(participants), 50)
                radar_clans.append({
                    "name": c.get("name", ""),
                    "is_us": is_us,
                    "trophies": trophies,
                    "medals": medals,
                    "medals_heute": medals_heute,
                    "boat_attacks": boat_attacks,
                    "decks_used": decks_used,
                    "max_decks": member_count * 4
                })

                if is_us:
                    for p in participants:
                        decks_today = p.get("decksUsedToday", 0)
                        if decks_today < 4:
                            raw_mahnwache.append({"name": p.get("name"), "offen": 4 - decks_today})
                        ptag = p.get("tag", "").lstrip("#")
                        if ptag and decks_today > 0:
                            current_war_participants[ptag] = decks_today

            save_war_radar_cache(new_radar_cache)

            radar_clans.sort(key=lambda x: (x["medals"], x["boat_attacks"], x["trophies"]), reverse=True)
    except Exception as e:
        print(f"Warnung: Radar konnte nicht geladen werden ({e})")

    top_decks_data = {}
    if top_decks_path.exists():
        try:
            with open(top_decks_path, "r", encoding="utf-8") as f:
                top_decks_data = json.load(f)
        except Exception as e:
            print(f"⚠️ Warnung: top_decks.json fehlerhaft, fange bei 0 an. ({e})")

    player_war_decks = {}
    if player_war_decks_path.exists():
        try:
            with open(player_war_decks_path, "r", encoding="utf-8") as f:
                player_war_decks = json.load(f)
        except Exception as e:
            print(f"⚠️ Warnung: player_war_decks.json fehlerhaft, fange bei 0 an. ({e})")

    top_decks_data, opponent_decks, player_war_decks = update_top_decks(current_members, top_decks_data, player_war_decks)

    print("Schritt 5.5: Rufe Clan-Gesamtdaten und Spieler-Profile ab...")
    clan_overview = fetch_clan_overview()
    player_profiles = fetch_player_profiles(current_members)

    records = {"donations": {"name": "-", "val": 0}, "delta": {"name": "-", "val": 0}, "trophies": {"name": "-", "val": 0}}
    if records_path.exists():
        try:
            with open(records_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                records.update(loaded)
        except Exception as e:
            print(f"⚠️ Warnung: records.json fehlerhaft, fange bei 0 an. ({e})")

    strikes_data = {
        "last_strike_week": 0,
        "players": {},
        "demoted_this_week": [],
        "kicked_this_week": []
    }
    if strikes_path.exists():
        try:
            with open(strikes_path, "r", encoding="utf-8") as f:
                loaded_strikes = json.load(f)
                if "players" in loaded_strikes:
                    strikes_data.update(loaded_strikes)
                else:
                    strikes_data["players"] = loaded_strikes
        except Exception as e:
            print(f"⚠️ Warnung: strikes.json fehlerhaft, fange bei 0 an. ({e})")

    print("=== STARTE AUSWERTUNG ===")
    archiviere_alte_dateien(upload_folder, archiv_folder)

    try:
        csv_path = finde_neueste_csv(upload_folder)
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"❌ Fehler beim CSV lesen: {e}")
        return

    is_current_mask = df["player_is_current_member"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
    df_active = df[is_current_mask].copy()
    if not df_active.empty:
        visible_mask = ~df_active.apply(
            lambda row: is_player_opted_out(
                tag=row.get("player_tag", ""),
                name=row.get("player_name", ""),
                opted_out_tags=opted_out_tags,
                opted_out_names=opted_out_names
            ),
            axis=1
        )
        df_active = df_active[visible_mask].copy()

    fame_columns = sorted([col for col in df.columns if col.startswith("s_") and col.endswith("_fame")], reverse=True)
    if not fame_columns:
        print("❌ Keine Fame-Spalten gefunden.")
        return
    fame_spalte = fame_columns[0]

    raw_mahnwache = [
        item for item in raw_mahnwache
        if not is_player_opted_out(name=item.get("name", ""), opted_out_tags=opted_out_tags, opted_out_names=opted_out_names)
    ]

    echte_neulinge = [name for name in echte_neulinge if not is_player_opted_out(name=name, opted_out_tags=opted_out_tags, opted_out_names=opted_out_names)]
    rueckkehrer = [name for name in rueckkehrer if not is_player_opted_out(name=name, opted_out_tags=opted_out_tags, opted_out_names=opted_out_names)]
    warn_rueckkehrer = [name for name in warn_rueckkehrer if not is_player_opted_out(name=name, opted_out_tags=opted_out_tags, opted_out_names=opted_out_names)]

    top_decks_data = sanitize_top_decks_for_website(top_decks_data, opted_out_tags, opted_out_names)

    if score_history_path.exists():
        df_history = pd.read_csv(score_history_path)
        if "trophies" not in df_history.columns:
            df_history["trophies"] = 0
    else:
        df_history = pd.DataFrame(columns=["player_name", "score", "date", "trophies"])

    heute_datum = datetime.today().strftime("%Y-%m-%d")
    jetzt_datei = datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
    encoded_header_img = get_encoded_header_image(HEADER_IMAGE_PATH)

    html_bericht, df_history, mail_chat_text, updated_records, updated_strikes_data, updated_kicked = generate_html_report(
        df_active=df_active,
        df_history=df_history,
        fame_spalte=fame_spalte,
        heute_datum=heute_datum,
        header_img_src=encoded_header_img,
        radar_clans=radar_clans,
        records=records,
        strikes_data=strikes_data,
        race_state_de=race_state_de,
        raw_mahnwache=raw_mahnwache,
        top_decks_data=top_decks_data,
        echte_neulinge=echte_neulinge,
        rueckkehrer=rueckkehrer,
        warn_rueckkehrer=warn_rueckkehrer,
        kicked_players=kicked_players,
        is_weekly_run=is_weekly_run,
        clan_overview=clan_overview,
        player_profiles=player_profiles,
        opponent_decks=opponent_decks,
        player_war_decks=player_war_decks,
        current_war_participants=current_war_participants,
    )

    impressumhtml, datenschutzhtml = build_legal_pages()

    html_path = speichere_html_bericht(
        html_content=html_bericht,
        df_history=df_history,
        records=updated_records,
        strikes_data=updated_strikes_data,
        file_suffix=jetzt_datei,
        top_decks_data=top_decks_data,
        kicked_players=updated_kicked,
        impressumhtml=impressumhtml,
        datenschutzhtml=datenschutzhtml,
        player_war_decks=player_war_decks,
    )
    archiviere_alte_auswertungen(output_folder)

    sender_mail = os.environ.get("EMAIL_SENDER")
    receiver_mail = os.environ.get("EMAIL_RECEIVER")
    email_pass = os.environ.get("EMAIL_PASS")

    if sender_mail and receiver_mail and email_pass:
        if is_weekly_run:
            print("=== BERICHT WURDE GENERIERT ===")
            print("💡 Testmodus aktiv: HTML und Layout wurden erfolgreich erstellt, E-Mail-Versand ist vorerst deaktiviert.")
            print(f"HTML-Bericht gespeichert unter: {html_path}")
            print(f"Chat-Text vorbereitet:\n{mail_chat_text}")
        else:
            print("\n💡 Info: Radar aktualisiert. Wochenhistorie und E-Mail-Versand wurden im Radar-Modus übersprungen.")
    else:
        print("\n⚠️ HINWEIS: E-Mail-Secrets fehlen, Versand nicht möglich.")

    print("\n=== ALLES ERFOLGREICH ABGESCHLOSSEN ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n❌ EIN KRITISCHER FEHLER IST AUFGETRETEN:")
        traceback.print_exc()
        sys.exit(1) 
 
