import os
import glob
import shutil
import subprocess
import platform
import requests
import csv
import base64
from datetime import datetime
from typing import List, Tuple
from pathlib import Path

import pandas as pd

from email.message import EmailMessage
import smtplib
from dotenv import load_dotenv

# === 1. Konfiguration & Pfade ===
load_dotenv()

# API Settings (Token unbedingt eintragen!)
API_TOKEN = os.environ.get("SUPERCELL_API_TOKEN", "DEIN_TOKEN_HIER")
BASE_URL = "https://proxy.royaleapi.dev/v1"
CLAN_TAG = "%23Y9YQC8UG"
CLAN_NAME = "HAMBURG"

# Feste Ordnerstruktur in C:\WarLog Paul
BASE_DIR = Path(r"C:\WarLog Paul")
upload_folder = BASE_DIR / "uploads"
archiv_folder = upload_folder / "archiv"
output_folder = BASE_DIR / "output"
score_history_path = BASE_DIR / "score_history.csv"

# Pfad zum Hintergrundbild für den Header-Bereich
HEADER_IMAGE_PATH = BASE_DIR / "clash_pix.jpg"

# === 2. API Datenabruf ===

def fetch_and_build_player_csv() -> bool:
    if not API_TOKEN or API_TOKEN == "DEIN_TOKEN_HIER":
        print("Fehler: Bitte trage deinen API_TOKEN im Code oder in der .env Datei ein.")
        return False

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Accept": "application/json"
    }

    print("Schritt 1: Rufe aktuelle Mitgliederliste ab...")
    members_url = f"{BASE_URL}/clans/{CLAN_TAG}/members"
    members_resp = requests.get(members_url, headers=headers)
    
    if members_resp.status_code != 200:
        print(f"Fehler beim Abruf der Mitglieder: {members_resp.status_code}")
        return False
        
    current_members = {
        m["tag"]: {"name": m["name"], "role": m.get("role", "member")} 
        for m in members_resp.json().get("items", [])
    }

    print("Schritt 2: Rufe Warlog (River Races) ab...")
    log_url = f"{BASE_URL}/clans/{CLAN_TAG}/riverracelog"
    log_resp = requests.get(log_url, headers=headers)
    
    if log_resp.status_code != 200:
        print(f"Fehler beim Abruf des Warlogs: {log_resp.status_code}")
        return False

    races = log_resp.json().get("items", [])
    print(f"{len(races)} Kriege gefunden. Verarbeite Spielerdaten...")

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
                    players_data[ptag] = {"name": pname, "is_current": is_curr, "role": role, "history": {}}
                players_data[ptag]["history"][race_id] = {"decks": decks, "fame": fame}

    for tag, data in current_members.items():
        if tag not in players_data:
            players_data[tag] = {"name": data["name"], "is_current": True, "role": data["role"], "history": {}}
        
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = upload_folder / f"clan_export_{date_str}.csv"

    race_ids = sorted(list(set(race_ids)), reverse=True)
    headers_csv = [
        "player_tag", "player_name", "player_is_current_member", "player_role",
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
                    
            row = [tag, data["name"], data["is_current"], data["role"], contribution_count, total_races, total_decks]
            row.extend(row_history)
            writer.writerow(row)
            
    print(f"✅ Spieler-Daten erfolgreich exportiert nach: {filename}\n")
    return True

# === 3. Auswertung & kreatives HTML-Design ===

def get_encoded_header_image(path: Path) -> str:
    if not path.exists():
        print(f"⚠️ Warnung: Hintergrundbild für Header '{path}' nicht gefunden.")
        return ""
    try:
        with open(path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return f"data:image/jpeg;base64,{encoded_string}"
    except Exception as e:
        print(f"❌ Fehler beim Kodieren des Header-Bildes: {e}")
        return ""

def archiviere_alte_dateien(ordner: Path, archiv_ordner: Path, anzahl: int = 2) -> None:
    archiv_ordner.mkdir(exist_ok=True, parents=True)
    dateien = sorted(ordner.glob("*.csv"), key=os.path.getctime)
    for datei in dateien[:-anzahl]:
        shutil.move(str(datei), archiv_ordner / datei.name)

def finde_neueste_csv(ordner: Path) -> Path:
    csvs = list(ordner.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError("Keine CSV-Datei im Upload-Ordner gefunden.")
    return max(csvs, key=os.path.getctime)

def berechne_score(participation: int, decks_total: int) -> float:
    max_mögliche_decks = participation * 16
    if max_mögliche_decks <= 0: return 0.0
    return round((decks_total / max_mögliche_decks) * 100, 2)

def generate_html_report(df_active: pd.DataFrame, df_history: pd.DataFrame, fame_spalte: str, heute_datum: str, header_img_src: str) -> Tuple[str, pd.DataFrame]:
    player_stats = []
    
    role_map = {
        "member": "Mitglied", "elder": "Ältester", "coLeader": "Vize",
        "leader": "Anführer", "unknown": "Ehemalig"
    }

    for _, row in df_active.iterrows():
        name = row.get("player_name", "Unbekannt")
        raw_role = row.get("player_role", "unknown")
        role_de = role_map.get(raw_role, raw_role)
        
        participation = int(row.get("player_contribution_count", 0) or 0)
        decks_total = int(row.get("player_total_decks_used", 0) or 0)
        score = berechne_score(participation, decks_total)
        aktueller_fame = int(row.get(fame_spalte, 0) or 0)
        
        if raw_role == "member" and aktueller_fame >= 2800:
            status_html = f"{role_de} <span class='badge-ja'>➔ BEFÖRDERN</span>"
        else:
            status_html = role_de

        vorher = df_history[df_history["player_name"] == name].sort_values("date").tail(1)
        delta = round(score - vorher["score"].values[0], 2) if not vorher.empty else 0.0

        if score >= 95: tier = "🌟 Elite (95-100%)"
        elif score >= 80: tier = "✅ Solides Mittelfeld (80-94%)"
        elif score >= 50: tier = "⚠️ Unter Beobachtung (50-79%)"
        else: tier = "🚫 Kritisch (< 50%)"

        player_stats.append({
            "name": name, "status": status_html, "score": score, "delta": delta,
            "teilnahme": f"{participation}/{int(row.get('player_participating_count', 0) or 0)}",
            "fame": aktueller_fame, "tier": tier
        })

        df_history = pd.concat([
            df_history, pd.DataFrame([{"player_name": name, "score": score, "date": heute_datum}])
        ], ignore_index=True)

    clan_avg = round(sum([p["score"] for p in player_stats]) / len(player_stats), 2) if player_stats else 0
    top_performers = sorted(player_stats, key=lambda x: x["score"], reverse=True)[:3]
    top_aufsteiger = sorted([p for p in player_stats if p["delta"] > 0], key=lambda x: x["delta"], reverse=True)[:3]
    kritisch = sorted([p for p in player_stats if p["score"] < 50], key=lambda x: x["score"])

    tiers = ["🌟 Elite (95-100%)", "✅ Solides Mittelfeld (80-94%)", "⚠️ Unter Beobachtung (50-79%)", "🚫 Kritisch (< 50%)"]
    
    html = f"""
    <html>
    <head>
        <meta charset='utf-8'>
        <title>Auswertung: {CLAN_NAME}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
            
            body {{ 
                font-family: 'Nunito', sans-serif; 
                margin: 0; padding: 20px; 
                background: linear-gradient(rgba(15, 23, 42, 0.85), rgba(15, 23, 42, 0.95)), 
                            url('https://images.hdqwalls.com/download/clash-royale-4k-19-1920x1080.jpg') no-repeat center center fixed; 
                background-size: cover;
                color: #f8fafc;
            }}
            
            .container {{ max-width: 1200px; margin: auto; }}
            
            .header-container {{ 
                position: relative; 
                background: linear-gradient(rgba(15, 23, 42, 0.7), rgba(15, 23, 42, 0.9)), 
                            url('{header_img_src}') no-repeat center center; 
                background-size: cover;
                border-radius: 12px; 
                padding: 40px 20px;
                margin-top: 20px;
                margin-bottom: 40px;
                text-align: center; 
                border: 1px solid rgba(255, 255, 255, 0.1); 
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
            }}

            .header-title {{ 
                font-weight: 800;
                color: #ffffff; 
                font-size: 2.2em; 
                margin: 0;
                text-shadow: 0 2px 4px rgba(0,0,0,0.5);
            }}
            .header-date {{ font-weight: 400; font-size: 0.45em; color: #cbd5e1; display: block; margin-top: 10px; }}

            .dashboard {{ display: flex; gap: 20px; margin-bottom: 50px; flex-wrap: wrap; }}
            .card {{ 
                flex: 1; min-width: 240px; 
                background: rgba(30, 41, 59, 0.8); 
                padding: 20px 25px; 
                border-radius: 12px; 
                border: 1px solid rgba(255, 255, 255, 0.08); 
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            }}
            
            .card h3 {{ font-weight: 600; font-size: 1.1em; margin-top: 0; color: #cbd5e1; }}
            .card.avg {{ border-top: 4px solid #38bdf8; }}
            .card.top {{ border-top: 4px solid #fbbf24; }}
            .card.aufsteiger {{ border-top: 4px solid #10b981; }}
            .card.kritisch {{ border-top: 4px solid #ef4444; }}
            
            .card h1 {{ font-weight: 800; font-size: 2.5em; margin: 10px 0; color: #38bdf8; }}
            .card ul {{ margin: 0; padding-left: 20px; font-size: 1.05em; line-height: 1.6; color: #f1f5f9; }}
            
            .tier-title {{ 
                font-weight: 800;
                font-size: 1.4em; 
                color: #fbbf24; 
                margin-top: 45px; 
                margin-bottom: 15px;
                border-bottom: 1px solid rgba(255,255,255,0.1);
                padding-bottom: 8px;
            }}
            
            table {{ 
                width: 100%; border-collapse: collapse; 
                background: rgba(15, 23, 42, 0.9); 
                border-radius: 8px; 
                overflow: hidden; margin-bottom: 30px; 
                border: 1px solid rgba(255, 255, 255, 0.1); 
            }}
            
            tr:nth-child(odd) {{ background-color: rgba(0, 0, 0, 0.45); }}
            tr:nth-child(even) {{ background-color: rgba(255, 255, 255, 0.15); }}
            tr:hover {{ background-color: rgba(255, 255, 255, 0.3); }}
            
            th, td {{ padding: 14px 16px; text-align: left; }}
            th {{ background-color: rgba(0, 0, 0, 0.6); font-weight: 600; font-size: 0.9em; color: #94a3b8; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            td {{ border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 1.05em; }}
            
            .badge-ja {{ 
                background-color: #10b981; color: #ffffff; 
                padding: 4px 10px; border-radius: 6px; 
                font-weight: 800; font-size: 0.8em; 
                margin-left: 8px;
                letter-spacing: 0.5px;
            }}
            .name-col {{ font-weight: 800; color: #ffffff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-container">
                <h1 class="header-title">📊 Clan-Auswertung: {CLAN_NAME} <br><span class="header-date">{heute_datum}</span></h1>
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
                <div class="card aufsteiger">
                    <h3>🚀 Größte Aufsteiger</h3>
                    <ul>{''.join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger]) if top_aufsteiger else "<li>Keine Verbesserungen</li>"}</ul>
                </div>
                <div class="card kritisch">
                    <h3>⚠️ Kritische Fälle</h3>
                    <ul>{''.join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in kritisch]) if kritisch else "<li>Alles im grünen Bereich!</li>"}</ul>
                </div>
            </div>

            <h2 style="font-weight: 800; font-size: 1.8em; text-align: center; margin-top: 60px; color: #ffffff;">📋 Detaillierte Spielerliste</h2>
    """

    for t in tiers:
        players_in_tier = sorted([p for p in player_stats if p["tier"] == t], key=lambda x: x["score"], reverse=True)
        if players_in_tier:
            html += f"<div class='tier-title'>{t}</div>"
            html += "<table><tr><th>Spieler</th><th>Status</th><th>Score</th><th>Delta</th><th>Teilnahme</th><th>Fame</th></tr>"
            for p in players_in_tier:
                delta_s = f"+{p['delta']}" if p['delta']>0 else f"{p['delta']}"
                color = "#10b981" if p['delta'] > 0 else "#ef4444" if p['delta'] < 0 else "#94a3b8"
                
                html += f"<tr><td class='name-col'>{p['name']}</td><td>{p['status']}</td><td><b>{p['score']}%</b></td><td style='color:{color}; font-weight:bold;'>{delta_s}%</td><td>{p['teilnahme']}</td><td>{p['fame']}</td></tr>"
            html += "</table>"
            
    html += "</div></body></html>"

    return html, df_history

def speichere_html_bericht(html_content: str, df_history: pd.DataFrame, file_suffix: str) -> Path:
    html_path = output_folder / f"auswertung_{file_suffix}.html"
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html_content)
        
    df_history.to_csv(score_history_path, index=False)
    return html_path

def archiviere_alte_auswertungen(output_dir: Path, anzahl: int = 2):
    archiv_output = output_dir / "archiv"
    archiv_output.mkdir(exist_ok=True, parents=True)
    
    alte_htmls = sorted(output_dir.glob("auswertung_*.html"), key=os.path.getctime)
    for file in alte_htmls[:-anzahl]:
        shutil.move(str(file), archiv_output / file.name)

def sende_bericht_per_mail(absender: str, empfänger: str, smtp_server: str, port: int, passwort: str, html_path: Path):
    if not passwort: return

    msg = EmailMessage()
    msg["Subject"] = f"📊 Clan-Auswertung: {CLAN_NAME}"
    msg["From"] = absender
    msg["To"] = empfänger
    
    # NEU: Professioneller und ausführlicher Begleittext für die E-Mail
    email_text = f"""Hallo Clan-Führung,

die Berechnungen für die aktuelle Kriegswoche von "{CLAN_NAME}" sind abgeschlossen. Das vollständige Dashboard liegt im Anhang für dich bereit!

Hier ist ein kurzer Überblick, was dich in der Auswertung erwartet:
📈 Der aktuelle Clan-Durchschnitts-Score
🏆 Die Top-Performer und größten Aufsteiger der Woche
🚀 Klare Beförderungs-Empfehlungen (Mitglied ➔ Ältester)
⚠️ Die Liste der kritischen Fälle (Kick-Kandidaten)

Lade die angehängte HTML-Datei einfach herunter und öffne sie in einem beliebigen Webbrowser (Chrome, Safari, Firefox etc.). Das Dashboard passt sich automatisch an deinen PC-Bildschirm oder dein Smartphone an.

Viel Erfolg bei der Clan-Verwaltung!

Beste Grüße
Dein automatischer Auswertungs-Bot 🤖
"""
    msg.set_content(email_text)

    with html_path.open("rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="html", filename=html_path.name)

    try:
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls()
            server.login(absender, passwort)
            server.send_message(msg)
        print("✅ E-Mail erfolgreich gesendet.")
    except Exception as e:
        print(f"❌ Fehler beim Senden der E-Mail: {e}")

# === 4. Hauptsteuerung ===

def main():
    upload_folder.mkdir(parents=True, exist_ok=True)
    archiv_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    print("=== STARTE CLAN-DATEN ABRUF ===")
    if not fetch_and_build_player_csv(): return

    print("=== STARTE AUSWERTUNG ===")
    archiviere_alte_dateien(upload_folder, archiv_folder)

    try:
        csv_path = finde_neueste_csv(upload_folder)
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Fehler beim Einlesen der CSV: {e}")
        return

    df_active = df[df.get("player_is_current_member", False) == True].copy()
    fame_columns = sorted([col for col in df.columns if col.startswith("s_") and col.endswith("_fame")], reverse=True)
    
    if not fame_columns: return
    fame_spalte = fame_columns[0]

    if score_history_path.exists(): df_history = pd.read_csv(score_history_path)
    else: df_history = pd.DataFrame(columns=["player_name", "score", "date"])

    heute_datum = datetime.today().strftime("%Y-%m-%d")
    jetzt_datei = datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
    
    encoded_header_img = get_encoded_header_image(HEADER_IMAGE_PATH)
    
    html_bericht, df_history = generate_html_report(df_active, df_history, fame_spalte, heute_datum, encoded_header_img)

    html_path = speichere_html_bericht(html_bericht, df_history, jetzt_datei)

    archiviere_alte_auswertungen(output_folder)
    
    print("Öffne HTML-Bericht im Browser...")
    if platform.system() == "Windows":
        os.startfile(html_path)

    print("Sende E-Mail...")
    sende_bericht_per_mail(
        absender="bassabello@bossmail.de",
        empfänger="strike2005-2012@yahoo.de",
        smtp_server="mx.freenet.de",
        port=587,
        passwort=os.environ.get("EMAIL_PASS"),
        html_path=html_path
    )
    
    print("\n=== ALLES ERFOLGREICH ABGESCHLOSSEN ===")

if __name__ == "__main__":
    main() 
