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
from datetime import datetime
from typing import List, Tuple
from pathlib import Path
import pandas as pd
from email.message import EmailMessage
import smtplib

# === 1. Konfiguration & Pfade ===

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
urlaub_path = BASE_DIR / "urlaub.txt" 
HEADER_IMAGE_PATH = BASE_DIR / "clash_pix.jpg"

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
    members_resp = requests.get(members_url, headers=headers)
    
    if members_resp.status_code != 200:
        print(f"❌ Fehler beim Abruf der Mitglieder: {members_resp.status_code}")
        return False, {}
        
    current_members = {
        m["tag"]: {
            "name": m["name"], 
            "role": m.get("role", "member"),
            "donations": m.get("donations", 0),
            "donations_received": m.get("donationsReceived", 0),
            "trophies": m.get("trophies", 0)  
        } 
        for m in members_resp.json().get("items", [])
    }

    print("Schritt 2: Rufe Warlog (River Races) ab...")
    log_url = f"{BASE_URL}/clans/{CLAN_TAG}/riverracelog"
    log_resp = requests.get(log_url, headers=headers)
    
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
                    players_data[ptag] = {"name": pname, "is_current": is_curr, "role": role, "donations": donations, "donations_received": donations_recv, "trophies": trophies, "history": {}}
                players_data[ptag]["history"][race_id] = {"decks": decks, "fame": fame}

    for tag, data in current_members.items():
        if tag not in players_data:
            players_data[tag] = {"name": data["name"], "is_current": True, "role": data["role"], "donations": data["donations"], "donations_received": data["donations_received"], "trophies": data["trophies"], "history": {}}
        else:
            players_data[tag]["donations"] = data["donations"]
            players_data[tag]["donations_received"] = data["donations_received"]
            players_data[tag]["trophies"] = data["trophies"]
        
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = upload_folder / f"clan_export_{date_str}.csv"

    race_ids = sorted(list(set(race_ids)), reverse=True)
    headers_csv = [
        "player_tag", "player_name", "player_is_current_member", "player_role", "player_donations", "player_donations_received", "player_trophies",
        "player_contribution_count", "player_participating_count", "player_total_decks_used"
    ]
    
    for rid in race_ids:
        headers_csv.extend([f"s_{rid}_fame", f"s_{rid}_decks_used"])
        
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
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
                    
            row = [tag, data["name"], data["is_current"], data["role"], data.get("donations", 0), data.get("donations_received", 0), data.get("trophies", 0), contribution_count, total_races, total_decks]
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
    
    count = 0
    for tag, member_info in current_members.items():
        p_name = member_info["name"]
        clean_tag = tag.replace("#", "%23")
        
        resp = requests.get(f"{BASE_URL}/players/{clean_tag}/battlelog", headers=headers)
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
                        
                        if deck_hash not in decks:
                            decks[deck_hash] = {
                                "cards": [{"id": c["id"], "name": c["name"], "icon": c.get("iconUrls", {}).get("medium", "")} for c in cards],
                                "wins": 0,
                                "losses": 0,
                                "players": [],
                                "tags": []
                            }
                            
                        if is_win: decks[deck_hash]["wins"] += 1
                        if is_loss: decks[deck_hash]["losses"] += 1
                        
                        if p_name not in decks[deck_hash]["players"]:
                            decks[deck_hash]["players"].append(p_name)
                            
                        raw_tag = tag.replace("#", "")
                        if raw_tag not in decks[deck_hash].setdefault("tags", []):
                            decks[deck_hash]["tags"].append(raw_tag)
                            
        if latest_time_in_log:
            metadata["last_battles"][tag] = latest_time_in_log
            
        count += 1
        if count % 10 == 0:
            print(f"  ... {count}/50 Spieler gescannt")
        time.sleep(0.1) 
        
    top_decks_data["_metadata"] = metadata
    top_decks_data["decks"] = decks
    print("✅ Battlelogs erfolgreich gescannt. Top-Decks aktualisiert.\n")
    return top_decks_data

def get_deck_archetype(cards: list) -> str:
    """Analysiert die Karten im Deck und bestimmt den Spielstil."""
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

# === 3. Auswertung & HTML-Design ===

