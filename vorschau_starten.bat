@echo off
echo Vorschau wird vorbereitet...

:: Kriegsdaten-Cache laden falls noch nicht vorhanden
if not exist warlog_cache.json (
    echo Kriegsdaten werden einmalig von Render geladen...
    python prefetch_warlog.py
)

:: index.html in preview/ kopieren
copy /Y index.html preview\index.html > nul

:: patch_preview.py ausfuehren
python patch_preview.py

:: Browser oeffnen
start http://localhost:8080

:: Lokalen Webserver starten
echo.
echo Vorschau laeuft unter http://localhost:8080
echo Zum Beenden dieses Fenster schliessen.
python -m http.server 8080 --directory preview
