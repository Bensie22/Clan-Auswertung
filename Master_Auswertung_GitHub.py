import os
import glob
import shutil
import requests
import csv
import base64
import json
import sys
import time
import traceback
import html
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from pathlib import Path
import pandas as pd
from email.message import EmailMessage
import smtplib

# === 1. Konfiguration & Pfade ===

APP_CONFIG = {
    "STRIKE_THRESHOLD": 50,      # Score in %: Unter diesem Wert gibt es eine Verwarnung
    "DROPPER_THRESHOLD": 115,    # Ø Punkte pro Deck: Unter diesem Wert Warnung wg. Bootsangriff/Aufgabe
    "MIN_PARTICIPATION": 3       # Welpenschutz: Bis einschließlich 3 Teilnahmen keine Strafen
}

JOIN_EVENT_TTL_HOURS = 24

DECK_LOOKBACK_DAYS = 30
DECK_META_MIN_MATCHES = 5
DECK_SOLID_MIN_MATCHES = 4
DECK_BEGINNER_MIN_MATCHES = 3

# API Settings (Token & E-Mails kommen sicher aus den Secrets!)
API_TOKEN = os.environ.get("SUPERCELL_API_TOKEN")
CLAN_TAG = "%23Y9YQC8UG"
CLAN_NAME = "HAMBURG"
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
donations_memory_path = BASE_DIR / "donations_memory.json"
member_memory_path = BASE_DIR / "member_memory.json"
urlaub_path = BASE_DIR / "urlaub.txt"
kicked_players_path = BASE_DIR / "kicked_players.json"
HEADER_IMAGE_PATH = BASE_DIR / "clash_pix.jpg"


