# CONTEXT

Begriffe aus der Clan-Domäne. Sie sind absichtlich deutsch und sollen es bleiben.
Wer hier einen Begriff findet, benutzt ihn: zwei Namen für dieselbe Sache sind der
Weg, auf dem die beiden Laufzeiten auseinanderdriften.

## Bewertung

Die Beurteilung eines Spielers allein aus seinen Kriegsdaten. Reine Rechnung,
keine Konsequenz. Lebt in [`app/bewertung.py`](app/bewertung.py).

## Score

Die eine Zahl aus der Bewertung, 0–100. Gewichtet aus drei Faktoren:

| Faktor | Gewicht | Bedeutung |
|--------|---------|-----------|
| Deck-Vollständigkeit | 50% | Anteil der möglichen Decks, die gespielt wurden |
| Dabei-Quote (Anwesenheit) | 30% | In wie vielen Kriegen des Fensters war der Spieler dabei |
| Qualität | 20% | Ø Punkte pro Deck, normiert zwischen `QUALITAET_FAME_MIN` und `QUALITAET_FAME_MAX` |

Grundlage für Verwarnungen, Kicks und Beförderungen. Gewichte und Grenzen stehen
in `config.py`, nicht im Code.

## Kriegsteilnahme

Der Eingabewert der Bewertung: die Kriege eines Spielers, neuester zuerst, plus
`kriege_im_fenster`. Letzteres muss mitgegeben werden — aus 0 Fame und 0 Decks
lässt sich nicht ableiten, ob jemand dabei war und nichts gespielt hat oder ob er
damals gar nicht im Clan war.

## Laufender Krieg

Der noch nicht abgeschlossene Krieg (`LAUFENDER_KRIEG_ID = "zzzcurrent"`, sortiert
über Ziffern und steht dadurch immer vorne). Er zählt **nicht** in
Deck-Vollständigkeit und Dabei-Quote — solange er läuft, wäre das unfair. Er zählt
aber **schon** in Ø Punkte pro Deck, damit die Kennzahl den aktuellen Stand zeigt.
Über die Qualität fließt er damit mit 20% in den Score ein.

Das ist gewachsenes Verhalten, kein Entwurf. Bisher entstand es allein daraus, dass
`"zzzcurrent"` beim Sortieren vorne landet. Ob es so bleiben soll, ist offen.

## Welpenschutz

Schonfrist im ersten Clankrieg (`kriege_mit_teilnahme <= MIN_PARTICIPATION`). Keine
Verwarnung, eigenes Badge (🌱 neu dabei).

## Urlaub

Manuell in `urlaub.txt` gemeldete Abwesenheit. Eine Entscheidung des Anführers über
Konsequenzen, keine Aussage über die Spielweise — deshalb gehört Urlaub zu den
Maßnahmen und nicht in die Bewertung.

## Maßnahmen

Was aus dem Score folgt: Verwarnung, Degradierung, Kick, Beförderung. Steckt
derzeit noch in `generate_html_report`.

## Strike / Verwarnung

Interner Hinweis bei Score unter `STRIKE_THRESHOLD`. Wird pro Kriegswoche einmal
vergeben und bei guter Woche wieder abgebaut. Ab 1/1 folgt die Maßnahme: Ältester
und Vize werden degradiert, Mitglieder gekickt.

## Beförderung

Aufstieg zum Ältesten. Setzt `PROMOTION_SCORE_MIN`, `PROMOTION_DONATIONS_MIN` und
null Strikes voraus.

## Mahnwache

Die Liste der Spieler mit heute noch offenen Decks im laufenden Krieg.

## Radar

Der Vergleich der fünf Clans im aktuellen River Race, inklusive Tagesdelta über
`war_radar_cache.json`.

## Rückkehrer

Ein Spieler, der schon einmal im Clan war (`ever_seen_players`). Stand er in
`kicked_players.json`, ist er ein **Warn-Rückkehrer**.

## Dropper

Spieler mit auffällig niedrigem Ertrag pro Deck (unter `DROPPER_THRESHOLD`) trotz
Teilnahme.