def get_encoded_header_image(path: Path) -> str:
    if not path.exists(): return ""
    try:
        with open(path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return f"data:image/jpeg;base64,{encoded_string}"
    except: return ""

def archiviere_alte_dateien(ordner: Path, archiv_ordner: Path, anzahl: int = 2) -> None:
    archiv_ordner.mkdir(exist_ok=True, parents=True)
    dateien = sorted(ordner.glob("*.csv"), key=os.path.getctime)
    for datei in dateien[:-anzahl]:
        shutil.move(str(datei), archiv_ordner / datei.name)

def finde_neueste_csv(ordner: Path) -> Path:
    csvs = list(ordner.glob("*.csv"))
    if not csvs: raise FileNotFoundError("Keine CSV-Datei im Upload-Ordner gefunden.")
    return max(csvs, key=os.path.getctime)

def berechne_score(participation: int, decks_total: int) -> float:
    max_mögliche_decks = participation * 16
    if max_mögliche_decks <= 0: return 0.0
    return round((decks_total / max_mögliche_decks) * 100, 2)

def chunk_list(lst: list, n: int) -> list:
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def escape_for_html(text: str) -> str:
    return text.replace('"', '&quot;').replace("'", "&#39;")

def generate_html_report(df_active: pd.DataFrame, df_history: pd.DataFrame, fame_spalte: str, heute_datum: str, header_img_src: str, radar_clans: list, records: dict, strikes: dict, race_state_de: str, raw_mahnwache: list, top_decks_data: dict) -> Tuple[str, pd.DataFrame, str, dict, dict]:
    player_stats = []
    urlauber_liste = []
    
    if urlaub_path.exists():
        with urlaub_path.open("r", encoding="utf-8") as f:
            urlauber_liste = [line.strip() for line in f if line.strip()]

    role_map = {"member": "Mitglied", "elder": "Ältester", "coleader": "Vize", "leader": "Anführer", "unknown": "Ehemalig"}

    for _, row in df_active.iterrows():
        raw_role = str(row.get("player_role", "unknown")).strip().lower()
        if raw_role == "unknown": continue
            
        name = row.get("player_name", "Unbekannt")
        role_de = role_map.get(raw_role, raw_role.capitalize())
        is_urlaub = name in urlauber_liste
        
        participation = int(row.get("player_contribution_count", 0) or 0)
        decks_total = int(row.get("player_total_decks_used", 0) or 0)
        donations = int(row.get("player_donations", 0) or 0)
        donations_received = int(row.get("player_donations_received", 0) or 0)
        aktueller_trophy = int(row.get("player_trophies", 0) or 0)
        score = berechne_score(participation, decks_total)
        
        aktueller_fame = int(row.get(fame_spalte, 0) or 0)
        aktueller_decks_spalte = fame_spalte.replace("_fame", "_decks_used")
        aktueller_decks = int(row.get(aktueller_decks_spalte, 0) or 0)
        fame_per_deck = round(aktueller_fame / aktueller_decks) if aktueller_decks > 0 else 0
        leecher_warnung = " <span class='custom-tooltip'>⚠️<span class='tooltip-text'>Verdacht: Zieht nur Punkte ab (verliert absichtlich/greift Boote an)</span></span>" if (0 < fame_per_deck < 115) else ""
        
        historie_spieler = df_history[df_history["player_name"] == name].sort_values("date")
        vergangene_scores = historie_spieler.tail(3)["score"].tolist()
        
        past_trophy = aktueller_trophy
        if not historie_spieler.empty and "trophies" in historie_spieler.columns:
            past_trophy = int(historie_spieler.tail(1)["trophies"].values[0])
            
        trophy_push = aktueller_trophy - past_trophy
        delta = round(score - vergangene_scores[-1], 2) if vergangene_scores else 0.0

        if donations > records.setdefault("donations", {"name": "-", "val": 0})["val"]:
            records["donations"] = {"name": name, "val": donations}
        if delta > records.setdefault("delta", {"name": "-", "val": 0})["val"]:
            records["delta"] = {"name": name, "val": delta}
        if aktueller_trophy > records.setdefault("trophies", {"name": "-", "val": 0})["val"]:
            records["trophies"] = {"name": name, "val": aktueller_trophy}

        trend_scores = vergangene_scores + [score]
        trend_str = "".join(["🟢" if s >= 80 else "🟡" if s >= 50 else "🔴" for s in trend_scores[-4:]])
        
        streak_count = 0
        for s in reversed(trend_scores):
            if s >= 100.0:
                streak_count += 1
            else:
                break
                
        if streak_count > participation:
            streak_count = participation
            
        streak_badge = f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥{streak_count}<span class='tooltip-text'>{streak_count} Auswertungen in Folge 100% Score!</span></span>" if streak_count >= 3 else ""

        ist_montag = datetime.utcnow().weekday() == 0
        ist_mail_zeit = datetime.utcnow().hour in [9, 10, 11]
        ist_manueller_start = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        
        if (ist_montag and ist_mail_zeit) or ist_manueller_start:
            if not is_urlaub and participation > 3:
                if score < 50:
                    strikes[name] = strikes.get(name, 0) + 1
                    if strikes[name] > 3: strikes[name] = 3
                elif score >= 50:
                    if strikes.get(name, 0) > 0:
                        strikes[name] -= 1

        strike_val = strikes.get(name, 0)
        strike_badge = ""
        if strike_val > 0:
            if strike_val >= 3:
                strike_badge = f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3<span class='tooltip-text'>3 Verwarnungen: Kick oder Degradierung empfohlen!</span></span>"
            else:
                strike_badge = f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ {strike_val}/3<span class='tooltip-text'>Verwarnung! Bei 3/3 droht Kick/Degradierung.</span></span>"

        if is_urlaub:
            status_html, tier = "🏖️ Urlaub", "🏖️ Im Urlaub (Pausiert)"
        else:
            status_html = f"{role_de} <span class='badge-ja'>➔ BEFÖRDERN</span>" if raw_role == "member" and aktueller_fame >= 2800 else role_de
            if score >= 95: tier = "🌟 Elite (95-100%)"
            elif score >= 80: tier = "✅ Solides Mittelfeld (80-94%)"
            elif score >= 50: tier = "⚠️ Unter Beobachtung (50-79%)"
            else: tier = "🚫 Kritisch (< 50%)"

        player_stats.append({
            "name": name, "status": status_html, "score": score, "delta": delta,
            "teilnahme": f"{participation}/{int(row.get('player_participating_count', 0) or 0)}",
            "teilnahme_int": participation, "fame": aktueller_fame, "donations": donations, 
            "donations_received": donations_received, "tier": tier, "is_urlaub": is_urlaub, 
            "trend_str": trend_str, "fame_per_deck": fame_per_deck, "leecher_warnung": leecher_warnung,
            "trophy_push": trophy_push, "trophies": aktueller_trophy, "streak_badge": streak_badge, "strike_badge": strike_badge,
            "raw_role": raw_role
        })

        df_history = pd.concat([
            df_history, pd.DataFrame([{"player_name": name, "score": score, "date": heute_datum, "trophies": aktueller_trophy}])
        ], ignore_index=True)

    aktive_spieler = [p for p in player_stats if not p["is_urlaub"]]
    clan_avg = round(sum([p["score"] for p in aktive_spieler]) / len(aktive_spieler), 2) if aktive_spieler else 0
    
    top_performers = sorted(aktive_spieler, key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]), reverse=True)[:3]
    top_aufsteiger = sorted([p for p in aktive_spieler if p["delta"] > 0], key=lambda x: x["delta"], reverse=True)[:3]
    top_spender = sorted([p for p in aktive_spieler if p["donations"] > 0], key=lambda x: x["donations"], reverse=True)[:3]
    top_leecher = sorted([p for p in aktive_spieler if p["teilnahme_int"] > 3 and p["donations"] == 0 and p["donations_received"] > 0], key=lambda x: x["donations_received"], reverse=True)[:3]
    
    kandidaten_kick = []
    kandidaten_demote = []
    for p in aktive_spieler:
        if strikes.get(p['name'], 0) >= 3:
            if p['raw_role'] in ['elder', 'coleader']:
                kandidaten_demote.append(p['name'])
            elif p['raw_role'] == 'member':
                kandidaten_kick.append(p['name'])

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
        for idx, c in enumerate(radar_clans):
            bold_start = "<b style='color:#fff;'>" if c["is_us"] else ""
            bold_end = " (WIR)</b>" if c["is_us"] else ""
            radar_html += f"<p style='margin: 0 0 5px 0;'>{idx+1}. {bold_start}{c['name']}{bold_end} - {c['fame']} Punkte</p>"
        radar_html += "</div>"
        
    mahnwache_html = ""
    ist_kampftag = datetime.utcnow().weekday() in [3, 4, 5, 6]
    
    total_active_players = len(aktive_spieler)
    total_decks_today = total_active_players * 4
    total_open_decks = 0
    hype_balken_html = ""
    
    if ist_kampftag:
        aktive_namen = df_active["player_name"].tolist()
        gefilterte_mahnwache = []
        for m in raw_mahnwache:
            if m['name'] not in urlauber_liste and m['name'] in aktive_namen:
                gefilterte_mahnwache.append(f"<b>{m['name']}</b> ({m['offen']} offen)")
                total_open_decks += m['offen']
                
        if gefilterte_mahnwache:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #ef4444; background: rgba(239, 68, 68, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #ef4444; margin-bottom: 8px;'>⏰ Mahnwache (Noch offene Decks heute):</h4><p style='margin: 0; font-size: 0.95em;'>{', '.join(gefilterte_mahnwache)}</p></div>"
        else:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #10b981; background: rgba(16, 185, 129, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #10b981; margin-bottom: 0;'>✅ Alle aktiven Spieler haben ihre Decks für heute gespielt!</h4></div>"

        played_decks_today = total_decks_today - total_open_decks
        hype_percentage = int((played_decks_today / total_decks_today) * 100) if total_decks_today > 0 else 0
        hype_color = "#ef4444" if hype_percentage < 50 else "#fbbf24" if hype_percentage < 90 else "#10b981"
        
        hype_balken_html = f"""
        <div style='background: rgba(30, 41, 59, 0.8); border-radius: 12px; padding: 20px; margin-bottom: 25px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 15px rgba(0,0,0,0.2);'>
            <div style='display: flex; justify-content: space-between; margin-bottom: 10px; align-items: baseline;'>
                <h3 style='margin: 0; color: #f8fafc; font-size: 1.1em;'>🎯 Tagesziel: Clan-Aktivität</h3>
                <span style='font-weight: bold; color: {hype_color}; font-size: 1.1em;'>{played_decks_today} / {total_decks_today} Decks ({hype_percentage}%)</span>
            </div>
            <div style='background: rgba(0,0,0,0.5); border-radius: 8px; height: 14px; width: 100%; overflow: hidden;'>
                <div style='background: {hype_color}; width: {hype_percentage}%; height: 100%; border-radius: 8px; transition: width 1s ease-in-out;'></div>
            </div>
        </div>
        """

    cr_top_names = ", ".join([p['name'] for p in top_performers])
    top_spender_names = ", ".join([p['name'] for p in top_spender][:2])
    echte_leecher = [p for p in top_leecher if p["donations"] == 0 and p["donations_received"] > 0]
    leecher_names = ", ".join([p['name'] for p in echte_leecher][:2]) if echte_leecher else ""

    chat_blocks = []

    msg_1_vars = {
        "Sachlich": f"📊 Clan-Ø: {clan_avg}%. MVPs: {cr_top_names} 🏆 {pusher_chat}",
        "Motivierend": f"🔥 Super Leistung! Clan-Ø: {clan_avg}%. Ein dickes Danke an unsere MVPs: {cr_top_names}! {pusher_chat}",
        "Kurz & Knackig": f"⚔️ Auswertung da! Schnitt: {clan_avg}%. Top 3: {cr_top_names}. {pusher_chat}"
    }
    chat_blocks.append(msg_1_vars)

    msg_2_sachlich = f"🃏 Ein Lob an unsere Top-Spender: {top_spender_names}! 🤝" if top_spender else "🃏 Kaum Spenden diese Woche. Ein Clan lebt vom Geben UND Nehmen! 🤝"
    if echte_leecher: msg_2_sachlich += f" | 🧛 Spenden-Leecher (nur kassiert): {leecher_names}."
    
    msg_2_motiv = f"💚 Wahnsinn, was ihr spendet! Top-Supporter: {top_spender_names}. Danke fürs Karten teilen!" if top_spender else "💚 Vergesst das Spenden nicht, Team! Jeder braucht mal Karten."
    
    msg_2_streng = f"⚠️ Spenden-Check: Danke an {top_spender_names}." if top_spender else "⚠️ Null Spenden-Moral diese Woche!"
    if echte_leecher: msg_2_streng += f" Die Leecher-Liste (nehmen ohne geben): {leecher_names}. Das muss besser werden!"
    
    msg_2_vars = {
        "Sachlich": msg_2_sachlich,
        "Motivierend": msg_2_motiv,
        "Kurz & Knackig": msg_2_streng
    }
    chat_blocks.append(msg_2_vars)

    for chunk in chunk_list(kandidaten_demote, 4):
        names_str = ", ".join(chunk)
        demote_vars = {
            "Sachlich": f"👇 Degradierung: {names_str}. Grund: Dauerhaft zu wenig Kriegskämpfe. Letzte Bewährungschance als Mitglied! ⚔️",
            "Motivierend": f"👇 Wir stufen {names_str} wegen Kriegsinaktivität zum Mitglied ab. Kommt stärker zurück, ihr schafft das! ⚔️",
            "Kurz & Knackig": f"👇 Degradierungen: {names_str} (Dauerhaft inaktiv im Krieg). Letzte Warnung. ⚔️"
        }
        chat_blocks.append(demote_vars)

    for chunk in chunk_list(kandidaten_kick, 4):
        names_str = ", ".join(chunk)
        kick_vars = {
            "Sachlich": f"👋 Verabschiedung: {names_str}. Grund: Wiederholte Inaktivität im Clankrieg. Wir machen Platz. Alles Gute! ✌️",
            "Motivierend": f"👋 Wir machen Platz für aktive Kämpfer und verabschieden {names_str} wegen Inaktivität. Danke für die Zeit! ✌️",
            "Kurz & Knackig": f"👋 Kicks: {names_str}. Grund: Dauerhafte Kriegsinaktivität. ✌️"
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
    colors = ["#38bdf8", "#a855f7", "#ef4444", "#f97316", "#10b981", "#fbbf24"]
    chat_boxes_html = ""
    
    for i, block_vars in enumerate(chat_blocks):
        color = colors[i % len(colors)]
        options_html = ""
        for style_name, text_content in block_vars.items():
            final_text = f"{i+1}/{total_msgs} {text_content}"
            safe_text = escape_for_html(final_text)
            options_html += f'<option value="{safe_text}">{style_name}</option>'
            
        default_text = f"{i+1}/{total_msgs} {list(block_vars.values())[0]}"
        
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
    sorted_decks = sorted(top_decks_data.get("decks", {}).values(), key=lambda x: x["wins"], reverse=True)
    top_x_decks = [d for d in sorted_decks if d["wins"] > 0][:8]
    
    if not top_x_decks:
        deck_html = "<div class='info-box' style='border-left-color: #64748b;'><p style='margin: 0;'><b>Noch nicht genug Daten gesammelt.</b><br>Das System zeichnet ab heute im Hintergrund alle Clankriegs-Siege auf. Schau in ein paar Tagen wieder vorbei, dann siehst du hier die absoluten Meta-Decks unseres Clans!</p></div>"
    else:
        for idx, d in enumerate(top_x_decks):
            total_matches = d["wins"] + d["losses"]
            winrate = int((d["wins"] / total_matches) * 100) if total_matches > 0 else 0
            players_str = ", ".join(d["players"][:3]) + ("..." if len(d["players"])>3 else "")
            
            archetype = get_deck_archetype(d["cards"])
            
            # Die magischen 8 Karten-IDs
            deck_ids_str = ";".join([str(c["id"]) for c in d["cards"]])
            
            # --- DER LÖSUNGS-CODE FÜR DEN DECK-LINK ---
            # 1. Nativer Link: Umgeht die Supercell-Website und öffnet direkt die App (Handy)
            mobile_copy_link = f"clashroyale://copyDeck?deck={deck_ids_str}"
            
            # 2. PC-Fallback: Generiert einen sauberen RoyaleAPI-Link 
            api_names = [c["name"].lower().replace(".", "").replace(" ", "-") for c in d["cards"]]
            royaleapi_link = f"https://royaleapi.com/decks/stats/{','.join(api_names)}"
            # -------------------------------------------
            
            images_html = "".join([f"<img src='{c['icon']}' style='width: 23%; border-radius: 4px; margin: 1%;' title='{c['name']}'>" for c in d["cards"]])
            
            deck_html += f"""
            <div class="deck-card">
                <div class="archetype-badge">{archetype}</div>
                <div class="deck-header">
                    <h3 style="margin: 0; color: #f97316; font-size: 1.1em; font-weight: 800;">🏆 Meta-Deck #{idx+1}</h3>
                    <span class="winrate">🔥 {winrate}% Win</span>
                </div>
                <div class="deck-images">
                    {images_html}
                </div>
                <p style="font-size: 0.85em; color: #94a3b8; margin: 10px 0;">Oft gewonnen von:<br><span style="color:#e2e8f0; font-weight:bold;">{players_str}</span></p>
                <div style="margin-top: auto; display: flex; flex-direction: column; gap: 8px;">
                    <a href="{mobile_copy_link}" class="copy-btn" style="background: #38bdf8; color: #0f172a;">📱 Ins Spiel kopieren</a>
                    <a href="{royaleapi_link}" class="copy-btn" style="background: #475569; color: #f8fafc;" target="_blank">💻 Auf RoyaleAPI ansehen</a>
                </div>
            </div>
            """

    tiers = ["🌟 Elite (95-100%)", "✅ Solides Mittelfeld (80-94%)", "⚠️ Unter Beobachtung (50-79%)", "🚫 Kritisch (< 50%)", "🏖️ Im Urlaub (Pausiert)"]

    table_html = ""
    modals_html = "" 
    
    for t in tiers:
        players_in_tier = sorted([p for p in player_stats if p["tier"] == t], key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]), reverse=True)
        if players_in_tier:
            table_html += f"<div class='tier-section'>"
            table_html += f"<div class='tier-title'>{t}</div>"
            table_html += """<table>
                <thead>
                <tr>
                    <th>Spieler</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Trend</th>
                    <th>Delta</th>
                    <th>Ø Punkte</th>
                    <th>🃏 Spenden</th>
                    <th>Teilnahmen</th>
                    <th>Kriegspunkte</th>
                </tr>
                </thead>
                <tbody>"""
            for p in players_in_tier:
                delta_s = f"+{p['delta']}" if p['delta']>0 else f"{p['delta']}"
                color = "#10b981" if p['delta'] > 0 else "#ef4444" if p['delta'] < 0 else "#94a3b8"
                neu_badge = " <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱<span class='tooltip-text'>Neu im Clan / Wenig Kriege</span></span>" if p['teilnahme_int'] <= 3 and not p['is_urlaub'] else ""
                
                spenden_warnung = ""
                if p['donations'] == 0 and p['teilnahme_int'] > 3 and not p['is_urlaub']:
                    if p['donations_received'] > 0:
                        spenden_warnung = f" <span class='custom-tooltip' style='font-size: 1.1em;'>🧛<span class='tooltip-text'>Spenden-Leecher (0 gespendet, aber {p['donations_received']} erhalten)</span></span>"
                    else:
                        spenden_warnung = " <span class='custom-tooltip' style='font-size: 1.1em;'>💤<span class='tooltip-text'>Spenden-Inaktiv (0 gespendet, 0 erhalten)</span></span>"
                
                spenden_zelle = f"<span class='custom-tooltip dotted'>{p['donations']}<span class='tooltip-text'>Gespendet: {p['donations']} | Empfangen: {p['donations_received']}</span></span>"
                
                safe_id = "".join([c if c.isalnum() else "_" for c in p['name']])
                
                table_html += f"<tr><td class='name-col' onclick=\"openModal('modal_{safe_id}')\" title='Klicke für Visitenkarte'>🔍 {p['name']}{neu_badge}{p['streak_badge']}{p['strike_badge']}</td><td>{p['status']}</td><td><b>{p['score']}%</b></td><td class='trend-cell'>{p['trend_str']}</td><td style='color:{color}; font-weight:bold;'>{delta_s}%</td><td style='color:#cbd5e1;'>{p['fame_per_deck']}{p['leecher_warnung']}</td><td style='color:#38bdf8; font-weight:bold;'>{spenden_zelle}{spenden_warnung}</td><td>{p['teilnahme']}</td><td>{p['fame']}</td></tr>"
                
                modals_html += f"""
                <div id="modal_{safe_id}" class="modal-overlay" onclick="closeModal('modal_{safe_id}')">
                    <div class="modal-content" onclick="event.stopPropagation()">
                        <button class="modal-close" onclick="closeModal('modal_{safe_id}')">✖</button>
                        <div class="modal-header">
                            <h2 style="margin:0; color:#38bdf8; font-size: 1.6em;">{p['name']}</h2>
                            <span style="color:#94a3b8; font-size:1em; font-weight: bold;">{p['status']}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:20px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:15px; text-align:center;">
                            <div style="flex:1;"><span style="color:#94a3b8; font-size:0.85em;">Score</span><br><b style="font-size:1.4em; color:#fff;">{p['score']}%</b></div>
                            <div style="flex:1;"><span style="color:#94a3b8; font-size:0.85em;">Trend</span><br><span style="font-size:1.4em; letter-spacing:2px;">{p['trend_str']}</span></div>
                            <div style="flex:1;"><span style="color:#94a3b8; font-size:0.85em;">Delta</span><br><b style="font-size:1.4em; color:{color};">{delta_s}%</b></div>
                        </div>
                        <div style="margin-bottom:12px; font-size: 1.1em;"><b>⚔️ Teilnahmen:</b> <span style="float:right; color:#e2e8f0;">{p['teilnahme']}</span></div>
                        <div style="margin-bottom:12px; font-size: 1.1em;"><b>🎖️ Ø Punkte/Deck:</b> <span style="float:right; color:#e2e8f0;">{p['fame_per_deck']} {p['leecher_warnung']}</span></div>
                        <div style="margin-bottom:12px; font-size: 1.1em;"><b>🃏 Spenden gesendet:</b> <span style="float:right; color:#10b981; font-weight:bold;">{p['donations']}</span></div>
                        <div style="margin-bottom:12px; font-size: 1.1em;"><b>📭 Spenden erhalten:</b> <span style="float:right; color:#ef4444; font-weight:bold;">{p['donations_received']}</span></div>
                        <div style="margin-top:20px; text-align:center; font-size: 1.5em;">{p['streak_badge']} {p['strike_badge']}</div>
                    </div>
                </div>
                """

            table_html += "</tbody></table></div>"

    html = f"""
    <html>
    <head>
        <meta charset='utf-8'>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Auswertung: {CLAN_NAME}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
            body {{ font-family: 'Nunito', sans-serif; margin: 0; padding: 20px; background: linear-gradient(rgba(15, 23, 42, 0.85), rgba(15, 23, 42, 0.95)), url('https://images.hdqwalls.com/download/clash-royale-4k-19-1920x1080.jpg') no-repeat center center fixed; background-size: cover; color: #f8fafc; }}
            .container {{ max-width: 1200px; margin: auto; }}
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
            th:nth-child(1) {{ width: 20%; }} th:nth-child(2) {{ width: 14%; }} th:nth-child(3) {{ width: 8%; text-align: center; }} th:nth-child(4) {{ width: 12%; }} th:nth-child(5) {{ width: 8%; text-align: center; }} th:nth-child(6) {{ width: 10%; text-align: center; }} th:nth-child(7) {{ width: 10%; text-align: center; }} th:nth-child(8) {{ width: 9%; text-align: center; }} th:nth-child(9) {{ width: 9%; text-align: center; }}
            tr:nth-child(odd) {{ background-color: rgba(0, 0, 0, 0.45); }} tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.15); }} tr:hover {{ background-color: rgba(255, 255, 255, 0.3); }}
            th, td {{ padding: 14px 10px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; vertical-align: middle; }}
            td:nth-child(3), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {{ text-align: center; }}
            
            th {{ position: sticky; top: 128px; background-color: #0f172a; color: #94a3b8; z-index: 800; font-weight: 600; font-size: 0.9em; border-bottom: 1px solid rgba(255,255,255,0.1); line-height: 1.4; box-shadow: 0 4px 5px rgba(0,0,0,0.3); }}
            td {{ border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 1.05em; }}
            
            .badge-ja {{ background-color: #10b981; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-weight: 800; font-size: 0.8em; margin-left: 8px; }}
            .name-col {{ font-weight: 800; color: #ffffff; cursor: pointer; transition: color 0.2s; }}
            .name-col:hover {{ color: #38bdf8; text-decoration: underline; text-decoration-style: dotted; }}
            
            .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 2000; justify-content: center; align-items: center; backdrop-filter: blur(3px); }}
            .modal-content {{ background: linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95)); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 12px; width: 90%; max-width: 350px; padding: 25px; position: relative; box-shadow: 0 10px 30px rgba(0,0,0,0.5); animation: scaleUp 0.3s ease; color: #f8fafc; }}
            .modal-close {{ position: absolute; top: 15px; right: 15px; background: transparent; border: none; color: #94a3b8; font-size: 1.2em; cursor: pointer; transition: 0.2s; }}
            .modal-close:hover {{ color: #ef4444; }}
            .modal-header {{ text-align: center; margin-bottom: 20px; }}
            @keyframes scaleUp {{ from {{ transform: scale(0.9); opacity: 0; }} to {{ transform: scale(1); opacity: 1; }} }}
            
            .trend-cell {{ font-size: 16px !important; white-space: nowrap; line-height: 1; }}
            
            .wiki-table {{ width: 100%; table-layout: fixed; border-collapse: collapse; background: rgba(0, 0, 0, 0.3); border-radius: 8px; margin: 15px 0; border: 1px solid rgba(255, 255, 255, 0.1); font-size: 0.85em; }}
            .wiki-table th {{ position: static; box-shadow: none; background-color: rgba(0,0,0,0.6); }}
            .wiki-table th, .wiki-table td {{ padding: 8px 5px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
            .wiki-table tr:nth-child(odd) {{ background-color: transparent; }}
            .wiki-table tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.05); }}
            
            .custom-tooltip {{ position: relative; display: inline-block; cursor: help; }}
            .custom-tooltip.dotted {{ border-bottom: 1px dotted rgba(56, 189, 248, 0.5); }}
            .custom-tooltip .tooltip-text {{ visibility: hidden; width: max-content; background-color: rgba(15, 23, 42, 0.98); color: #fff; text-align: center; border-radius: 6px; padding: 6px 12px; position: absolute; z-index: 100; bottom: 140%; left: 50%; transform: translateX(-50%); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 10px rgba(0,0,0,0.4); opacity: 0; transition: opacity 0.2s ease-in-out; font-size: 0.9em; font-weight: normal; font-family: 'Nunito', sans-serif; }}
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
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-container">
                <h1 class="header-title"><span onclick="unlockChat()" style="cursor: pointer;" title="Nur für die Clan-Führung">📊</span> Clan-Auswertung: {CLAN_NAME} <br>
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
                
                <div class="dashboard">
                    <div class="card avg">
                        <h3>📈 Clan-Durchschnitt</h3>
                        <h1>{clan_avg}%</h1>
                    </div>
                    <div class="card top">
                        <h3>🏆 Top 3 Performer</h3>
                        <ul>{''.join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in top_performers])}</ul>
                    </div>
                    <div class="card spender">
                        <h3>🃏 Top 3 Spender</h3>
                        <ul>{''.join([f"<li><b>{p['name']}</b> ({p['donations']})</li>" for p in top_spender]) if top_spender else "<li>Keine Spenden</li>"}</ul>
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
                        <ul>{''.join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger]) if top_aufsteiger else "<li>Keine Verbesserungen</li>"}</ul>
                    </div>
                    <div class="card leecher">
                        <h3>🧛 Top 3 Leecher</h3>
                        <ul>{''.join([f"<li><b>{p['name']}</b> ({p['donations']} gesp. / {p['donations_received']} empf.)</li>" for p in top_leecher]) if top_leecher else "<li>Keine Leecher! 🎉</li>"}</ul>
                    </div>
                    
                    <div id="admin-chat-container" style="display: none; width: 100%;">
                        <div class="card messenger">
                            <h3 style="color: #f1c40f; margin-bottom: 10px;">🎮 Admin-Tool: In-Game Chat ({total_msgs}-Teiler)</h3>
                            <p style="font-size: 0.9em; color: #cbd5e1; margin-top: 0; margin-bottom: 15px;">Wähle oben im Menü den passenden Tonfall. Kopiere dann die {total_msgs} Texte nacheinander in den Chat.</p>
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
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>❌ 1/3:</b> Verwarnungen (bei 3/3 droht Kick)</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🧛 Vampir:</b> Nimmt Spenden, gibt aber 0</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>💤 Schläfer:</b> Spendet 0, fordert 0</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>⚠️ Ø Punkte:</b> Verdacht auf Dropping (<115)</div>
                        <div style="background: rgba(0,0,0,0.3); padding: 5px 10px; border-radius: 6px;"><b>🔥 Streak:</b> Mehrere Wochen 100% Score</div>
                    </div>
                </div>
                
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 30px; color: #ffffff;">📋 Detail-Auswertung</h2>
                <p style="text-align: center; color: #94a3b8; margin-top: -20px; margin-bottom: 25px;">💡 Tippe auf einen <b>Spielernamen</b>, um seine digitale Visitenkarte zu öffnen!</p>
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

                <button class="accordion-btn">⚖️ Verwarnungen, Degradierung & Kicks (❌)</button>
                <div class="accordion-content">
                    <p>Damit nicht eine einzige schlechte Woche sofort zum Rauswurf führt, hat unsere Auswertung ein faires Langzeit-Gedächtnis. Wer sich nicht abmeldet und im Clankrieg dauerhaft zu wenig liefert (Score unter 50%), sammelt im Hintergrund unsichtbare Verwarnungen (❌).</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler A <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td>Ältester</td><td><b>49.38%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>179</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>303</span></td><td>10/10</td><td>1250</td></tr>
                            <tr><td class='name-col'>Spieler B <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td>Mitglied</td><td><b>34.38%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>100 ⚠️</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> 💤</td><td>4/10</td><td>800</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Die zweite Chance (Degradierung):</b> Wenn ein <i>Ältester</i> oder <i>Vize</i> (wie <b>Spieler A</b> oben) 3 Verwarnungen ansammelt, wird er nicht sofort gekickt. Er wird zur Strafe zum <b>Mitglied degradiert</b> und erhält so eine letzte Bewährungschance.</li>
                        <li><b>Der Rauswurf (Kick):</b> Wenn ein normales <i>Mitglied</i> (wie <b>Spieler B</b> oben) 3 Verwarnungen erreicht, trennen wir uns. So machen wir Platz für neue, aktive Spieler.</li>
                        <li><b>Das Konto ausgleichen:</b> Wer nach einer Verwarnung wieder anzieht und in der Folgewoche über 50% Score holt, baut seine negativen Einträge automatisch wieder ab!</li>
                    </ul>
                </div>

                <button class="accordion-btn">🎯 Der Score (Zuverlässigkeit & Welpenschutz)</button>
                <div class="accordion-content">
                    <p>Der Score ist die wichtigste Zahl im Dashboard. Er misst nicht, wie stark du bist oder wie viel du gewinnst, sondern <b>wie verlässlich du bist</b>.<br><br>
                    Stell dir vor, du hast für jedes Kriegswochenende 16 "Tickets" (4 Tage × 4 Decks). Der Score zeigt einfach, wie viele deiner verfügbaren Tickets du auch wirklich genutzt hast.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler C <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥 4</span></td><td>Vize</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>131</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>146</span></td><td>10/10</td><td>2100</td></tr>
                            <tr><td class='name-col'>Spieler D <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td>Mitglied</td><td><b>6.25%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>200</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span></td><td>2/10</td><td>200</td></tr>
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
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler E</td><td>Mitglied</td><td><b>45.0%</b></td><td class='trend-cell'>🟢🟢🟡🔴</td><td style='color:#ef4444; font-weight:bold;'>-20.0%</td><td style='color:#cbd5e1;'>180</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>150</span></td><td>8/10</td><td>1400</td></tr>
                            <tr><td class='name-col'>Spieler F</td><td>Ältester</td><td><b>90.0%</b></td><td class='trend-cell'>🔴🔴🟢🟢</td><td style='color:#10b981; font-weight:bold;'>+15.0%</td><td style='color:#cbd5e1;'>160</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>200</span></td><td>6/10</td><td>900</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>🟢 Grün (Leistungsträger):</b> Starker Score von 80% bis 100%.</li>
                        <li><b>🟡 Gelb (Mittelfeld):</b> Akzeptabler Score von 50% bis 79%, aber mit Luft nach oben.</li>
                        <li><b>🔴 Rot (Kritisch):</b> Score unter 50% (Zu wenig Teilnahme im Flussrennen).</li>
                        <li><i>Beispiel Spieler E:</i> Hat stark angefangen, aber in den letzten zwei Wochen leider stark nachgelassen (Rechter Punkt ist rot).</li>
                    </ul>
                </div>

                <button class="accordion-btn">📈 Das Delta (Deine Formkurve)</button>
                <div class="accordion-content">
                    <p>Das Delta ist wie beim Sport deine aktuelle Formkurve. Es vergleicht deine Leistung von heute mit deiner Leistung aus der letzten Auswertung.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler G</td><td>Mitglied</td><td><b>85.0%</b></td><td class='trend-cell'>🟢🟢🟡🟢</td><td style='color:#10b981; font-weight:bold;'>+12.0%</td><td style='color:#cbd5e1;'>180</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>150</span></td><td>8/10</td><td>1400</td></tr>
                            <tr><td class='name-col'>Spieler H</td><td>Ältester</td><td><b>60.0%</b></td><td class='trend-cell'>🟡🔴🟢🟡</td><td style='color:#ef4444; font-weight:bold;'>-5.0%</td><td style='color:#cbd5e1;'>160</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>200</span></td><td>6/10</td><td>900</td></tr>
                            <tr><td class='name-col'>Spieler I</td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>205</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>350</span></td><td>10/10</td><td>2050</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b style="color: #10b981;">Grüne Zahl (z.B. +12.0%):</b> Super! Du hast dich im Vergleich zur letzten Woche gesteigert und warst aktiver (siehe <b>Spieler G</b>).</li>
                        <li><b style="color: #ef4444;">Rote Zahl (z.B. -5.0%):</b> Du hast diese Woche etwas nachgelassen und weniger Angriffe gemacht als zuletzt (siehe <b>Spieler H</b>).</li>
                        <li><b style="color: #94a3b8;">Graue Null (0.0%):</b> Deine Leistung ist exakt konstant geblieben (siehe <b>Spieler I</b>).</li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ Ø Punkte (Der Qualitäts-Check)</button>
                <div class="accordion-content">
                    <p>Hier schauen wir, wie effektiv du deine Decks einsetzt. Das System teilt deine gesammelten Kriegspunkte durch die Anzahl deiner gespielten Decks.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler J <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ 3/3</span></td><td>Ältester</td><td><b>27.34%</b></td><td class='trend-cell'>🔴🔴🔴🔴</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>100 <span class='custom-tooltip'>⚠️</span></td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>72</span></td><td>8/10</td><td>100</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Normalwert:</b> Selbst wenn du verlierst, bekommst du in normalen Kämpfen mindestens 115 Punkte. Ein Sieg bringt deutlich mehr.</li>
                        <li><b>⚠️ Die Warnung (< 115 Punkte):</b> Wenn dein Durchschnitt unter 115 fällt (wie bei <b>Spieler J</b> oben), schlägt das System Alarm. Das passiert nur, wenn jemand oft feindliche Boote angreift (bringt sehr wenig Punkte für den Clan) oder absichtlich Kämpfe sofort aufgibt, um schnell fertig zu werden.</li>
                    </ul>
                </div>

                <button class="accordion-btn">🃏 Spenden-Verhalten (Das Teamplay)</button>
                <div class="accordion-content">
                    <p>Ein starker Clan hilft sich gegenseitig beim Leveln der Karten. Wir haben das Auge auf zwei Problemfälle:</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler K</td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>200</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>🧛</span></td><td>10/10</td><td>2000</td></tr>
                            <tr><td class='name-col'>Spieler L</td><td>Mitglied</td><td><b>50.0%</b></td><td class='trend-cell'>🟡🟡🟡🟡</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>150</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>0</span> <span class='custom-tooltip' style='font-size: 1.1em;'>💤</span></td><td>5/10</td><td>1000</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>🧛 Der Vampir-Leecher:</b> Jemand (wie <b>Spieler K</b>), der ständig Karten anfordert und im Chat abkassiert, aber selbst absolut <b>0</b> Karten an andere spendet. Das ist unfaires Teamplay.</li>
                        <li><b>💤 Der Schläfer:</b> Jemand (wie <b>Spieler L</b>), der weder spendet noch etwas anfordert. Hier geht dem Clan zwar nichts verloren, aber die Person beteiligt sich gar nicht am Clan-Leben.</li>
                    </ul>
                </div>

                <button class="accordion-btn">⚔️ Teilnahmen (Deine Clan-Treue)</button>
                <div class="accordion-content">
                    <p>Gibt an, in wie vielen der letzten 10 Clankriege du mindestens ein Deck gespielt hast.</p>
                    <div style="overflow-x:auto;">
                        <table class="wiki-table">
                            <tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teilnahmen</th><th>Kriegspunkte</th></tr>
                            <tr><td class='name-col'>Spieler M</td><td>Vize</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>200</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>100</span></td><td>10/10</td><td>2000</td></tr>
                            <tr><td class='name-col'>Spieler N <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱</span></td><td>Mitglied</td><td><b>100.0%</b></td><td class='trend-cell'>🟢🟢🟢🟢</td><td style='color:#94a3b8; font-weight:bold;'>0.0%</td><td style='color:#cbd5e1;'>200</td><td style='color:#38bdf8; font-weight:bold;'><span class='custom-tooltip dotted'>50</span></td><td>2/10</td><td>400</td></tr>
                        </table>
                    </div>
                    <ul>
                        <li><b>Langzeit-Aktivität:</b> Zeigt, wie treu du dem Clan über die letzten Wochen zur Seite standest. Maximal sind aktuell 10 Teilnahmen sichtbar (wie bei <b>Spieler M</b> mit 10/10).</li>
                        <li><b>Welpenschutz (🌱):</b> Wenn du neu bei uns bist (wie <b>Spieler N</b> mit 2/10), brauchst du dir keine Sorgen machen. Dein Score wird fair nur anhand der Kriege berechnet, bei denen du schon im Clan warst.</li>
                    </ul>
                </div>
                
                <button class="accordion-btn">📊 Der Clan-Durchschnitt</button>
                <div class="accordion-content">
                    <p>Das ist quasi der "Notendurchschnitt" unserer Klasse. Wir addieren alle Scores und teilen sie durch die Anzahl der aktiven Mitglieder.</p>
                    <ul>
                        <li><b>Die Urlaubs-Regel:</b> Wenn jemand offiziell im Urlaub (🏖️) ist und pausiert, wird er aus dieser Rechnung komplett herausgenommen. So zieht jemand, der am Strand liegt, unseren Clan-Durchschnitt nicht ungerechtfertigt nach unten!</li>
                    </ul>
                </div>
            </div>

            <div id="Decks" class="tab-content">
                <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 10px; margin-bottom: 10px; color: #ffffff;">🃏 Clan-Meta: Die besten Kriegs-Decks</h2>
                <p style="text-align: center; color: #94a3b8; margin-bottom: 30px;">Das System analysiert im Hintergrund alle Clankriegs-Kämpfe und zeigt euch hier die Decks, die am häufigsten gewonnen haben.</p>
                <div class="deck-slider">
                    {deck_html}
                </div>
            </div>

        </div>

        {modals_html}

        <script>
            // Visitenkarten öffnen und schließen
            function openModal(id) {{
                document.getElementById(id).style.display = 'flex';
            }}
            function closeModal(id) {{
                document.getElementById(id).style.display = 'none';
            }}

            function unlockChat() {{
                var pin = prompt("Admin-Bereich. Bitte PIN eingeben:");
                if(pin === "vize") {{
                    document.getElementById("admin-chat-container").style.display = "block";
                    alert("Chat-Generator erfolgreich freigeschaltet!");
                }} else if(pin !== null) {{
                    alert("Falsche PIN. Zugriff verweigert.");
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
    </html>"""

    default_mail_texts = [list(block.values())[0] for block in chat_blocks]
    mail_chat_text = "\n\n".join([f"{i+1}/{total_msgs} {text}" for i, text in enumerate(default_mail_texts)])
    return html, df_history, mail_chat_text, records, strikes

