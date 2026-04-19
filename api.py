from fastapi import FastAPI
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
)

app = FastAPI(title="Clash Royale Clan Management API", version="3.0.0")


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


from app.routes.clan import router as clan_router
from app.routes.player import router as player_router
from app.routes.war import router as war_router
from app.routes.analytics import router as analytics_router
from app.routes.coaching import router as coaching_router

app.include_router(clan_router)
app.include_router(player_router)
app.include_router(war_router)
app.include_router(analytics_router)
app.include_router(coaching_router)
