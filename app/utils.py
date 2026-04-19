import re
from typing import Any

from fastapi import HTTPException


def normalize_tag(tag: str) -> str:
    tag = str(tag or "").strip().upper().replace("%23", "#")
    if not tag:
        return ""
    if not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


_TAG_PATTERN = re.compile(r"^#[0-9A-Z]{3,12}$")


def validate_tag(player_tag: str) -> str:
    tag = normalize_tag(player_tag)
    if not _TAG_PATTERN.match(tag):
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger Spieler-Tag: '{tag}'. Erwartet: #XXXXXXXX (nur Großbuchstaben und Ziffern)",
        )
    return tag


def normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "")


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def compute_trend(scores: list, tier_solide: float, strike_threshold: float) -> str:
    return "".join([
        "🟢" if s >= tier_solide else
        "🟡" if s >= strike_threshold else
        "🔴"
        for s in scores[-6:]
    ])


def compute_streak(scores: list) -> int:
    streak = 0
    for s in reversed(scores):
        if s >= 100.0:
            streak += 1
        else:
            break
    return streak