def speichere_html_bericht(html_content: str, df_history: pd.DataFrame, records: dict, strikes: dict, file_suffix: str, top_decks_data: dict) -> Path:
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
        json.dump(strikes, f, ensure_ascii=False, indent=4)
        
    with open(top_decks_path, "w", encoding="utf-8") as f:
        json.dump(top_decks_data, f, ensure_ascii=False, indent=4)
        
    return html_path

def archiviere_alte_auswertungen(output_dir: Path, anzahl: int = 2):
    archiv_output = output_dir / "archiv"
    archiv_output.mkdir(exist_ok=True, parents=True)
    alte_htmls = sorted(output_dir.glob("auswertung_*.html"), key=os.path.getctime)
    for file in alte_htmls[:-anzahl]:
        shutil.move(str(file), archiv_output / file.name)

def sende_bericht_per_mail(absender: str, empfänger: str, smtp_server: str, port: int, passwort: str, html_path: Path, all_chat_texts: str):
    pass 

def main():
    upload_folder.mkdir(parents=True, exist_ok=True)
    archiv_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    print("=== STARTE CLAN-DATEN ABRUF ===")
    success, current_members = fetch_and_build_player_csv()
    if not success: return
    
    print("Schritt 3: Rufe Live-Radar (Current River Race) ab...")
    radar_clans = []
    race_state_de = "Live"
    raw_mahnwache = []
    
    try:
        headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
        race_resp = requests.get(f"{BASE_URL}/clans/{CLAN_TAG}/currentriverrace", headers=headers)
        if race_resp.status_code == 200:
            data = race_resp.json()
            
            raw_state = data.get("state", "")
            if raw_state == "training": race_state_de = "Trainingstage"
            elif raw_state == "warDay": race_state_de = "Kampftag"
            
            clans_in_race = data.get("clans", [])
            for c in clans_in_race:
                pts = c.get("periodPoints", 0)
                if pts == 0: pts = c.get("fame", 0)
                
                if pts == 0 and "participants" in c:
                    pts = sum(p.get("fame", 0) for p in c.get("participants", []))
                    
                if pts == 0 and "periodLogs" in data:
                    for log in data.get("periodLogs", []):
                        for item in log.get("items", []):
                            if item.get("clan", {}).get("tag") == c.get("tag"):
                                pts += item.get("points", 0)
                                pts += item.get("fame", 0)
                
                is_us = c.get("tag") == CLAN_TAG.replace("%23", "#")
                radar_clans.append({
                    "name": c.get("name", ""), "fame": pts, "is_us": is_us
                })
                
                if is_us:
                    for p in c.get("participants", []):
                        decks_today = p.get("decksUsedToday", 0)
                        if decks_today < 4:
                            raw_mahnwache.append({"name": p.get("name"), "offen": 4 - decks_today})
                            
            radar_clans.sort(key=lambda x: x["fame"], reverse=True)
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

    strikes = {}
    if strikes_path.exists():
        try:
            with open(strikes_path, "r", encoding="utf-8") as f:
                strikes = json.load(f)
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
    if not fame_columns: return
    fame_spalte = fame_columns[0]

    if score_history_path.exists(): 
        df_history = pd.read_csv(score_history_path)
        if "trophies" not in df_history.columns: df_history["trophies"] = 0
    else: 
        df_history = pd.DataFrame(columns=["player_name", "score", "date", "trophies"])

    heute_datum = datetime.today().strftime("%Y-%m-%d")
    jetzt_datei = datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
    encoded_header_img = get_encoded_header_image(HEADER_IMAGE_PATH)
    
    html_bericht, df_history, mail_chat_text, updated_records, updated_strikes = generate_html_report(df_active, df_history, fame_spalte, heute_datum, encoded_header_img, radar_clans, records, strikes, race_state_de, raw_mahnwache, top_decks_data)

    html_path = speichere_html_bericht(html_bericht, df_history, updated_records, updated_strikes, jetzt_datei, top_decks_data)
    archiviere_alte_auswertungen(output_folder)
    
    sender_mail = os.environ.get("EMAIL_SENDER")
    receiver_mail = os.environ.get("EMAIL_RECEIVER")
    email_pass = os.environ.get("EMAIL_PASS")
    
    ist_manueller_start = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    jetzt_utc = datetime.utcnow()
    ist_montag = jetzt_utc.weekday() == 0
    ist_mail_zeit = jetzt_utc.hour in [9, 10, 11]
    
    if sender_mail and receiver_mail and email_pass:
        if (ist_montag and ist_mail_zeit) or ist_manueller_start:
            print("=== BERICHT WURDE GENERIERT ===")
            print("💡 Testmodus aktiv: HTML und Layout wurden erfolgreich erstellt, E-Mail-Versand ist vorerst deaktiviert.")
        else:
            print(f"\n💡 Info: Radar aktualisiert. E-Mail-Versand übersprungen (Passiert nur montags oder bei manuellem Start).")
    else:
        print("\n⚠️ HINWEIS: E-Mail-Secrets fehlen, Versand nicht möglich.")
        
    print("\n=== ALLES ERFOLGREICH ABGESCHLOSSEN ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print("\n❌ EIN KRITISCHER FEHLER IST AUFGETRETEN:")
        traceback.print_exc()
        sys.exit(1) 
