import os
import requests

BASE_URL = os.environ.get("API_BASE_URL", "https://clan-gpt-api.onrender.com")
_API_KEY = os.environ.get("CLAN_API_KEY", "")


def get(endpoint: str) -> dict:
    headers = {"X-Api-Key": _API_KEY} if _API_KEY else {}
    try:
        response = requests.get(BASE_URL + endpoint, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"API-Fehler bei {endpoint}: {e}") from e
