import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger(__name__)


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
    except (ValueError, TypeError):
        logger.debug("parse_float: konnte %r nicht konvertieren, nutze Standard %s", value, default)
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        logger.debug("parse_int: konnte %r nicht konvertieren, nutze Standard %s", value, default)
        return default


def parse_battle_date(raw: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Parst ein RoyaleAPI-Datumsformat und gibt (iso_string, tage_seit) zurück."""
    if not raw:
        return None, None
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - dt).days
        return dt.isoformat(), days_since
    except Exception:
        return None, None
