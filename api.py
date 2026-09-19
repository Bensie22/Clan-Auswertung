import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import (
    STRIKE_THRESHOLD, KICK_THRESHOLD, PROMOTION_SCORE_MIN,
    DROPPER_THRESHOLD, MIN_PARTICIPATION,
    BADGE_STARK_SCORE, BADGE_STARK_FAME,
    BADGE_STABIL_SCORE, BADGE_STABIL_FAME,
    TIER_SEHR_STARK, TIER_SOLIDE,
    CLAN_RELIABLE_GREEN, CLAN_RELIABLE_YELLOW,
    SMART_RISIKO_THRESHOLD, SMART_STARK_THRESHOLD,
    COACHING_MID_THRESHOLD,
    SCORE_GEWICHT_DECKS, SCORE_GEWICHT_ANWESENHEIT, SCORE_GEWICHT_QUALITAET,
    QUALITAET_FAME_MIN, QUALITAET_FAME_MAX,
)
from app.bewertung import DECKS_PRO_KRIEG, ROLLING_KRIEGE

app = FastAPI(title="Clash Royale Clan Management API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://clan-hamburg.de",
        "https://www.clan-hamburg.de",
        "http://localhost:3333",
        "http://127.0.0.1:3333",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_methods=["GET"],
    allow_headers=["X-Api-Key"],
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Clash Royale Clan Management API",
        version="3.0.0",
        description="JSON-first API für Clanführung, Warnungen, Beförderungen, Kriegsanalyse und Spielerübersichten.",
        routes=app.routes,
    )
    openapi_schema["servers"] = [{"url": "https://clan-gpt-api.onrender.com"}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

_API_KEY = os.environ.get("CLAN_API_KEY", "")


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not _API_KEY:
        return
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger oder fehlender API-Key.")


APP_CONFIG = {
    "STRIKE_THRESHOLD":        STRIKE_THRESHOLD,
    "KICK_THRESHOLD":          KICK_THRESHOLD,
    "PROMOTION_SCORE_MIN":     PROMOTION_SCORE_MIN,
    "DROPPER_THRESHOLD":       DROPPER_THRESHOLD,
    "MIN_PARTICIPATION":       MIN_PARTICIPATION,
    "BADGE_STARK_SCORE":       BADGE_STARK_SCORE,
    "BADGE_STARK_FAME":        BADGE_STARK_FAME,
    "BADGE_STABIL_SCORE":      BADGE_STABIL_SCORE,
    "BADGE_STABIL_FAME":       BADGE_STABIL_FAME,
    "TIER_SEHR_STARK":         TIER_SEHR_STARK,
    "TIER_SOLIDE":             TIER_SOLIDE,
    "CLAN_RELIABLE_GREEN":     CLAN_RELIABLE_GREEN,
    "CLAN_RELIABLE_YELLOW":    CLAN_RELIABLE_YELLOW,
    "SMART_RISIKO_THRESHOLD":  SMART_RISIKO_THRESHOLD,
    "SMART_STARK_THRESHOLD":   SMART_STARK_THRESHOLD,
    "COACHING_MID_THRESHOLD":  COACHING_MID_THRESHOLD,
    "SCORE_GEWICHT_DECKS":       SCORE_GEWICHT_DECKS,
    "SCORE_GEWICHT_ANWESENHEIT": SCORE_GEWICHT_ANWESENHEIT,
    "SCORE_GEWICHT_QUALITAET":   SCORE_GEWICHT_QUALITAET,
    "QUALITAET_FAME_MIN":        QUALITAET_FAME_MIN,
    "QUALITAET_FAME_MAX":        QUALITAET_FAME_MAX,
    "DECKS_PRO_KRIEG":           DECKS_PRO_KRIEG,
    "ROLLING_KRIEGE":            ROLLING_KRIEGE,
}


@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/datenschutz.html")
def datenschutz():
    return FileResponse("datenschutz.html")

@app.get("/impressum.html")
def impressum():
    return FileResponse("impressum.html")


@app.get("/config")
def get_config():
    """Alle aktuellen Schwellenwerte – verhindert Drift zwischen KI-Konfiguration und Backend."""
    return APP_CONFIG


from fastapi import Depends
from app.routes.clan import router as clan_router
from app.routes.player import router as player_router
from app.routes.war import router as war_router
from app.routes.analytics import router as analytics_router
from app.routes.coaching import router as coaching_router

_auth = Depends(require_api_key)
app.include_router(clan_router, dependencies=[_auth])
app.include_router(war_router, dependencies=[_auth])
app.include_router(analytics_router, dependencies=[_auth])
app.include_router(coaching_router, dependencies=[_auth])

# Warlog öffentlich – enthält nur Spielstatistiken (Fame/Decks), keine sensiblen Daten
from app.routes.player import player_warlog as _warlog_handler
app.add_api_route(
    "/player/{player_tag}/warlog",
    _warlog_handler,
    methods=["GET"],
    tags=["player"],
)

# Restliche Player-Endpoints mit Auth
app.include_router(player_router, dependencies=[_auth])
