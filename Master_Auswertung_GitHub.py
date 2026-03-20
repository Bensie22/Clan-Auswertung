def generate_html_report(df_active: pd.DataFrame, df_history: pd.DataFrame, fame_spalte: str, heute_datum: str, header_img_src: str, radar_clans: list, records: dict, strikes_data: dict, race_state_de: str, raw_mahnwache: list, top_decks_data: dict, echte_neulinge: list, rueckkehrer: list, kicked_players: dict) -> Tuple[str, pd.DataFrame, str, dict, dict, dict]:
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
    ist_montag = datetime.utcnow().weekday() == 0
    ist_mail_zeit = datetime.utcnow().hour in [9, 10, 11]
    ist_manueller_start = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    apply_strikes_now = False
    if (ist_montag and ist_mail_zeit) or ist_manueller_start:
        if last_strike_week != curr_week:
            apply_strikes_now = True
            strikes_data["last_strike_week"] = curr_week
            strikes_data["demoted_this_week"] = []
            strikes_data["kicked_this_week"] = []

    # Alle sichtbaren War-Spalten ermitteln
    all_fame_cols = sorted(
        [col for col in df_active.columns if col.startswith("s_") and col.endswith("_fame")],
        reverse=True
    )

    all_deck_cols = [col.replace("_fame", "_decks_used") for col in all_fame_cols]

    for _, row in df_active.iterrows():
        raw_role = str(row.get("player_role", "unknown")).strip().lower()
        if raw_role == "unknown":
            continue

        name = row.get("player_name", "Unbekannt")
        role_de = role_map.get(raw_role, raw_role.capitalize())
        is_urlaub = name in urlauber_liste

        donations = int(row.get("player_donations", 0) or 0)
        donations_received = int(row.get("player_donations_received", 0) or 0)
        aktueller_trophy = int(row.get("player_trophies", 0) or 0)

        # Anzeige: in wie vielen sichtbaren Kriegen wurde mindestens 1 Deck gespielt?
        sichtbare_teilnahmen = int(row.get("player_contribution_count", 0) or 0)
        sichtbare_kriege = int(row.get("player_participating_count", 0) or 0)

        # Wiki-nahe Logik:
        # Relevante Kriege beginnen ab dem ersten Krieg, in dem Aktivität sichtbar ist.
        race_data = []
        for fame_col, deck_col in zip(all_fame_cols, all_deck_cols):
            fame_val = int(row.get(fame_col, 0) or 0)
            deck_val = int(row.get(deck_col, 0) or 0)
            race_data.append({
                "fame_col": fame_col,
                "deck_col": deck_col,
                "fame": fame_val,
                "decks": deck_val
            })

        first_active_index = None
        for idx, r in enumerate(race_data):
            if r["decks"] > 0 or r["fame"] > 0:
                first_active_index = idx
                break

        if first_active_index is None:
            relevante_races = []
        else:
            relevante_races = race_data[first_active_index:]

        relevante_kriege = len(relevante_races)
        relevante_decks_total = sum(r["decks"] for r in relevante_races)
        max_moegliche_decks = relevante_kriege * 16

        score = round((relevante_decks_total / max_moegliche_decks) * 100, 2) if max_moegliche_decks > 0 else 0.0

        # Welpenschutz explizit und unabhängig von der Tabellenanzeige merken
        is_welpenschutz = (0 < relevante_kriege <= APP_CONFIG["MIN_PARTICIPATION"])

        aktueller_fame = int(row.get(fame_spalte, 0) or 0)
        aktueller_decks_spalte = fame_spalte.replace("_fame", "_decks_used")
        aktueller_decks = int(row.get(aktueller_decks_spalte, 0) or 0)
        fame_per_deck = round(aktueller_fame / aktueller_decks) if aktueller_decks > 0 else 0

        leecher_warnung = ""
        if 0 < fame_per_deck < APP_CONFIG["DROPPER_THRESHOLD"]:
            leecher_warnung = " <span class='custom-tooltip'>⚠️<span class='tooltip-text'>Verdacht: Zieht nur Punkte ab (verliert absichtlich/greift Boote an)</span></span>"

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
        trend_str = "".join(
            ["🟢" if s >= 80 else "🟡" if s >= APP_CONFIG["STRIKE_THRESHOLD"] else "🔴" for s in trend_scores[-4:]]
        )

        streak_count = 0
        for s in reversed(trend_scores):
            if s >= 100.0:
                streak_count += 1
            else:
                break

        # Sicherheitsgrenze: nicht mehr Streak anzeigen als es überhaupt relevante Kriege gibt
        if relevante_kriege > 0 and streak_count > relevante_kriege:
            streak_count = relevante_kriege

        streak_badge = ""
        if streak_count >= 3:
            streak_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>🔥{streak_count}"
                f"<span class='tooltip-text'>{streak_count} Auswertungen in Folge 100% Score!</span></span>"
            )

        # Verwarnungen nur anwenden, wenn kein Urlaub und kein Welpenschutz mehr greift
        if apply_strikes_now:
            if not is_urlaub and not is_welpenschutz and relevante_kriege > APP_CONFIG["MIN_PARTICIPATION"]:
                if score < APP_CONFIG["STRIKE_THRESHOLD"]:
                    strikes[name] = strikes.get(name, 0) + 1
                else:
                    if strikes.get(name, 0) > 0:
                        strikes[name] -= 1

        strike_val = strikes.get(name, 0)

        if apply_strikes_now and strike_val >= 3:
            if not is_urlaub:
                if raw_role in ["elder", "coleader"]:
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
                "<span class='tooltip-text'>3 Verwarnungen: Verabschiedung!</span></span>"
            )
        elif strike_val > 0:
            strike_badge = (
                f" <span class='custom-tooltip align-left' style='font-size: 0.9em;'>❌ {strike_val}/3"
                "<span class='tooltip-text'>Verwarnung! Bei 3/3 droht Kick/Degradierung.</span></span>"
            )

        if is_urlaub:
            status_html = "🏖️ Urlaub"
            tier = "🏖️ Im Urlaub (Pausiert)"
        else:
            status_html = f"{role_de} <span class='badge-ja'>➔ BEFÖRDERN</span>" if raw_role == "member" and aktueller_fame >= 2800 else role_de

            if score >= 95:
                tier = "🌟 Elite (95-100%)"
            elif score >= 80:
                tier = "✅ Solides Mittelfeld (80-94%)"
            elif score >= APP_CONFIG["STRIKE_THRESHOLD"]:
                tier = f"⚠️ Unter Beobachtung ({APP_CONFIG['STRIKE_THRESHOLD']}-79%)"
            else:
                tier = f"🚫 Kritisch (< {APP_CONFIG['STRIKE_THRESHOLD']}%)"

        player_stats.append({
            "name": name,
            "status": status_html,
            "score": score,
            "delta": delta,
            "teilnahme": f"{sichtbare_teilnahmen}/{sichtbare_kriege}",
            "teilnahme_int": sichtbare_teilnahmen,
            "fame": aktueller_fame,
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
            "raw_role": raw_role,
            "relevante_kriege": relevante_kriege
        })

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

    # Historie nur für aktive behalten, max. letzte 6 Einträge je Spieler
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
        [p for p in aktive_spieler if p["relevante_kriege"] > APP_CONFIG["MIN_PARTICIPATION"] and p["donations"] == 0 and p["donations_received"] > 0],
        key=lambda x: x["donations_received"],
        reverse=True
    )[:3]

    top_performers_html = ''.join([f"<li><b>{p['name']}</b> ({p['score']}%)</li>" for p in top_performers_list])
    top_aufsteiger_html = ''.join([f"<li><b>{p['name']}</b> (+{p['delta']}%)</li>" for p in top_aufsteiger_list]) if top_aufsteiger_list else "<li>Keine Verbesserungen</li>"
    top_spender_html = ''.join([f"<li><b>{p['name']}</b> ({p['donations']})</li>" for p in top_spender_list]) if top_spender_list else "<li>Keine Spenden</li>"
    top_leecher_html = ''.join([f"<li><b>{p['name']}</b> ({p['donations']} gesp. / {p['donations_received']} empf.)</li>" for p in top_leecher_list]) if top_leecher_list else "<li>Keine Leecher! 🎉</li>"

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
        radar_html += "<div style='overflow-x: auto;'><table style='width: 100%; border-collapse: collapse; font-size: 0.95em;'>"
        radar_html += "<tr style='border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-weight: 600; text-align: left;'><td style='padding-bottom: 8px; border: none; text-align: left;'>Clan</td><td style='padding-bottom: 8px; border: none; text-align: center;'>⛵ Boot</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🥇 Medaille</td><td style='padding-bottom: 8px; border: none; text-align: center;'>🏆 Trophäe</td></tr>"

        for idx, c in enumerate(radar_clans):
            bold_name = f"<b style='color:#fff;'>{c['name']} (WIR)</b>" if c["is_us"] else c['name']
            bg_color = "rgba(255,255,255,0.05)" if idx % 2 == 0 else "transparent"
            radar_html += f"<tr style='background: {bg_color}; border-bottom: 1px solid rgba(255,255,255,0.02);'>"
            radar_html += f"<td style='padding: 10px 5px;'>{bold_name}<br><span style='font-size: 0.8em; color: #cbd5e1;'>🃏 {c['decks_used']} / 200 Decks</span></td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #f8fafc;'>{c['fame']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #fbbf24;'>{c['medals']}</td>"
            radar_html += f"<td style='text-align: center; font-weight: bold; color: #c084fc;'>{c['trophies']}</td>"
            radar_html += "</tr>"
        radar_html += "</table></div></div>"

    mahnwache_html = ""
    ist_kampftag = datetime.utcnow().weekday() in [0, 3, 4, 5, 6]

    total_active_players = len(aktive_spieler)
    total_decks_today = total_active_players * 4
    total_open_decks = 0
    hype_balken_html = ""

    if ist_kampftag:
        aktive_namen_list = df_active["player_name"].tolist()
        gefilterte_mahnwache = []
        for m in raw_mahnwache:
            if m['name'] not in urlauber_liste and m['name'] in aktive_namen_list:
                gefilterte_mahnwache.append(f"<b>{m['name']}</b> ({m['offen']} offen)")
                total_open_decks += m['offen']

        if gefilterte_mahnwache:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #ef4444; background: rgba(239, 68, 68, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #ef4444; margin-bottom: 8px;'>⏰ Mahnwache (Noch offene Decks heute):</h4><p style='margin: 0; font-size: 0.95em;'>{', '.join(gefilterte_mahnwache)}</p></div>"
        else:
            mahnwache_html = f"<div class='info-box' style='border-left-color: #10b981; background: rgba(16, 185, 129, 0.15); padding: 15px 25px; margin-bottom: 40px;'><h4 style='margin-top: 0; color: #10b981; margin-bottom: 0;'>✅ Alle aktiven Spieler haben ihre Decks für heute gespielt!</h4></div>"

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

    cr_top_names = ", ".join([p['name'] for p in top_performers_list])
    top_spender_names = ", ".join([p['name'] for p in top_spender_list][:2])
    echte_leecher = [p for p in top_leecher_list if p["donations"] == 0 and p["donations_received"] > 0]
    leecher_names = ", ".join([p['name'] for p in echte_leecher][:2]) if echte_leecher else ""

    chat_blocks = []

    if echte_neulinge:
        names_str = ", ".join(echte_neulinge)
        welcome_vars = {
            "Sachlich": f"👋 Willkommen {names_str}. Viel Spaß und Erfolg bei und mit uns. Alles Wichtige steht in der Info.",
            "Motivierend": f"🎉 Herzlich willkommen in der HAMBURG-Family, {names_str}! Viel Spaß und Erfolg bei und mit uns. Alles Wichtige steht in der Info.",
            "Kurz & Knackig": f"👋 Moin {names_str}! Willkommen im Clan. Viel Spaß und Erfolg bei und mit uns. Alles Wichtige steht in der Info."
        }
        chat_blocks.append(welcome_vars)

    if rueckkehrer:
        names_str = ", ".join(rueckkehrer)
        rueckkehrer_vars = {
            "Sachlich": f"⚠️ Info an die Vizes: {names_str} ist wieder beigetreten. Dieser Spieler wurde in der Vergangenheit wegen Inaktivität im Clankrieg gekickt.",
            "Motivierend": f"👀 {names_str} ist zurück! Wurde früher wegen Kriegsinaktivität entfernt. Lasst uns schauen, ob es dieses Mal klappt. Bitte im Auge behalten!",
            "Kurz & Knackig": f"🚨 Achtung: Rückkehrer {names_str} erkannt. (Ehemaliger Kick wegen Inaktivität)."
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
        msg_2_sachlich += f" | 🧛 Spenden-Leecher (nur kassiert): {leecher_names}."
    msg_2_motiv = f"💚 Wahnsinn, was ihr spendet! Top-Supporter: {top_spender_names}. Danke fürs Karten teilen!" if top_spender_list else "💚 Vergesst das Spenden nicht, Team! Jeder braucht mal Karten."
    msg_2_streng = f"⚠️ Spenden-Check: Danke an {top_spender_names}." if top_spender_list else "⚠️ Null Spenden-Moral diese Woche!"
    if echte_leecher:
        msg_2_streng += f" Die Leecher-Liste (nehmen ohne geben): {leecher_names}. Das muss besser werden!"

    msg_2_vars = {
        "Sachlich": msg_2_sachlich,
        "Motivierend": msg_2_motiv,
        "Kurz & Knackig": msg_2_streng
    }
    chat_blocks.append(msg_2_vars)

    dropper_names = [p['name'] for p in aktive_spieler if 0 < p['fame_per_deck'] < APP_CONFIG["DROPPER_THRESHOLD"] and not p['is_urlaub']]
    if dropper_names:
        names_str = ", ".join(dropper_names)
        dropper_vars = {
            "Sachlich": f"⚠️ Hinweis an {names_str}: Euer Punkteschnitt pro Deck ist auffällig niedrig (<{APP_CONFIG['DROPPER_THRESHOLD']}). Bitte greift keine feindlichen Boote an und gebt Kämpfe nicht absichtlich auf. Der Clan braucht jeden Punkt in echten Duellen! ⚔️",
            "Motivierend": f"💡 Kleiner Tipp an {names_str}: Normale Kämpfe oder Duelle bringen dem Clan viel mehr Punkte als Bootsangriffe! Spielt eure Decks am besten in den normalen Modi aus, auch wenn ihr mal verliert. Ihr schafft das! 💪",
            "Kurz & Knackig": f"⚠️ Bootsangriffe / Kampf-Aufgabe entdeckt bei: {names_str}. Bitte ab sofort normale Kämpfe machen, das bringt deutlich mehr Punkte für den Clan!"
        }
        chat_blocks.append(dropper_vars)

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
    colors = ["#38bdf8", "#a855f7", "#ef4444", "#f97316", "#10b981", "#fbbf24", "#6366f1", "#ec4899"]
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
            players_str = ", ".join(d["players"][:3]) + ("..." if len(d["players"]) > 3 else "")

            archetype = get_deck_archetype(d["cards"])
            api_names = [c["name"].lower().replace(".", "").replace(" ", "-") for c in d["cards"]]
            royaleapi_link = f"https://royaleapi.com/decks/stats/{','.join(api_names)}"

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
                    <a href="{royaleapi_link}" class="copy-btn" style="background: #38bdf8; color: #0f172a;" target="_blank">🔗 Auf RoyaleAPI öffnen & kopieren</a>
                </div>
            </div>
            """

    tiers = [
        "🌟 Elite (95-100%)",
        "✅ Solides Mittelfeld (80-94%)",
        f"⚠️ Unter Beobachtung ({APP_CONFIG['STRIKE_THRESHOLD']}-79%)",
        f"🚫 Kritisch (< {APP_CONFIG['STRIKE_THRESHOLD']}%)",
        "🏖️ Im Urlaub (Pausiert)"
    ]

    table_html = ""
    for t in tiers:
        players_in_tier = sorted(
            [p for p in player_stats if p["tier"] == t],
            key=lambda x: (x["score"], x["teilnahme_int"], x["fame"], x["donations"]),
            reverse=True
        )
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
                delta_s = f"+{p['delta']}" if p['delta'] > 0 else f"{p['delta']}"
                color = "#10b981" if p['delta'] > 0 else "#ef4444" if p['delta'] < 0 else "#94a3b8"

                neu_badge = ""
                if p["is_welpenschutz"] and not p["is_urlaub"]:
                    neu_badge = " <span class='custom-tooltip align-left' style='opacity:0.8;'>🌱<span class='tooltip-text'>Neu im Clan / Welpenschutz aktiv</span></span>"

                spenden_warnung = ""
                if p['donations'] == 0 and p['relevante_kriege'] > APP_CONFIG["MIN_PARTICIPATION"] and not p['is_urlaub']:
                    if p['donations_received'] > 0:
                        spenden_warnung = f" <span class='custom-tooltip' style='font-size: 1.1em;'>🧛<span class='tooltip-text'>Spenden-Leecher (0 gespendet, aber {p['donations_received']} erhalten)</span></span>"
                    else:
                        spenden_warnung = " <span class='custom-tooltip' style='font-size: 1.1em;'>💤<span class='tooltip-text'>Spenden-Inaktiv (0 gespendet, 0 erhalten)</span></span>"

                spenden_zelle = f"<span class='custom-tooltip dotted'>{p['donations']}<span class='tooltip-text'>Gespendet: {p['donations']} | Empfangen: {p['donations_received']}</span></span>"

                table_html += (
                    f"<tr>"
                    f"<td class='name-col'>{p['name']}{neu_badge}{p['streak_badge']}{p['strike_badge']}</td>"
                    f"<td>{p['status']}</td>"
                    f"<td><b>{p['score']}%</b></td>"
                    f"<td class='trend-cell'>{p['trend_str']}</td>"
                    f"<td style='color:{color}; font-weight:bold;'>{delta_s}%</td>"
                    f"<td style='color:#cbd5e1;'>{p['fame_per_deck']}{p['leecher_warnung']}</td>"
                    f"<td style='color:#38bdf8; font-weight:bold;'>{spenden_zelle}{spenden_warnung}</td>"
                    f"<td>{p['teilnahme']}</td>"
                    f"<td>{p['fame']}</td>"
                    f"</tr>"
                )

            table_html += "</tbody></table></div>"

    keys_to_delete = []
    for s_name in strikes.keys():
        if s_name not in aktive_namen_set:
            keys_to_delete.append(s_name)
    for k in keys_to_delete:
        del strikes[k]

    html = render_html_template(
        clan_name=CLAN_NAME,
        heute_datum=heute_datum,
        header_img_src=header_img_src,
        hype_balken_html=hype_balken_html,
        radar_html=radar_html,
        mahnwache_html=mahnwache_html,
        clan_avg=clan_avg,
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
        deck_html=deck_html
    )

    default_mail_texts = [list(block.values())[0] for block in chat_blocks]
    mail_chat_text = "\n\n".join([f"{i+1}/{total_msgs} {text}" for i, text in enumerate(default_mail_texts)])

    strikes_data["players"] = strikes
    return html, df_history, mail_chat_text, records, strikes_data, kicked_players 