def safe_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def build_legal_pages() -> Tuple[str, str]:
    site_name = safe_env("IMPRESSUM_SITE_NAME", CLAN_NAME)
    owner_name = safe_env("IMPRESSUM_OWNER_NAME")
    street = safe_env("IMPRESSUM_STREET")
    city = safe_env("IMPRESSUM_CITY")
    phone = safe_env("IMPRESSUM_PHONE")
    legal_email = safe_env("IMPRESSUM_EMAIL", safe_env("EMAIL_SENDER"))
    website_url = safe_env("IMPRESSUM_WEBSITE_URL", "https://www.houseofnames.com/diener/german/p/family-crest-download-heritage-series-300")
    responsible_name = safe_env("IMPRESSUM_RESPONSIBLE_NAME", owner_name)
    responsible_street = safe_env("IMPRESSUM_RESPONSIBLE_STREET", street)
    responsible_city = safe_env("IMPRESSUM_RESPONSIBLE_CITY", city)

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

    phone_html = f"<p><b>Telefon:</b> {html.escape(phone)}</p>" if phone else ""
    website_html = f"<p><b>Website:</b> <a href='{html.escape(website_url)}' target='_blank' rel='noopener noreferrer'>{html.escape(website_url)}</a></p>" if website_url else ""

    impressum_html = f"""
        <div class="legal-page">
            {setup_notice}
            <h2>Impressum</h2>
            <p><b>Angaben gemäß § 5 DDG</b></p>
            <div class="legal-section">
                <p><b>{html.escape(site_name)}</b></p>
                <p>{html.escape(owner_name)}</p>
                <p>{html.escape(street)}</p>
                <p>{html.escape(city)}</p>
            </div>
            <div class="legal-section">
                <h3>Kontakt</h3>
                {phone_html}
                <p><b>E-Mail:</b> <a href='mailto:{html.escape(legal_email)}'>{html.escape(legal_email)}</a></p>
                {website_html}
            </div>
            <div class="legal-section">
                <h3>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h3>
                <p>{html.escape(responsible_name)}</p>
                <p>{html.escape(responsible_street)}</p>
                <p>{html.escape(responsible_city)}</p>
            </div>
            <div class="legal-section">
                <h3>EU-Streitschlichtung</h3>
                <p>Die Europäische Kommission stellt eine Plattform zur Online-Streitbeilegung (OS) bereit: <a href="https://ec.europa.eu/consumers/odr/" target="_blank" rel="noopener noreferrer">https://ec.europa.eu/consumers/odr/</a>.</p>
                <p>Unsere E-Mail-Adresse finden Sie oben im Impressum.</p>
            </div>
            <div class="legal-section">
                <h3>Verbraucherstreitbeilegung/Universalschlichtungsstelle</h3>
                <p>Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
            </div>
        </div>
    """

    datenschutz_html = f"""
        <div class="legal-page">
            <h2>Datenschutzerklärung</h2>
            <p>Diese Website ist eine statische Informationsseite des Clans <b>{html.escape(site_name)}</b>. Sie dient zur Anzeige von Clan-, Kriegs- und Statistikdaten.</p>
            <div class="legal-section">
                <h3>1. Verantwortliche Stelle</h3>
                <p>{html.escape(owner_name)}</p>
                <p>{html.escape(street)}</p>
                <p>{html.escape(city)}</p>
                <p><b>E-Mail:</b> <a href='mailto:{html.escape(legal_email)}'>{html.escape(legal_email)}</a></p>
            </div>
            <div class="legal-section">
                <h3>2. Welche Daten verarbeitet werden</h3>
                <p>Auf dieser Website werden vor allem spielbezogene Daten dargestellt, etwa Ingame-Namen, Rollen, Trophäen, Spendenwerte sowie Kriegs- und Aktivitätsstatistiken.</p>
                <p>Beim Aufruf der Website können technisch notwendige Verbindungsdaten verarbeitet werden, insbesondere IP-Adresse, Datum und Uhrzeit des Zugriffs sowie Browser- und Gerätedaten. Solche Daten fallen typischerweise im Rahmen des Hostings an.</p>
            </div>
            <div class="legal-section">
                <h3>3. Zweck der Verarbeitung</h3>
                <p>Die Verarbeitung erfolgt, um die Clan-Auswertung bereitzustellen, die Website technisch auszuliefern und den sicheren Betrieb der Seite zu gewährleisten.</p>
            </div>
            <div class="legal-section">
                <h3>4. Hosting</h3>
                <p>Diese Website wird über GitHub Pages bereitgestellt. Weitere Informationen dazu findest du hier: <a href="https://docs.github.com/de/pages/getting-started-with-github-pages/what-is-github-pages" target="_blank" rel="noopener noreferrer">GitHub Pages</a>.</p>
                <p>Ergänzend gilt die allgemeine Datenschutzerklärung von GitHub: <a href="https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub Datenschutzerklärung</a>.</p>
            </div>
            <div class="legal-section">
                <h3>5. Cookies und Tracking</h3>
                <p>Diese Website verwendet nach aktuellem Stand keine eigenen Cookies, kein Kontaktformular und kein eigenes Analyse- oder Tracking-Tool.</p>
            </div>
            <div class="legal-section">
                <h3>6. Rechte betroffener Personen</h3>
                <p>Betroffene Personen haben im Rahmen der gesetzlichen Vorschriften insbesondere ein Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung und Beschwerde bei einer zuständigen Datenschutzaufsichtsbehörde.</p>
            </div>
            <div class="legal-section">
                <h3>7. Kontakt zum Datenschutz</h3>
                <p>Bei Fragen zum Datenschutz auf dieser Website kannst du dich an <a href='mailto:{html.escape(legal_email)}'>{html.escape(legal_email)}</a> wenden.</p>
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

    now = datetime.utcnow()
    curr_week = now.isocalendar()[1]

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

                players_data[ptag]["history"][race_id] = {"decks": decks, "fame": fame}

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

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = upload_folder / f"clan_export_{date_str}.csv"

    race_ids = sorted(list(set(race_ids)), reverse=True)
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
        "player_total_decks_used"
    ]

    for rid in race_ids:
        headers_csv.extend([f"s_{rid}_fame", f"s_{rid}_decks_used"])

    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers_csv)
        total_races = len(race_ids)

        for tag, data in players_data.items():
            total_decks = 0
            contribution_count = 0
            row_history = []

            for rid in race_ids:
                r_data = data["history"].get(rid, {"decks": 0, "fame": 0})
                decks = r_data["decks"]
                fame = r_data["fame"]
                row_history.extend([fame, decks])

                total_decks += decks
                if decks > 0:
                    contribution_count += 1

            row = [
                tag,
                data["name"],
                data["is_current"],
                data["role"],
                data.get("donations", 0),
                data.get("donations_received", 0),
                data.get("trophies", 0),
                contribution_count,
                total_races,
                total_decks
            ]
            row.extend(row_history)
            writer.writerow(row)

    print(f"✅ Spieler-Daten erfolgreich exportiert nach: {filename}\n")
    return True, current_members


# === 2.5 Battlelogs analysieren (Top Decks) ===

def update_top_decks(current_members: dict, top_decks_data: dict) -> dict:
    print("Schritt 4: Spioniere Battlelogs für Clan-Meta Decks aus (Bitte warten)...")
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}

    metadata = top_decks_data.get("_metadata", {"last_battles": {}})
    decks = top_decks_data.get("decks", {})
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

            if "riverRace" in b_type and "team" in battle:
                team = battle["team"][0]
                opponent = battle["opponent"][0]
                cards = team.get("cards", [])

                if len(cards) == 8:
                    crowns_t = team.get("crowns", 0)
                    crowns_o = opponent.get("crowns", 0)

                    is_win = crowns_t > crowns_o
                    is_loss = crowns_o > crowns_t

                    if is_win or is_loss:
                        deck_ids = sorted([str(c["id"]) for c in cards])
                        deck_hash = "-".join(deck_ids)
                        raw_tag = tag.replace("#", "")

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
        sorted_keys = sorted(
            decks.keys(),
            key=lambda k: (
                get_deck_winrate(decks[k]),
                decks[k]["wins"] + decks[k]["losses"],
                decks[k]["wins"]
            ),
            reverse=True
        )
        for k in sorted_keys[100:]:
            del decks[k]

    top_decks_data["_metadata"] = metadata
    top_decks_data["decks"] = decks
    print("✅ Battlelogs erfolgreich gescannt. Top-Decks aktualisiert.\n")
    return top_decks_data


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
    for deck_data in top_decks_data.get("decks", {}).values():
        total_matches = deck_data.get("wins", 0) + deck_data.get("losses", 0)
        if total_matches <= 0:
            continue

        deck_copy = dict(deck_data)
        deck_copy["total_matches"] = total_matches
        deck_copy["winrate"] = int(round(get_deck_winrate(deck_data) * 100))
        deck_copy["archetype"] = get_deck_archetype(deck_data.get("cards", []))
        deck_copy["is_beginner_friendly"] = is_beginner_friendly_deck(deck_data.get("cards", []))
        decks.append(deck_copy)

    meta_decks = sorted(
        [d for d in decks if d["total_matches"] >= DECK_META_MIN_MATCHES],
        key=lambda d: (d["winrate"], d["total_matches"], d["wins"]),
        reverse=True
    )[:4]

    solid_decks = sorted(
        [d for d in decks if d["total_matches"] >= DECK_SOLID_MIN_MATCHES and d["winrate"] >= 55],
        key=lambda d: (d["total_matches"], d["winrate"], d["wins"]),
        reverse=True
    )
    solid_decks = [d for d in solid_decks if d not in meta_decks][:4]

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
    beginner_decks = [d for d in beginner_decks if d not in meta_decks and d not in solid_decks][:4]

    return [
        {
            "title": "🏆 Meta-Decks",
            "description": f"Die stärksten und belastbarsten Kriegs-Decks aus den letzten {DECK_LOOKBACK_DAYS} Tagen.",
            "decks": meta_decks
        },
        {
            "title": "🛡️ Solide Decks",
            "description": f"Verlässliche Decks mit ordentlicher Quote und genug Spielen aus den letzten {DECK_LOOKBACK_DAYS} Tagen.",
            "decks": solid_decks
        },
        {
            "title": "🎯 Einsteigerfreundlich",
            "description": f"Einfachere Decks für Leute, die ein klares und stabiles Kriegs-Deck suchen.",
            "decks": beginner_decks
        }
    ]


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
        return "neu dabei", "#38bdf8"
    if score >= 95 and fame_per_deck >= 160:
        return "⭐ stark", "#10b981"
    if score >= 80 and fame_per_deck >= 130:
        return "🛡️ stabil", "#38bdf8"
    if score < APP_CONFIG["STRIKE_THRESHOLD"]:
        return "⚠️ ausbaufähig", "#f97316"
    if current_decks > 0 and fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"]:
        return "👀 auffällig", "#ef4444"
    return "🙂 solide", "#94a3b8"


def get_deck_archetype(cards: list) -> str:
    card_names = [c.get("name", "") for c in cards]
    if any(n in card_names for n in ["Golem", "Lava Hound", "Giant", "Goblin Giant", "Electro Giant", "Elixir Golem"]):
        return "🛡️ Schwerer Angriff (Beatdown)"
    if any(n in card_names for n in ["X-Bow", "Mortar"]):
        return "🏹 Belagerung (Siege)"
    if any(n in card_names for n in ["Goblin Barrel", "Skeleton Barrel", "Miner", "Graveyard", "Wall Breakers", "Goblin Drill"]):
        return "🗡️ Nadelstiche (Bait/Control)"
    if any(n in card_names for n in ["Hog Rider", "Royal Hogs", "Battle Ram", "Ram Rider", "Balloon"]):
        return "⚡ Schneller Angriff (Rush/Spam)"
    return "⚔️ Hybrid / Allrounder"


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
    return text.replace('"', "&quot;").replace("'", "&#39;")


def is_clan_war_period(now_utc: datetime | None = None) -> bool:
    if now_utc is None:
        now_utc = datetime.utcnow()

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
    datenschutz_html
):
    return f"""
    <html>
    <head>
        <meta charset='utf-8'>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Auswertung: {clan_name}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
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
            .tier-title {{ position: sticky; top: 73px; background: rgba(15, 23, 42, 0.98); z-index: 900; margin: 0; padding: 15px 0 10px 0; font-weight: 800; font-size: 1.4em; color: #fbbf24; border-bottom: 2px solid rgba(255,255,255,0.1); }}
            table {{ width: 100%; table-layout: fixed; border-collapse: collapse; background: rgba(15, 23, 42, 0.9); border-radius: 8px; margin-bottom: 30px; border: 1px solid rgba(255, 255, 255, 0.1); }}
            th:nth-child(1) {{ width: 20%; }}
            th:nth-child(2) {{ width: 16%; text-align: center; }}
            th:nth-child(3) {{ width: 12%; text-align: center; }}
            th:nth-child(4) {{ width: 10%; text-align: center; }}
            th:nth-child(5) {{ width: 11%; text-align: center; }}
            th:nth-child(6) {{ width: 10%; text-align: center; }}
            th:nth-child(7) {{ width: 11%; text-align: center; }}
            th:nth-child(8) {{ width: 10%; text-align: center; }}
            tr:nth-child(odd) {{ background-color: rgba(0, 0, 0, 0.45); }} tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.15); }} tr:hover {{ background-color: rgba(255, 255, 255, 0.3); }}
            th, td {{ padding: 14px 10px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; vertical-align: middle; }}
            td:nth-child(2), td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8) {{ text-align: center; }}
            th:nth-child(3), td:nth-child(3) {{ text-align: center; white-space: nowrap; }}

            th {{ position: sticky; top: 128px; background-color: #0f172a; color: #94a3b8; z-index: 800; font-weight: 600; font-size: 0.9em; border-bottom: 1px solid rgba(255,255,255,0.1); line-height: 1.4; box-shadow: 0 4px 5px rgba(0,0,0,0.3); }}
            td {{ border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 1.05em; }}

            .badge-ja {{ background-color: #10b981; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-weight: 800; font-size: 0.8em; margin-left: 8px; }}
            .name-col {{ font-weight: 800; color: #ffffff; }}
            .focus-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 104px; padding: 5px 10px; border-radius: 999px; font-size: 0.8em; font-weight: 800; white-space: nowrap; }}

            .trend-cell {{ font-size: 16px !important; white-space: nowrap; line-height: 1; }}

            .wiki-table {{ width: 100%; table-layout: fixed; border-collapse: collapse; background: rgba(0, 0, 0, 0.3); border-radius: 8px; margin: 15px 0; border: 1px solid rgba(255, 255, 255, 0.1); font-size: 0.85em; }}
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
                table:not(.radar-table) td:nth-child(4)::before, .wiki-table td:nth-child(4)::before {{ content: "Score"; }}
                table:not(.radar-table) td:nth-child(5)::before, .wiki-table td:nth-child(5)::before {{ content: "Trend"; }}
                table:not(.radar-table) td:nth-child(6)::before, .wiki-table td:nth-child(6)::before {{ content: "Ø Punkte"; }}
                table:not(.radar-table) td:nth-child(7)::before, .wiki-table td:nth-child(7)::before {{ content: "Aktive Kriege"; }}
                table:not(.radar-table) td:nth-child(8)::before, .wiki-table td:nth-child(8)::before {{ content: "Spenden"; }}
                .wiki-table td {{ font-size: 0.92em; }}
                .name-col {{ font-size: 1.05em; }}
                .focus-pill {{ min-width: 0; width: fit-content; }}
                .trend-cell {{ font-size: 18px !important; }}
                .custom-tooltip .tooltip-text {{ max-width: 220px; width: max-content; white-space: normal; }}
                table:not(.radar-table) td:nth-child(6), .wiki-table td:nth-child(6),
                table:not(.radar-table) td:nth-child(8), .wiki-table td:nth-child(8) {{ white-space: nowrap; }}
                table:not(.radar-table) td:nth-child(6) > *, .wiki-table td:nth-child(6) > *,
                table:not(.radar-table) td:nth-child(8) > *, .wiki-table td:nth-child(8) > * {{ white-space: nowrap; }}
                table:not(.radar-table) td:nth-child(8) .custom-tooltip.dotted,
                .wiki-table td:nth-child(8) .custom-tooltip.dotted {{ border-bottom: none !important; }}
                .spenden-cell .custom-tooltip.dotted {{ border-bottom: none; }}
                .radar-table {{ width: 100%; table-layout: fixed; font-size: 0.84em !important; }}
                .radar-table th {{ display: table-cell; position: static; box-shadow: none; font-size: 0.82em; padding: 8px 6px; }}
                .radar-table tbody {{ display: table-row-group; }}
                .radar-table tr {{ display: table-row; background: transparent !important; border: none; box-shadow: none; padding: 0; }}
                .radar-table td {{ display: table-cell; width: auto; padding: 10px 6px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: center !important; vertical-align: middle; }}
                .radar-table td:first-child {{ text-align: left !important; }}
                .radar-table td::before {{ content: none !important; }}
            }}
            @media (orientation: landscape) and (max-width: 1024px) {{
                body {{ background-attachment: scroll; }}
                .container {{ max-width: 100%; padding: 12px 14px; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-container">
                <h1 class="header-title"><span onclick="toggleChat()" style="cursor: pointer;" title="Chat-Hilfe ein-/ausblenden">📊</span> Clan-Auswertung: {clan_name} <br>
                <span class="header-date">{heute_datum}</span>
                <span class="header-mobile-tip">📱 Tipp: Für die beste Übersicht am Handy bitte quer halten 🔄</span></h1>
            </div>

            <div class="tab-container">
                <button class="tab-btn active" onclick="openTab(event, 'Overview')">🏠 Übersicht</button>
                <button class="tab-btn" onclick="openTab(event, 'Table')">📋 Detail-Auswertung</button>
                <button class="tab-btn" onclick="openTab(event, 'Wiki')">📖 Regeln & System</button>
                <button class="tab-btn" onclick="openTab(event, 'Decks')">🃏 Top-Decks</button>
            </div>

            <div id="Overview" class="tab-content active">
                <div class="welcome-box">
                    <h2 class="welcome-title">Willkommen bei der HAMBURG-Family! 🤝</h2>
                    <p>Schön, dass du über unsere Clan-Info hierher gefunden hast. Egal ob du schon ewig dabei bist oder gerade erst überlegst, uns beizutreten: Schau dich in Ruhe um!</p>
                    <p>Ein starker Clan braucht aktive Mitglieder. Auf dieser Seite tracken wir jede Woche transparent unseren Erfolg im Clankrieg und unsere Spendenbereitschaft.</p>
                    <p>Wir sind eine entspannte, aber ehrgeizige Truppe. Bei uns zählt Verlässlichkeit mehr als reine Trophäen. Wenn du einen dauerhaft aktiven Clan suchst und deine 4 Decks verlässlich spielst, bist du bei uns genau <b>richtig</b>! 🛡️</p>
                </div>

                {hype_balken_html}

                {radar_html}
                {mahnwache_html}
                {clan_ampel_html}
                {weekly_summary_html}
                {coach_html}

                <div class="dashboard">
                    <div class="card avg">
                        <h3>📈 Clan-Durchschnitt</h3>
                        <h1>{clan_avg}%</h1>
                    </div>
                    <div class="card avg">
                        <h3>⚔️ Clan-Ø Punkte</h3>
                        <h1>{clan_avg_points_per_deck}</h1>
                    </div>
                    <div class="card top">
                        <h3>🏆 Top 3 Performer</h3>
                        <ul>{top_performers}</ul>
                    </div>
                    <div class="card spender">
                        <h3>🃏 Top 3 Spender</h3>
                        <ul>{top_spender}</ul>
                    </div>
                    <div class="card pusher">
                        <h3>🚀 Trophäen-Pusher</h3>
                        <ul>{pusher_html}</ul>
                    </div>
                    <div class="card hof">
                        <h3>📖 Hall of Fame (Ewig)</h3>
                        <ul style="font-size: 0.95em;">
                            <li><b>Spenden-Gott:</b> {records['donations']['name']} ({records['donations']['val']})</li>
                            <li><b>Max Trophäen:</b> {records['trophies']['name']} ({records['trophies']['val']} 🏆)</li>
                            <li><b>Mega-Comeback:</b> {records['delta']['name']} (+{records['delta']['val']}%)</li>
                        </ul>
                    </div>
                    <div class="card urlaub">
                        <h3>🏖️ Aktuell im Urlaub</h3>
                        <ul style="font-size: 0.95em;">{urlaub_html}</ul>
                    </div>
                    <div class="card aufsteiger">
                        <h3>🚀 Größte Aufsteiger</h3>
                        <ul>{top_aufsteiger}</ul>
                    </div>
                    <div class="card leecher">
                        <h3>📦 Spenden auffällig</h3>
                        <ul>{top_leecher}</ul>
                    </div>

                    <div id="admin-chat-container" style="display: none; width: 100%;">
                        <div class="card messenger">
                            <h3 style="color: #f1c40f; margin-bottom: 10px;">🎮 Chat-Hilfe ({total_msgs}-Teiler)</h3>
                            <p style="font-size: 0.9em; color: #cbd5e1; margin-top: 0; margin-bottom: 15px;">Klicke oben auf das 📊-Symbol, um diese Hilfe ein- oder auszublenden. Wähle den passenden Tonfall und kopiere dann die {total_msgs} Texte nacheinander in den Chat.</p>
                            {chat_boxes_html}
                        </div>
                    </div>

                </div>
            </div>

            <div id="Table" class="tab-content">
                <div style="background: rgba(30, 41, 59, 0.8); padding: 20px; border-radius: 8px; margin-bottom: 25px; font-size: 0.95em; border: 1px solid rgba(255,255,255,0.05); box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                    <h4 style="margin-top: 0; color: #38bdf8; margin-bottom: 5px;">📌 Schnelle Symbol-Legende:</h4>
                    <p style="margin: 0 0 15px 0; font-size: 0.9em; color: #94a3b8; font-style: italic;">Weitere Infos unter <b>📖 Regeln & System</b>.</p>
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; color: #cbd5e1;">
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🌱 Welpenschutz:</b> Neu im Clan (geschützt)</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>❌ 1/3:</b> Interner Hinweis bei längerer Inaktivität</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>📦 Spenden auffällig:</b> Fordert, spendet aber 0</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>💤 Spenden inaktiv:</b> Spendet 0, fordert 0</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>⚠️ Ø Punkte:</b> Auffällig niedriger Punkteschnitt pro Deck (&lt;115)</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🔥 Streak:</b> Mehrere Wochen 100% Score</div>
                    </div>
                </div>

                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 30px; color: #ffffff;">📋 Detail-Auswertung</h2>
                {table_html}
            </div>

            <div id="Wiki" class="tab-content">
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 30px; color: #8b5cf6;">📖 Clan-Wiki: Regeln & System</h2>

                <button class="accordion-btn">📬 Die Montags-Auswertung per E-Mail</button>
                <div class="accordion-content">
                    <p>Willst du diese Auswertung jeden Montag ganz bequem und automatisch in dein Postfach bekommen?</p>
                    <ul>
                        <li><b>Anmelden:</b> Schreib einfach eine kurze E-Mail mit deinem In-Game-Namen an: <b>strike2005-Hamburg_Royal@yahoo.com</b>. Die Clan-Führung trägt dich dann in den Verteiler ein.</li>
                        <li>🔒 <b>100% Datenschutz (BCC-Versand):</b> Keine Sorge um deine private E-Mail-Adresse! Das System verschickt die Auswertung an alle Mitglieder ausschließlich als <b>Blindkopie (BCC)</b>. Niemand im Clan kann sehen, wer sonst noch auf der Liste steht.</li>
                        <li><b>Abmelden:</b> Eine kurze Nachricht reicht, und du fliegst sofort wieder aus dem Verteiler.</li>
                    </ul>
                </div>

                <button class="accordion-btn">⚖️ Regeln bei längerer Inaktivität (❌)</button>
                <div class="accordion-content">
                    <p>Damit nicht eine einzelne schwache Woche sofort Folgen hat, arbeitet unsere Auswertung mit einem fairen Langzeit-Gedächtnis. Wer sich nicht abmeldet und im Clankrieg dauerhaft zu wenig beiträgt (Score unter 50%), sammelt im Hintergrund interne Hinweise (❌).</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler A <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'>⚠️ ausbaufähig</span></td><td>Ältester</td><td><b>49.38%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#cbd5e1;'>179</td><td>10/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>303</span></td></tr>
                            <tr><td class='name-col'>Spieler B <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'>⚠️ ausbaufähig</span></td><td>Mitglied</td><td><b>34.38%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#cbd5e1;'>100 ⚠️</td><td>4/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> 💤</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Die zweite Chance (Degradierung):</b> Wer als <i>Anführer</i>, <i>Vize</i> oder <i>Ältester</i> 3 interne Hinweise ansammelt, wird nicht sofort entfernt, sondern genau <b>eine Rang-Stufe tiefer</b> gesetzt und bekommt so eine Bewährungschance.</li>
                        <li><b>Die letzte Stufe:</b> Wenn ein normales <i>Mitglied</i> (wie <b>Spieler B</b> oben) 3 interne Hinweise erreicht, trennen wir uns. So bleibt Platz für verlässliche, aktive Spieler.</li>
                        <li><b>Wieder ins Gleichgewicht kommen:</b> Wer nach einem internen Hinweis wieder anzieht und in der Folgewoche über 50% Score holt, baut diese Einträge automatisch wieder ab.</li>
                    </ul>
                </div>

                <button class="accordion-btn">🎯 Der Score (Zuverlässigkeit & Welpenschutz)</button>
                <div class="accordion-content">
                    <p>Der Score ist die wichtigste Zahl im Dashboard. Er misst nicht, wie stark du bist oder wie viel du gewinnst, sondern <b>wie verlässlich du bist</b>.<br><br>
                    Stell dir vor, du hast für jede Kriegswochen 16 "Decks" (4 Tage × 4 Decks). Der Score zeigt einfach, wie viele deiner verfügbaren Decks du auch wirklich genutzt hast.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler C <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥 4</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>🛡️ stabil</span></td><td>Vize</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>131</td><td>10/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>146</span></td></tr>
                            <tr><td class='name-col'>Spieler D <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>neu dabei</span></td><td>Mitglied</td><td><b>6.25%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#cbd5e1;'>200</td><td>2/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>100% (Der Streak 🔥):</b> Perfekt! Du hast keinen einzigen Angriff verpasst. Schaffst du das über mehrere Wochen in Folge, erhältst du das Flammen-Symbol (wie <b>Spieler C</b> oben mit 4 Wochen am Stück!).</li>
                        <li><b>50%:</b> Du hast nur die Hälfte deiner möglichen Angriffe gemacht.</li>
                        <li><b>Welpenschutz (🌱):</b> Wenn du neu im Clan bist (wie <b>Spieler D</b> oben), fangen wir fair an. Du wirst nur an den Kriegen gemessen, bei denen du auch wirklich schon im Clan warst und bist vorerst vor Strafen geschützt.</li>
                    </ul>
                </div>

                <button class="accordion-btn">🟢🟡🔴 Der Trend (Deine Konstanz)</button>
                <div class="accordion-content">
                    <p>Die Ampel-Punkte zeigen deine Leistung (deinen Score) der letzten 4 Wochen auf einen Blick. Jeder Punkt steht für eine Woche, wobei der <b>Punkt ganz rechts die aktuellste Auswertung</b> ist.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler E</td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'>⚠️ ausbaufähig</span></td><td>Mitglied</td><td><b>45.0%</b></td><td class='trend-cell'>🟢🟢🟡🔴</td><td style='color:#cbd5e1;'>180</td><td>8/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>150</span></td></tr>
                            <tr><td class='name-col'>Spieler F</td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>🛡️ stabil</span></td><td>Ältester</td><td><b>90.0%</b></td><td class='trend-cell'>🔴🔴🟢🟢</td><td style='color:#cbd5e1;'>160</td><td>6/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>200</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>🟢 Grün (Leistungsträger):</b> Starker Score von 80% bis 100%.</li>
                        <li><b>🟡 Gelb (Mittelfeld):</b> Akzeptabler Score von 50% bis 79%, aber mit Luft nach oben.</li>
                        <li><b>🔴 Rot (Kritisch):</b> Score unter 50% (Zu wenig Teilnahme im Flussrennen).</li>
                        <li><i>Beispiel Spieler E:</i> Hat stark angefangen, aber in der letzten Woche leider stark nachgelassen (rechter Punkt ist rot).</li>
                    </ul>
                </div>

                <button class="accordion-btn">🏷️ Check-Spalte (Orientierung)</button>
                <div class="accordion-content">
                    <p>Die <b>Check</b>-Spalte ist eine kurze, leicht lesbare Orientierung auf einen Blick. Sie ersetzt keine Zahlen, sondern hilft nur dabei, Spieler schneller einzuordnen.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler P</td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'>⭐ stark</span></td><td>Ältester</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>182</td><td>10/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>220</span></td></tr>
                            <tr><td class='name-col'>Spieler Q</td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>🛡️ stabil</span></td><td>Mitglied</td><td><b>86.25%</b></td><td class='trend-cell'>🟢🟢🟡🟢</td><td style='color:#cbd5e1;'>142</td><td>9/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>95</span></td></tr>
                            <tr><td class='name-col'>Spieler R</td><td><span class='focus-pill' style='background:#94a3b822; color:#94a3b8; border:1px solid #94a3b855;'>🙂 solide</span></td><td>Mitglied</td><td><b>73.75%</b></td><td class='trend-cell'>🟡🟡🟡🟢</td><td style='color:#cbd5e1;'>150</td><td>7/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>70</span></td></tr>
                            <tr><td class='name-col'>Spieler S</td><td><span class='focus-pill' style='background:#ef444422; color:#ef4444; border:1px solid #ef444455;'>👀 auffällig</span></td><td>Mitglied</td><td><b>81.25%</b></td><td class='trend-cell'>🟢🟡🟡🟢</td><td style='color:#cbd5e1;'>102 ⚠️</td><td>9/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>40</span></td></tr>
                            <tr><td class='name-col'>Spieler T</td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'>⚠️ ausbaufähig</span></td><td>Mitglied</td><td><b>43.75%</b></td><td class='trend-cell'>🔴🔴🟡🔴</td><td style='color:#cbd5e1;'>140</td><td>4/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>30</span></td></tr>
                            <tr><td class='name-col'>Spieler U <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>neu dabei</span></td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>170</td><td>2/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>35</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>⭐ stark:</b> Sehr verlässlich und gleichzeitig stark bei den Punkten pro Deck.</li>
                        <li><b>🛡️ stabil:</b> Gute, solide Leistung ohne große Schwächen. Genau solche Spieler tragen einen Clan langfristig.</li>
                        <li><b>🙂 solide:</b> Nicht auffällig schlecht, aber auch noch nicht ganz oben. Hier ist noch Luft nach oben.</li>
                        <li><b>👀 auffällig:</b> Die Teilnahme kann okay sein, aber die Punkte pro Deck fallen gerade eher schwach aus. Hier lohnt ein genauerer Blick.</li>
                        <li><b>⚠️ ausbaufähig:</b> Die Teilnahme ist im Moment klar verbesserungswürdig. Diese Spieler liegen beim Score schon im unteren Bereich.</li>
                        <li><b>neu dabei:</b> Spieler ist noch im Welpenschutz. Deshalb wird hier noch keine harte Leistungsbewertung angesetzt.</li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ Ø Punkte (Der Qualitäts-Check)</button>
                <div class="accordion-content">
                    <p>Hier schauen wir, wie effektiv du deine Decks einsetzt. Das System teilt deine gesammelten Kriegspunkte durch die Anzahl deiner gespielten Decks.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler J <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td><span class='focus-pill' style='background:#f9731622; color:#f97316; border:1px solid #f9731655;'>⚠️ ausbaufähig</span></td><td>Ältester</td><td><b>27.34%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#cbd5e1;'>100 <span class='custom-tooltip'>⚠️</span></td><td>8/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>72</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Normalwert:</b> Selbst wenn du verlierst, bekommst du in normalen Kämpfen mindestens 115 Punkte. Ein Sieg bringt deutlich mehr.</li>
                        <li><b>⚠️ Auffälliger Bereich (&lt; 115 Punkte):</b> Wenn dein Durchschnitt unter 115 fällt, ist das ein klarer Hinweis auf zu wenig Ertrag pro Deck. Häufig steckt dahinter, dass Decks nicht in normalen Kämpfen ausgespielt werden.</li>
                    </ul>
                </div>

                <button class="accordion-btn">🃏 Spenden-Verhalten (Teamplay)</button>
                <div class="accordion-content">
                    <p>Ein starker Clan hilft sich gegenseitig beim Leveln der Karten. Deshalb schauen wir auch auf das Spendenverhalten im Clan.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler K</td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'>⭐ stark</span></td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>200</td><td>10/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>📦</span></td></tr>
                            <tr><td class='name-col'>Spieler L</td><td><span class='focus-pill' style='background:#94a3b822; color:#94a3b8; border:1px solid #94a3b855;'>🙂 solide</span></td><td>Mitglied</td><td><b>50.0%</b></td><td class='trend-cell'>🟡🟡🟡🟡</td><td style='color:#cbd5e1;'>150</td><td>5/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>💤</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>📦 Spenden auffällig:</b> Jemand fordert regelmäßig Karten an, spendet aber selbst nichts zurück.</li>
                        <li><b>💤 Spenden inaktiv:</b> Jemand spendet nicht und fordert auch nichts an.</li>
                        <li><b>Wichtig:</b> Diese Hinweise sollen nicht bloßstellen, sondern zeigen, wo im Clan noch etwas mehr Mitziehen helfen würde.</li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ Aktive Kriege (Deine Clan-Treue)</button>
                <div class="accordion-content">
                    <p>Zeigt, in wie vielen der letzten 10 Clankriege du wirklich aktiv warst, also mindestens ein Deck gespielt hast.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Check</th><th>Status</th><th>Score</th><th>Trend</th><th>Ø Punkte</th><th>Aktive Kriege</th><th>🃏 Spenden</th></tr>
                            <tr><td class='name-col'>Spieler M</td><td><span class='focus-pill' style='background:#10b98122; color:#10b981; border:1px solid #10b98155;'>⭐ stark</span></td><td>Vize</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>200</td><td>10/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>100</span></td></tr>
                            <tr><td class='name-col'>Spieler N <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td><span class='focus-pill' style='background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855;'>neu dabei</span></td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#cbd5e1;'>200</td><td>2/10</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>50</span></td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Langzeit-Aktivität:</b> Zeigt, wie treu du dem Clan über die letzten Wochen zur Seite standest.</li>
                    </ul>
                </div>

                <button class="accordion-btn">📊 Clan-Durchschnitt & ⚔️ Clan-Ø Punkte</button>
                <div class="accordion-content">
                    <p>In der Übersicht seht ihr zwei Clan-Werte, die absichtlich zwei verschiedene Fragen beantworten: <b>Wie zuverlässig spielen wir unsere Decks aus?</b> und <b>wie stark kämpfen wir pro Deck?</b></p>
                    <ul>
                        <li><b>📈 Clan-Durchschnitt:</b> Das ist der Durchschnitt aller <b>Score</b>-Werte der aktiven Mitglieder. Er zeigt also, wie zuverlässig der Clan seine verfügbaren Kriegs-Decks insgesamt nutzt.
                        Beispiel: <b>90%+</b> ist stark, weil fast alle ihre Decks sauber spielen. Ein Wert um <b>60%</b> oder darunter zeigt, dass dem Clan viele Decks fehlen.</li>
                        <li><b>⚔️ Clan-Ø Punkte:</b> Dieser Wert teilt die <b>gesamten aktuellen Kriegspunkte</b> des Clans durch die <b>gesamt gespielten Decks</b> der aktiven Mitglieder. Er zeigt also, wie stark der Clan pro eingesetztem Deck kämpft.
                        Beispiel: Ein Wert von <b>160 bis 200</b> ist ordentlich bis stark. Werte nah an <b>115</b> sind eher schwach, weil dann viele Decks kaum Ertrag bringen.</li>
                        <li><b>Unterschied:</b> Ein hoher Clan-Durchschnitt heißt, dass viele Leute ihre Decks spielen. Ein hoher Clan-Ø Punkte heißt, dass diese Decks auch qualitativ gute Punkte holen. Beides zusammen ist ideal.</li>
                        <li><b>Die Urlaubs-Regel:</b> Wenn jemand offiziell im Urlaub (🏖️) ist und pausiert, wird er aus beiden Clan-Werten komplett herausgenommen.</li>
                    </ul>
                </div>
            </div>

            <div id="Decks" class="tab-content">
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 10px; color: #ffffff;">🃏 Clan-Meta: Die besten Kriegs-Decks</h2>
                <p style="text-align: center; color: #94a3b8; margin-bottom: 30px;">Das System analysiert die Clankriegs-Kämpfe der letzten 30 Tage und sortiert sie für euch in starke Meta-Decks, solide Allrounder und einsteigerfreundliche Optionen.</p>
                <div>
                    {deck_html}
                </div>
            </div>

            <div id="Impressum" class="tab-content">
                {impressum_html}
            </div>

            <div id="Datenschutz" class="tab-content">
                {datenschutz_html}
            </div>

            <footer class="site-footer">
                <div class="footer-links">
                    <a class="footer-link" onclick="openTabByName('Impressum')">Impressum</a>
                    <a class="footer-link" onclick="openTabByName('Datenschutz')">Datenschutz</a>
                </div>
            </footer>
        </div>

        <script>
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
    is_weekly_run: bool
) -> Tuple[str, pd.DataFrame, str, dict, dict, dict]:
    player_stats = []
    urlauber_liste = []

    if urlaub_path.exists():
        with urlaub_path.open("r", encoding="utf-8") as f:
            urlauber_liste = [line.strip() for line in f if line.strip()]

    role_map = {
        "member": "Mitglied",
        "elder": "Ältester",
        "coleader": "Vize",
        "leader": "Anführer",
        "unknown": "Ehemalig"
    }

    strikes = strikes_data.get("players", {})
    last_strike_week = strikes_data.get("last_strike_week", 0)

    curr_week = datetime.utcnow().isocalendar()[1]

    apply_strikes_now = False
    if is_weekly_run:
        if last_strike_week != curr_week:
            apply_strikes_now = True
            strikes_data["last_strike_week"] = curr_week
            strikes_data["demoted_this_week"] = []
            strikes_data["kicked_this_week"] = []

    # Vorhandene Historie vorbereiten
    df_history = df_history.copy()
    if df_history.empty:
        df_history = pd.DataFrame(columns=["player_name", "score", "date", "trophies"])

    for _, row in df_active.iterrows():
        raw_role = str(row.get("player_role", "unknown")).strip().lower()
        if raw_role == "unknown":
            continue

        name = row.get("player_name", "Unbekannt")
        role_de = role_map.get(raw_role, raw_role.capitalize())
        is_urlaub = name in urlauber_liste

        wars_with_participation = int(row.get("player_contribution_count", 0) or 0)
        wars_in_history_window = int(row.get("player_participating_count", 0) or 0)
        decks_total = int(row.get("player_total_decks_used", 0) or 0)
        donations = int(row.get("player_donations", 0) or 0)
        donations_received = int(row.get("player_donations_received", 0) or 0)
        aktueller_trophy = int(row.get("player_trophies", 0) or 0)

        # Wiki-konforme Score-Logik:
        # Nur Kriege zählen, in denen tatsächlich gespielt wurde.
        max_moegliche_decks = wars_with_participation * 16
        score = round((decks_total / max_moegliche_decks) * 100, 2) if max_moegliche_decks > 0 else 0.0

        fame_columns_all = [col for col in row.index if str(col).startswith("s_") and str(col).endswith("_fame")]
        total_war_points = sum(int(row.get(col, 0) or 0) for col in fame_columns_all)

        aktueller_fame = int(row.get(fame_spalte, 0) or 0)
        aktueller_decks_spalte = fame_spalte.replace("_fame", "_decks_used")
        aktueller_decks = int(row.get(aktueller_decks_spalte, 0) or 0)
        fame_per_deck = round(aktueller_fame / aktueller_decks) if aktueller_decks > 0 else 0

        leecher_warnung = ""
        if 0 < fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"]:
            leecher_warnung = (
                " <span class='custom-tooltip'>⚠️"
                "<span class='tooltip-text'>Auffällig niedriger Ertrag pro Deck "
                "(bitte Spielweise prüfen)</span></span>"
            )

        historie_spieler = df_history[df_history["player_name"] == name].copy()
        historie_spieler = historie_spieler.sort_values("date")
        vergangene_scores = historie_spieler.tail(3)["score"].tolist()

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
            ["🟢" if s >= 80 else "🟡" if s >= APP_CONFIG["STRIKE_THRESHOLD"] else "🔴" for s in trend_scores[-4:]]
        )

        # Streak-Logik
        streak_count = 0
        for s in reversed(trend_scores):
            if s >= 100.0:
                streak_count += 1
            else:
                break

        if streak_count > wars_with_participation:
            streak_count = wars_with_participation

        streak_badge = ""
        if streak_count >= 3:
            streak_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥 {streak_count}"
                f"<span class='tooltip-text'>{streak_count} Auswertungen in Folge 100% Score!</span></span>"
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

        if apply_strikes_now and strike_val >= 3:
            if not is_urlaub:
                if raw_role in ["leader", "coleader", "elder"]:
                    strikes_data.setdefault("demoted_this_week", []).append(name)
                    strikes[name] = 2
                elif raw_role == "member":
                    strikes_data.setdefault("kicked_this_week", []).append(name)
                    kicked_players[name] = heute_datum
                    strikes[name] = 3

        strike_badge = ""
        if name in strikes_data.get("demoted_this_week", []):
            strike_badge = (
                " <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3"
                "<span class='tooltip-text'>Wurde degradiert! Bewährungschance aktiv.</span></span>"
            )
        elif name in strikes_data.get("kicked_this_week", []):
            strike_badge = (
                " <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3"
                "<span class='tooltip-text'>3 interne Hinweise: interne Maßnahme erfolgt.</span></span>"
            )
        elif strike_val > 0:
            strike_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ {strike_val}/3"
                "<span class='tooltip-text'>Interner Hinweis. Bei 3/3 folgen interne Maßnahmen.</span></span>"
            )

        # Welpenschutz-Logik
        is_welpenschutz = wars_with_participation <= APP_CONFIG["MIN_PARTICIPATION"] and not is_urlaub
        welpenschutz_badge = ""
        if is_welpenschutz:
            welpenschutz_badge = (
                " <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱"
                "<span class='tooltip-text'>Neu im Clan / Wenig Kriege / Welpenschutz aktiv</span></span>"
            )

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
            status_html = "🏖️ Urlaub"
            tier = "🏖️ Im Urlaub (Pausiert)"
        else:
            status_html = (
                f"{role_de} <span class='badge-ja'>➔ BEFÖRDERN</span>"
                if raw_role == "member" and aktueller_fame >= 2800
                else role_de
            )

            if score >= 95:
                tier = "Sehr stark (95-100%)"
            elif score >= 80:
                tier = "Solide Basis (80-94%)"
            elif score >= APP_CONFIG["STRIKE_THRESHOLD"]:
                tier = f"Mehr drin ({APP_CONFIG['STRIKE_THRESHOLD']}-79%)"
            else:
                tier = f"Ausbaufaehig (< {APP_CONFIG['STRIKE_THRESHOLD']}%)"

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
            "raw_role": raw_role
        })

        if is_weekly_run:
            df_history = pd.concat([
                df_history,
                pd.DataFrame([{
                    "player_name": name,
                    "score": score,
                    "date": heute_datum,
                    "trophies": aktueller_trophy
                }])
            ], ignore_index=True)

    aktive_spieler = [p for p in player_stats if not p["is_urlaub"]]
    clan_avg = round(sum([p["score"] for p in aktive_spieler]) / len(aktive_spieler), 2) if aktive_spieler else 0
    clan_total_fame = sum(p["fame"] for p in aktive_spieler if p["current_decks"] > 0)
    clan_total_decks = sum(p["current_decks"] for p in aktive_spieler if p["current_decks"] > 0)
    clan_avg_points_per_deck = round(clan_total_fame / clan_total_decks) if clan_total_decks > 0 else 0
    clan_teamplay, teamplay_details = calculate_teamplay_score(aktive_spieler)

    # --- HISTORIE CLEANUP (Nur aktive behalten & max. die letzten 6 Wochen) ---
    aktive_namen_set = set(df_active["player_name"].tolist())
    df_history = df_history[df_history["player_name"].isin(aktive_namen_set)]
    df_history = df_history.groupby("player_name").tail(6).reset_index(drop=True)

    top_performers_list = sorted(
        aktive_spieler,
        key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]),
        reverse=True
    )[:3]

    top_aufsteiger_list = sorted(
        [p for p in aktive_spieler if p["delta"] > 0],
        key=lambda x: x["delta"],
        reverse=True
    )[:3]

    top_spender_list = sorted(
        [p for p in aktive_spieler if p["donations"] > 0],
        key=lambda x: x["donations"],
        reverse=True
    )[:3]

    top_leecher_list = sorted(
        [p for p in aktive_spieler if p["teilnahme_int"] > APP_CONFIG["MIN_PARTICIPATION"] and p["donations"] == 0 and p["donations_received"] > 0],
        key=lambda x: x["donations_received"],
        reverse=True
    )[:3]

    top_performers_html = "".join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in top_performers_list])
    top_aufsteiger_html = "".join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger_list]) if top_aufsteiger_list else "<li>Keine Verbesserungen</li>"
    top_spender_html = "".join([f"<li><b>{p['name']}</b> ({p['donations']})</li>" for p in top_spender_list]) if top_spender_list else "<li>Keine Spenden</li>"
    top_leecher_html = "".join([f"<li><b>{p['name']}</b> ({p['donations']} gesp. / {p['donations_received']} empf.)</li>" for p in top_leecher_list]) if top_leecher_list else "<li>Keine Auffälligkeiten 🎉</li>"

    reliability_state, reliability_color = get_signal_state(clan_avg, 85, 70)
    quality_state, quality_color = get_signal_state(clan_avg_points_per_deck, 160, 130)
    teamplay_state, teamplay_color = get_signal_state(clan_teamplay, 60, 35)

    clan_ampel_html = f"""
    <div class='signal-board'>
        <div class='signal-card'>
            <h4>📈 Zuverlässigkeit</h4>
            <div class='signal-value' style='color:{reliability_color};'>{reliability_state.upper()}</div>
            <div style='color:#94a3b8; font-size:0.92em;'>Bewertung des Clan-Durchschnitts</div>
            <div class='signal-state' style='color:{reliability_color};'>{reliability_state.upper()}</div>
        </div>
        <div class='signal-card'>
            <h4>⚔️ Kampfqualität</h4>
            <div class='signal-value' style='color:{quality_color};'>{quality_state.upper()}</div>
            <div style='color:#94a3b8; font-size:0.92em;'>Bewertung der Punkte pro Deck</div>
            <div class='signal-state' style='color:{quality_color};'>{quality_state.upper()}</div>
        </div>
        <div class='signal-card'>
            <h4>🤝 Teamplay</h4>
            <div class='signal-value' style='color:{teamplay_color};'>{teamplay_state.upper()}</div>
            <div style='color:#94a3b8; font-size:0.92em;'>{teamplay_details['donors']} von {len(aktive_spieler)} Aktiven spenden mit</div>
            <div class='signal-state' style='color:{teamplay_color};'>{teamplay_state.upper()}</div>
        </div>
    </div>
    """

    summary_lines = []
    if clan_avg >= 85:
        summary_lines.append("Der Clan spielt seine Decks sehr zuverlässig aus.")
    elif clan_avg >= 70:
        summary_lines.append("Die Zuverlässigkeit ist okay, aber es bleiben noch zu viele Decks liegen.")
    else:
        summary_lines.append("Beim Ausspielen der Decks verlieren wir aktuell zu viel Boden.")

    if clan_avg_points_per_deck >= 160:
        summary_lines.append("Die Kampfqualität ist stark und bringt pro Deck ordentlich Punkte.")
    elif clan_avg_points_per_deck >= 130:
        summary_lines.append("Die Kampfqualität ist solide, hat aber noch Luft nach oben.")
    else:
        summary_lines.append("Die Kämpfe bringen aktuell zu wenig Ertrag pro Deck.")

    if teamplay_state == "kritisch":
        summary_lines.append("Beim Spenden und Unterstützen im Clan ist gerade noch Luft nach oben.")
    elif teamplay_state == "okay":
        summary_lines.append("Beim Teamplay ist schon was da, aber noch nicht jeder zieht mit.")
    else:
        summary_lines.append("Auch beim Teamplay wirkt der Clan im Moment sehr geschlossen.")

    weekly_summary_html = "<div class='info-box' style='border-left-color: #fbbf24;'><h3 style='margin-top:0; color:#fbbf24;'>🧭 Wochenfazit</h3><ul style='margin:0;'>" + "".join([f"<li>{line}</li>" for line in summary_lines]) + "</ul></div>"

    aktive_namen_set = set(df_active["player_name"].tolist())
    preliminary_open_decks = sum(
        m["offen"]
        for m in raw_mahnwache
        if m["name"] not in urlauber_liste and m["name"] in aktive_namen_set
    )

    coach_items = []
    low_quality_count = sum(1 for p in aktive_spieler if p["current_decks"] > 0 and p["fame_per_deck"] < APP_CONFIG["DROPPER_THRESHOLD"])
    low_score_count = sum(1 for p in aktive_spieler if p["score"] < 80)
    newbie_count = sum(1 for p in aktive_spieler if p["is_welpenschutz"])

    if preliminary_open_decks > 0:
        coach_items.append(f"<li><b>Offene Decks zuerst dicht machen:</b> Heute sind noch <b>{preliminary_open_decks}</b> Decks offen. Konstanz bringt uns im Moment am schnellsten nach vorne.</li>")
    if low_quality_count > 0:
        coach_items.append(f"<li><b>Kämpfe sauber ausspielen:</b> Bei <b>{low_quality_count}</b> Spielern liegt der Ø-Wert unter {APP_CONFIG['DROPPER_THRESHOLD']}. Lieber normale Kämpfe als Bootsangriffe verschwenden.</li>")
    if teamplay_details["leecher"] > 0 or teamplay_details["sleeper"] > 0:
        coach_items.append(f"<li><b>Mehr Teamplay hilft sofort:</b> Aktuell haben wir <b>{teamplay_details['leecher']}</b> Spieler mit auffaelligem Spendenverhalten und <b>{teamplay_details['sleeper']}</b> spendeninaktive Spieler. Ein paar Spenden mehr machen den Clan direkt runder.</li>")
    if newbie_count > 0 or low_score_count > 0:
        coach_items.append("<li><b>Sauber statt kompliziert:</b> Auch mit Erfahrung bringen im Krieg oft klar aufgebaute, verlaesslich spielbare Decks mehr Konstanz als sehr spezielle Listen. Erst sauber ausspielen, dann experimentieren.</li>")

    coach_html = ""
    if coach_items:
        coach_html = "<div class='info-box' style='border-left-color: #10b981;'><h3 style='margin-top:0; color:#10b981;'>🧠 Coach-Ecke</h3><p style='margin-top:0;'>Ein paar einfache Wochen-Hinweise, mit denen wir als Clan direkt mehr rausholen können:</p><ul style='margin-bottom:0;'>" + "".join(coach_items[:4]) + "</ul></div>"

    kandidaten_demote = strikes_data.get("demoted_this_week", [])
    kandidaten_kick = strikes_data.get("kicked_this_week", [])

    top_pusher = sorted(aktive_spieler, key=lambda x: x["trophy_push"], reverse=True)
    if top_pusher and top_pusher[0]["trophy_push"] > 0:
        pusher_name, pusher_val = top_pusher[0]["name"], top_pusher[0]["trophy_push"]
        pusher_html = f"<li><b>{pusher_name}</b> (+{pusher_val} 🏆)</li>"
        pusher_chat = f"🚀 Top-Pusher: {pusher_name} (+{pusher_val}🏆)"
    else:
        pusher_html = "<li>Niemand</li>"
        pusher_chat = ""

    urlaub_html = "<li>Niemand</li>"
    if urlauber_liste:
        urlaub_html = "".join([f"<li>🏖️ <b>{u}</b></li>" for u in urlauber_liste])

    radar_html = ""
    if radar_clans:
        radar_hint = f" <span style='font-size:0.8em; opacity:0.8; font-weight:normal;'>(Status: {race_state_de})</span>"
        radar_html = f"<div class='info-box' style='border-left-color: #f43f5e; background: rgba(159, 18, 57, 0.15); margin-bottom: 25px;'><h3 style='margin-top: 0; color: #f43f5e; margin-bottom: 12px; font-size: 1.2em;'>📡 Live Kriegs-Radar{radar_hint}</h3>"
        radar_html += "<div style='overflow-x: auto;'><table class='radar-table' style='width: 100%; border-collapse: collapse; font-size: 0.95em;'>"
        radar_html += "<tr style='border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-weight: 600; text-align: left;'><td style='padding-bottom: 8px; border: none; text-align: left;'>Clan</td><td style='padding-bottom: 8px; border: none; text-align: center;'>⛵ Boot</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🥇 Medaille</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🏆 Trophäe</td></tr>"

        for idx, c in enumerate(radar_clans):
            bold_name = f"<b style='color:#fff;'>{c['name']} (WIR)</b>" if c["is_us"] else c["name"]
            bg_color = "rgba(255,255,255,0.05)" if idx % 2 == 0 else "transparent"
            radar_html += f"<tr style='background: {bg_color}; border-bottom: 1px solid rgba(255,255,255,0.02);'>"
            radar_html += f"<td style='padding: 10px 5px;'>{bold_name}<br><span style='font-size: 0.8em; color: #cbd5e1;'>🃏 {c['decks_used']} / 200 Decks</span></td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #f8fafc;'>{c['boat_attacks']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #fbbf24;'>{c['medals']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #c084fc;'>{c['trophies']}</td>"
            radar_html += "</tr>"
        radar_html += "</table></div></div>"

    mahnwache_html = ""
    ist_kampftag = is_clan_war_period()

    total_active_players = len(aktive_spieler)
    total_decks_today = total_active_players * 4
    total_open_decks = 0
    hype_balken_html = ""

    if ist_kampftag:
        aktive_namen_list = df_active["player_name"].tolist()
        gefilterte_mahnwache = []
        mahnwache_colors = ["#7dd3fc", "#fdba74"]
        mahnwache_idx = 0
        for m in raw_mahnwache:
            if m["name"] not in urlauber_liste and m["name"] in aktive_namen_list:
                name_color = mahnwache_colors[mahnwache_idx % len(mahnwache_colors)]
                gefilterte_mahnwache.append(
                    f"<span style='color:{name_color}; font-weight:800;'>{m['name']}</span> "
                    f"<span style='color:#ffffff;'>({m['offen']} offen)</span>"
                )
                mahnwache_idx += 1
                total_open_decks += m["offen"]

        if gefilterte_mahnwache:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #ef4444; background: rgba(239, 68, 68, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #ef4444; margin-bottom: 8px;'>⏰ Mahnwache (Noch offene Decks heute):</h4><p style='margin: 0; font-size: 0.95em;'>{', '.join(gefilterte_mahnwache)}</p></div>"
        else:
            mahnwache_html = "<div class='info-box' style='border-left-color: #10b981; background: rgba(16, 185, 129, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #10b981; margin-bottom: 0;'>✅ Alle aktiven Spieler haben ihre Decks für heute gespielt!</h4></div>"

        played_decks_today = total_decks_today - total_open_decks
        hype_percentage = int((played_decks_today / total_decks_today) * 100) if total_decks_today > 0 else 0
        hype_color = "#ef4444" if hype_percentage < 50 else "#fbbf24" if hype_percentage < 90 else "#10b981"

        tagesziel_titel = "🎯 Tagesziel: Trainings-Kämpfe" if "Training" in race_state_de else "🎯 Tagesziel: Clan-Kriegs Kämpfe"

        hype_balken_html = f"""
        <div style='background: rgba(30, 41, 59, 0.8); border-radius: 12px; padding: 20px; margin-bottom: 25px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 15px rgba(0,0,0,0.2);'>
            <div style='display: flex; justify-content: space-between; margin-bottom: 10px; align-items: baseline;'>
                <h3 style='margin: 0; color: #f8fafc; font-size: 1.1em;'>{tagesziel_titel}</h3>
                <span style='font-weight: bold; color: {hype_color}; font-size: 1.1em;'>{played_decks_today} / {total_decks_today} Decks ({hype_percentage}%)</span>
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
            "Sachlich": f"👋 Moin {names_str}, willkommen bei uns im Clan. Alles Wichtige findet ihr unter clan-hamburg.de",
            "Motivierend": f"🎉 Moin {names_str}, herzlich willkommen in der HAMBURG-Family! Alles Wichtige findet ihr unter clan-hamburg.de",
            "Kurz & Knackig": f"👋 Moin {names_str}, willkommen im Clan! Alles Wichtige: clan-hamburg.de"
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
    colors = ["#38bdf8", "#a855f7", "#ef4444", "#f97316", "#10b981", "#fbbf24", "#6366f1", "#ec4899"]
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
                    <p style="font-size: 0.85em; color: #94a3b8; margin: 10px 0;">{d['wins']} Siege / {d['losses']} Niederlagen in {d['total_matches']} Spielen<br><span style="color:#e2e8f0; font-weight:bold;">Oft gewonnen von: {players_str}</span></p>
                    <div style="margin-top: auto; display: flex; flex-direction: column; gap: 8px;">
                        <a href="{royaleapi_link}" class="copy-btn" style="background: #38bdf8; color: #0f172a;" target="_blank">🔗 Auf RoyaleAPI öffnen & kopieren</a>
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
        "Sehr stark (95-100%)",
        "Solide Basis (80-94%)",
        f"Mehr drin ({APP_CONFIG['STRIKE_THRESHOLD']}-79%)",
        f"Ausbaufaehig (< {APP_CONFIG['STRIKE_THRESHOLD']}%)",
        "Im Urlaub (Pausiert)"
    ]

    table_html = ""
    for t in tiers:
        players_in_tier = sorted(
            [p for p in player_stats if p["tier"] == t],
            key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]),
            reverse=True
        )
        if players_in_tier:
            table_html += "<div class='tier-section'>"
            table_html += f"<div class='tier-title'>{t}</div>"
            table_html += """<table>
                <thead>
                <tr>
                    <th>Spieler</th>
                    <th>Check</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Trend</th>
                    <th>Ø Punkte</th>
                    <th>Aktive Kriege</th>
                    <th>🃏 Spenden</th>
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

                table_html += (
                    f"<tr>"
                    f"<td class='name-col'><span class='name-inline'>{p['name']}{p['welpenschutz_badge']}{p['streak_badge']}{p['strike_badge']}</span></td>"
                    f"<td>{p['focus_badge']}</td>"
                    f"<td>{p['status']}</td>"
                    f"<td><b>{p['score']}%</b></td>"
                    f"<td class='trend-cell'>{p['trend_str']}</td>"
                    f"<td style='color:#cbd5e1;'>{p['fame_per_deck']}{p['leecher_warnung']}</td>"
                    f"<td>{p['teilnahme']}</td>"
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

    html = render_html_template(
        clan_name=CLAN_NAME,
        heute_datum=heute_datum,
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
        datenschutz_html=datenschutz_html
    )

    default_mail_texts = [list(block.values())[0] for block in chat_blocks]
    mail_chat_text = "\n\n".join([
        enforce_chat_limit(text, prefix=f"{i + 1}/{total_msgs} ")
        for i, text in enumerate(default_mail_texts)
    ])

    strikes_data["players"] = strikes
    return html, df_history, mail_chat_text, records, strikes_data, kicked_players


def speichere_html_bericht(
    html_content: str,
    df_history: pd.DataFrame,
    records: dict,
    strikes_data: dict,
    file_suffix: str,
    top_decks_data: dict,
    kicked_players: dict
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

    with open(kicked_players_path, "w", encoding="utf-8") as f:
        json.dump(kicked_players, f, ensure_ascii=False, indent=4)

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
    now_utc = datetime.utcnow()
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
            detected_dt = datetime.strptime(detected_at, "%Y-%m-%dT%H:%M:%SZ")
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
            "last_seen": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "first_seen": previous_entry.get("first_seen", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
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

    try:
        headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
        race_resp = requests.get(f"{BASE_URL}/clans/{CLAN_TAG}/currentriverrace", headers=headers, timeout=30)
        if race_resp.status_code == 200:
            data = race_resp.json()

            clans_in_race = data.get("clans", [])
            for c in clans_in_race:
                is_us = c.get("tag") == CLAN_TAG.replace("%23", "#")

                trophies = c.get("clanScore", 0)
                medals = c.get("periodPoints", 0)
                boat_attacks = sum(p.get("boatAttacks", 0) for p in c.get("participants", []))
                decks_used = sum(p.get("decksUsedToday", 0) for p in c.get("participants", []))

                radar_clans.append({
                    "name": c.get("name", ""),
                    "is_us": is_us,
                    "trophies": trophies,
                    "medals": medals,
                    "boat_attacks": boat_attacks,
                    "decks_used": decks_used
                })

                if is_us:
                    for p in c.get("participants", []):
                        decks_today = p.get("decksUsedToday", 0)
                        if decks_today < 4:
                            raw_mahnwache.append({"name": p.get("name"), "offen": 4 - decks_today})

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

    top_decks_data = update_top_decks(current_members, top_decks_data)

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

    fame_columns = sorted([col for col in df.columns if col.startswith("s_") and col.endswith("_fame")], reverse=True)
    if not fame_columns:
        print("❌ Keine Fame-Spalten gefunden.")
        return
    fame_spalte = fame_columns[0]

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
        is_weekly_run=is_weekly_run
    )

    html_path = speichere_html_bericht(
        html_content=html_bericht,
        df_history=df_history,
        records=updated_records,
        strikes_data=updated_strikes_data,
        file_suffix=jetzt_datei,
        top_decks_data=top_decks_data,
        kicked_players=updated_kicked
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
