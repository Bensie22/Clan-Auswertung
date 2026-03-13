import os
import glob
import shutil
import requests
import csv
import base64
import json
import sys
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
urlaub_path = BASE_DIR / "urlaub.txt" 
HEADER_IMAGE_PATH = BASE_DIR / "clash_pix.jpg"

# === 2. API Datenabruf ===

def fetch_and_build_player_csv() -> bool:
    if not API_TOKEN:
        print("❌ Fehler: Bitte trage deinen SUPERCELL_API_TOKEN in die GitHub Secrets ein.")
        return False

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Accept": "application/json"
    }

    print("Schritt 1: Rufe aktuelle Mitgliederliste ab...")
    members_url = f"{BASE_URL}/clans/{CLAN_TAG}/members"
    members_resp = requests.get(members_url, headers=headers)
    
    if members_resp.status_code != 200:
        print(f"❌ Fehler beim Abruf der Mitglieder: {members_resp.status_code}")
        return False
        
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
        return False

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
    return True

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

def generate_html_report(df_active: pd.DataFrame, df_history: pd.DataFrame, fame_spalte: str, heute_datum: str, header_img_src: str, radar_clans: list, records: dict, race_state_de: str) -> Tuple[str, pd.DataFrame, str, str, str, dict]:
    player_stats = []
    urlauber_liste = []
    
    if urlaub_path.exists():
        with urlaub_path.open("r", encoding="utf-8") as f:
            urlauber_liste = [line.strip() for line in f if line.strip()]

    role_map = {"member": "Mitglied", "elder": "Ältester", "coLeader": "Vize", "leader": "Anführer", "unknown": "Ehemalig"}

    for _, row in df_active.iterrows():
        raw_role = row.get("player_role", "unknown")
        if raw_role == "unknown": continue
            
        name = row.get("player_name", "Unbekannt")
        role_de = role_map.get(raw_role, raw_role)
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
            "trophy_push": trophy_push, "trophies": aktueller_trophy
        })

        df_history = pd.concat([
            df_history, pd.DataFrame([{"player_name": name, "score": score, "date": heute_datum, "trophies": aktueller_trophy}])
        ], ignore_index=True)

    aktive_spieler = [p for p in player_stats if not p["is_urlaub"]]
    clan_avg = round(sum([p["score"] for p in aktive_spieler]) / len(aktive_spieler), 2) if aktive_spieler else 0
    
    top_performers = sorted(aktive_spieler, key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]), reverse=True)[:3]
    top_aufsteiger = sorted([p for p in aktive_spieler if p["delta"] > 0], key=lambda x: x["delta"], reverse=True)[:3]
    kritisch = sorted([p for p in aktive_spieler if p["score"] < 50 and p["teilnahme_int"] > 3], key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]))
    top_spender = sorted([p for p in aktive_spieler if p["donations"] > 0], key=lambda x: x["donations"], reverse=True)[:3]
    top_leecher = sorted([p for p in aktive_spieler if p["teilnahme_int"] > 3 and p["donations"] == 0 and p["donations_received"] > 0], key=lambda x: x["donations_received"], reverse=True)[:3]
    
    top_pusher = sorted(aktive_spieler, key=lambda x: x["trophy_push"], reverse=True)
    if top_pusher and top_pusher[0]["trophy_push"] > 0:
        pusher_name, pusher_val = top_pusher[0]["name"], top_pusher[0]["trophy_push"]
        pusher_html = f"<li><b>{pusher_name}</b> (+{pusher_val} 🏆)</li>"
        pusher_chat = f"🚀 Top-Pusher: {pusher_name} (+{pusher_val}🏆)"
    else:
        pusher_html = "<li>Niemand</li>"
        pusher_chat = ""

    radar_html = ""
    if radar_clans:
        radar_hint = f" <span style='font-size:0.8em; opacity:0.8; font-weight:normal;'>(Status: {race_state_de})</span>"
        radar_html = f"<div class='info-box' style='border-left-color: #f43f5e; background: rgba(159, 18, 57, 0.15);'><h3 style='margin-top: 0; color: #f43f5e; margin-bottom: 12px; font-size: 1.2em;'>📡 Live Kriegs-Radar{radar_hint}</h3>"
        for idx, c in enumerate(radar_clans):
            bold_start = "<b style='color:#fff;'>" if c["is_us"] else ""
            bold_end = " (WIR)</b>" if c["is_us"] else ""
            radar_html += f"<p style='margin: 0 0 5px 0;'>{idx+1}. {bold_start}{c['name']}{bold_end} - {c['fame']} Punkte</p>"
        radar_html += "</div>"

    cr_top_names = ", ".join([p['name'] for p in top_performers])
    cr_motiv = "Starke Woche! 💪" if clan_avg >= 80 else "Da geht noch mehr! ⚔️"
    cr_text_1 = f"1/3 📊 Clan-Ø: {clan_avg}%. MVPs: {cr_top_names} 🏆 {pusher_chat}"
    
    if top_spender:
        cr_text_2 = f"2/3 🃏 Ein fettes Lob an unsere Top-Spender: {', '.join([p['name'] for p in top_spender][:2])}! 🤝"
    else:
        cr_text_2 = "2/3 🃏 Diese Woche gab es leider kaum Spenden. Ein Clan lebt vom Geben UND Nehmen! 🤝"
        
    echte_leecher = [p for p in top_leecher if p["donations"] == 0 and p["donations_received"] > 0]
    if echte_leecher:
        cr_text_2 += f" | 🧛 Spenden-Leecher (0 geben, aber kassieren): {', '.join([p['name'] for p in echte_leecher][:2])}."
        
    if kritisch:
        krit_names_list = [p['name'] for p in kritisch]
        cr_krit_names = ", ".join(krit_names_list[:5]) + (f" (+{len(kritisch)-5})" if len(kritisch) > 5 else "")
        cr_text_3 = f"3/3 ⚠️ Kick-Liste/Warnung: {cr_krit_names}. Leistung reicht aktuell nicht. Bitte ranhalten oder abmelden! 🛡️"
    else:
        cr_text_3 = "3/3 🌟 Starke Woche: Niemand auf der Kick-Liste! Alle haben geliefert oder Urlaub angemeldet. 🛡️💪"

    tiers = ["🌟 Elite (95-100%)", "✅ Solides Mittelfeld (80-94%)", "⚠️ Unter Beobachtung (50-79%)", "🚫 Kritisch (< 50%)", "🏖️ Im Urlaub (Pausiert)"]
    
    html = f"""
    <html>
    <head>
        <meta charset='utf-8'>
        <title>Auswertung: {CLAN_NAME}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
            body {{ font-family: 'Nunito', sans-serif; margin: 0; padding: 20px; background: linear-gradient(rgba(15, 23, 42, 0.85), rgba(15, 23, 42, 0.95)), url('https://images.hdqwalls.com/download/clash-royale-4k-19-1920x1080.jpg') no-repeat center center fixed; background-size: cover; color: #f8fafc; }}
            .container {{ max-width: 1200px; margin: auto; }}
            .header-container {{ position: relative; background: linear-gradient(rgba(15, 23, 42, 0.7), rgba(15, 23, 42, 0.9)), url('{header_img_src}') no-repeat center center; background-size: cover; border-radius: 12px; padding: 40px 20px; margin-top: 20px; margin-bottom: 30px; text-align: center; border: 1px solid rgba(255, 255, 255, 0.1); box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3); }}
            .header-title {{ font-weight: 800; color: #ffffff; font-size: 2.2em; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.5); letter-spacing: 1px; }}
            .header-date {{ font-weight: 400; font-size: 0.45em; color: #cbd5e1; display: block; margin-top: 10px; letter-spacing: 0px; }}
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
            .card.kritisch {{ border-top: 4px solid #ef4444; }}
            .card.messenger {{ border-top: 4px solid #f1c40f; width: 100%; flex: 100%; }}
            .card h1 {{ font-weight: 800; font-size: 2.5em; margin: 10px 0; color: #38bdf8; }}
            .card ul {{ margin: 0; padding-left: 20px; font-size: 1.05em; line-height: 1.6; color: #f1f5f9; }}
            .tier-title {{ font-weight: 800; font-size: 1.4em; color: #fbbf24; margin-top: 45px; margin-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; }}
            table {{ width: 100%; border-collapse: collapse; background: rgba(15, 23, 42, 0.9); border-radius: 8px; margin-bottom: 30px; border: 1px solid rgba(255, 255, 255, 0.1); }}
            th:first-child {{ border-top-left-radius: 8px; }} th:last-child {{ border-top-right-radius: 8px; }}
            tr:last-child td:first-child {{ border-bottom-left-radius: 8px; }} tr:last-child td:last-child {{ border-bottom-right-radius: 8px; }}
            tr:nth-child(odd) {{ background-color: rgba(0, 0, 0, 0.45); }} tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.15); }} tr:hover {{ background-color: rgba(255, 255, 255, 0.3); }}
            th, td {{ padding: 14px 16px; text-align: left; }}
            th {{ background-color: rgba(0, 0, 0, 0.6); font-weight: 600; font-size: 0.9em; color: #94a3b8; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            td {{ border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 1.05em; }}
            .badge-ja {{ background-color: #10b981; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-weight: 800; font-size: 0.8em; margin-left: 8px; }}
            .name-col {{ font-weight: 800; color: #ffffff; }}
            .trend-cell {{ font-size: 16px !important; white-space: nowrap; line-height: 1; }}
            .custom-tooltip {{ position: relative; display: inline-block; cursor: help; }}
            .custom-tooltip.dotted {{ border-bottom: 1px dotted rgba(56, 189, 248, 0.5); }}
            .custom-tooltip .tooltip-text {{ visibility: hidden; width: max-content; background-color: rgba(15, 23, 42, 0.98); color: #fff; text-align: center; border-radius: 6px; padding: 6px 12px; position: absolute; z-index: 100; bottom: 140%; left: 50%; transform: translateX(-50%); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 10px rgba(0,0,0,0.4); opacity: 0; transition: opacity 0.2s ease-in-out; font-size: 0.9em; font-weight: normal; font-family: 'Nunito', sans-serif; }}
            .custom-tooltip .tooltip-text::after {{ content: ""; position: absolute; top: 100%; left: 50%; margin-left: -5px; border-width: 5px; border-style: solid; border-color: rgba(255, 255, 255, 0.2) transparent transparent transparent; }}
            .custom-tooltip.align-left .tooltip-text {{ left: 0; transform: none; }}
            .custom-tooltip.align-left .tooltip-text::after {{ left: 10px; margin-left: 0; }}
            .custom-tooltip:hover .tooltip-text {{ visibility: visible; opacity: 1; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-container">
                <h1 class="header-title">📊 Clan-Auswertung: {CLAN_NAME} <br><span class="header-date">{heute_datum}</span></h1>
            </div>
            
            {radar_html}
            
            <div class="info-box">
                <h3 style="margin-top: 0; color: #38bdf8; margin-bottom: 12px; font-size: 1.2em;">💡 So liest du diese Auswertung:</h3>
                <p style="margin: 0 0 10px 0;"><b>🏆 Wer steht oben? (Die Sortierung):</b> Die Liste ist streng nach Leistung sortiert. Wer 100% holt, steht oben. Bei Punktegleichstand gewinnt die Teilnahme-Treue, dann Kriegspunkte, zuletzt Spenden.</p>
                <p style="margin: 0 0 10px 0;"><b>📈 Delta (Entwicklung):</b> Zeigt die prozentuale Veränderung des Scores zur letzten Auswertung an (Grün = Aufstieg, Rot = Abfall).</p>
                <p style="margin: 0 0 10px 0;"><b>🌱 Welpenschutz (Neu im Clan?):</b> Spieler mit ≤ 3 Kriegen bekommen das 🌱-Symbol und sind vor Kick-Warnungen geschützt.</p>
                <p style="margin: 0 0 10px 0;"><b>🟢🟡🔴 Trend & Qualität (Die Ampel):</b> Zeigt die Leistung der letzten 4 Wochen. "Ø Punkte" zeigt die Punkte pro Deck. Ein ⚠️ bedeutet: Verdacht auf Bootsangriffe/Dropping (< 115 Pkt).</p>
                <p style="margin: 0 0 10px 0;"><b>🃏 Geben & Nehmen (Spenden):</b> Ein Clan lebt von der Gemeinschaft! <br><b>🧛 Vampir:</b> 0 gespendet, aber abkassiert. <br><b>💤 Schlafend:</b> 0 gespendet, 0 angefordert. <br><i>Tipp: Fahre mit der Maus am PC über die Spenden-Zahlen für Details!</i></p>
            </div>
            
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
                <div class="card aufsteiger">
                    <h3>🚀 Größte Aufsteiger</h3>
                    <ul>{''.join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger]) if top_aufsteiger else "<li>Keine Verbesserungen</li>"}</ul>
                </div>
                <div class="card leecher">
                    <h3>🧛 Top 3 Leecher</h3>
                    <ul>{''.join([f"<li><b>{p['name']}</b> ({p['donations']} gesp. / {p['donations_received']} empf.)</li>" for p in top_leecher]) if top_leecher else "<li>Keine Leecher! 🎉</li>"}</ul>
                </div>
                <div class="card kritisch">
                    <h3>⚠️ Kritische Fälle</h3>
                    <ul>{''.join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in kritisch]) if kritisch else "<li>Alles im grünen Bereich!</li>"}</ul>
                </div>
                
                <div class="card messenger">
                    <h3 style="color: #f1c40f; margin-bottom: 10px;">🎮 Clash Royale In-Game Chat (3-Teiler)</h3>
                    <p style="font-size: 0.9em; color: #cbd5e1; margin-top: 0; margin-bottom: 15px;">Kopiere diese 3 Texte nacheinander in den Clan-Chat (jeder Text ist garantiert unter 255 Zeichen).</p>
                    <label style="color: #38bdf8; font-weight: bold; font-size: 0.9em;">💬 Teil 1/3 (Ergebnis & MVPs):</label>
                    <textarea readonly style="width: 100%; height: 50px; background: rgba(0,0,0,0.4); color: #fff; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 8px; font-family: inherit; font-size: 0.95em; resize: none; margin-bottom: 15px;">{cr_text_1}</textarea>
                    <label style="color: #a855f7; font-weight: bold; font-size: 0.9em;">💬 Teil 2/3 (Spenden & Leecher):</label>
                    <textarea readonly style="width: 100%; height: 50px; background: rgba(0,0,0,0.4); color: #fff; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 8px; font-family: inherit; font-size: 0.95em; resize: none; margin-bottom: 15px;">{cr_text_2}</textarea>
                    <label style="color: #ef4444; font-weight: bold; font-size: 0.9em;">💬 Teil 3/3 (Warnungen):</label>
                    <textarea readonly style="width: 100%; height: 50px; background: rgba(0,0,0,0.4); color: #fff; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 8px; font-family: inherit; font-size: 0.95em; resize: none;">{cr_text_3}</textarea>
                </div>
            </div>

            <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 60px; color: #ffffff;">📋 Detaillierte Spielerliste</h2>
    """

    for t in tiers:
        players_in_tier = sorted([p for p in player_stats if p["tier"] == t], key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]), reverse=True)
        if players_in_tier:
            html += f"<div class='tier-title'>{t}</div>"
            html += "<table><tr><th>Spieler</th><th>Status</th><th>Score</th><th>Trend</th><th>Delta</th><th>Ø Punkte</th><th>🃏 Spenden</th><th>Teiln.</th><th>Kriegspunkte</th></tr>"
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
                
                html += f"<tr><td class='name-col'>{p['name']}{neu_badge}</td><td>{p['status']}</td><td><b>{p['score']}%</b></td><td class='trend-cell'>{p['trend_str']}</td><td style='color:{color}; font-weight:bold;'>{delta_s}%</td><td style='color:#cbd5e1;'>{p['fame_per_deck']}{p['leecher_warnung']}</td><td style='color:#38bdf8; font-weight:bold;'>{spenden_zelle}{spenden_warnung}</td><td>{p['teilnahme']}</td><td>{p['fame']}</td></tr>"
            html += "</table>"
            
    html += "</div></body></html>"

    return html, df_history, cr_text_1, cr_text_2, cr_text_3, records

def speichere_html_bericht(html_content: str, df_history: pd.DataFrame, records: dict, file_suffix: str) -> Path:
    html_path = output_folder / f"auswertung_{file_suffix}.html"
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html_content)
        
    index_path = BASE_DIR / "index.html"
    with index_path.open("w", encoding="utf-8") as f:
        f.write(html_content)
        
    df_history.to_csv(score_history_path, index=False)
    
    with open(records_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=4)
        
    return html_path

def archiviere_alte_auswertungen(output_dir: Path, anzahl: int = 2):
    archiv_output = output_dir / "archiv"
    archiv_output.mkdir(exist_ok=True, parents=True)
    alte_htmls = sorted(output_dir.glob("auswertung_*.html"), key=os.path.getctime)
    for file in alte_htmls[:-anzahl]:
        shutil.move(str(file), archiv_output / file.name)

def sende_bericht_per_mail(absender: str, empfänger: str, smtp_server: str, port: int, passwort: str, html_path: Path, cr_text_1: str, cr_text_2: str, cr_text_3: str):
    msg = EmailMessage()
    msg["Subject"] = f"📊 Clan-Auswertung: {CLAN_NAME}"
    msg["From"] = absender
    msg["To"] = empfänger
    
    with html_path.open("r", encoding="utf-8") as f:
        html_content = f.read()

    text_fallback = f"Hallo Clan-Führung,\nHIER SIND DEINE IN-GAME CHAT TEXTE ZUM KOPIEREN:\n\n{cr_text_1}\n\n{cr_text_2}\n\n{cr_text_3}"
    msg.set_content(text_fallback)
    msg.add_alternative(html_content, subtype='html')
    with html_path.open("rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="html", filename=html_path.name)

    try:
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls()
            server.login(absender, passwort)
            server.send_message(msg)
            print("✅ E-Mail erfolgreich gesendet.")
    except Exception as e:
        print(f"❌ FEHLER beim Senden der E-Mail: {e}")

# === 4. Hauptsteuerung ===

def main():
    upload_folder.mkdir(parents=True, exist_ok=True)
    archiv_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    print("=== STARTE CLAN-DATEN ABRUF ===")
    if not fetch_and_build_player_csv(): return
    
    print("Schritt 3: Rufe Live-Radar (Current River Race) ab...")
    radar_clans = []
    race_state_de = "Live"
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
                
                radar_clans.append({
                    "name": c.get("name", ""), "fame": pts, "is_us": c.get("tag") == CLAN_TAG.replace("%23", "#")
                })
            radar_clans.sort(key=lambda x: x["fame"], reverse=True)
    except Exception as e:
        print(f"Warnung: Radar konnte nicht geladen werden ({e})")

    # JSON SICHER LADEN
    records = {"donations": {"name": "-", "val": 0}, "delta": {"name": "-", "val": 0}, "trophies": {"name": "-", "val": 0}}
    if records_path.exists():
        try:
            with open(records_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                records.update(loaded)
        except Exception as e:
            print(f"⚠️ Warnung: records.json fehlerhaft, fange bei 0 an. ({e})")

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
    
    html_bericht, df_history, cr_text_1, cr_text_2, cr_text_3, updated_records = generate_html_report(df_active, df_history, fame_spalte, heute_datum, encoded_header_img, radar_clans, records, race_state_de)

    html_path = speichere_html_bericht(html_bericht, df_history, updated_records, jetzt_datei)
    archiviere_alte_auswertungen(output_folder)
    
    # === E-MAIL ZEITSTEUERUNG ===
    sender_mail = os.environ.get("EMAIL_SENDER")
    receiver_mail = os.environ.get("EMAIL_RECEIVER")
    email_pass = os.environ.get("EMAIL_PASS")
    
    ist_manueller_start = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    jetzt_utc = datetime.utcnow()
    ist_montag = jetzt_utc.weekday() == 0
    ist_mail_zeit = jetzt_utc.hour in [9, 10, 11]
    
    if sender_mail and receiver_mail and email_pass:
        if (ist_montag and ist_mail_zeit) or ist_manueller_start:
            print("=== SENDE BERICHT ===")
            sende_bericht_per_mail(
                absender=sender_mail, 
                empfänger=receiver_mail, 
                smtp_server="mx.freenet.de",
                port=587, 
                passwort=email_pass, 
                html_path=html_path,
                cr_text_1=cr_text_1, 
                cr_text_2=cr_text_2, 
                cr_text_3=cr_text_3
            )
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
