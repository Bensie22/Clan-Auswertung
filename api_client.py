import os
import requests

BASE_URL = os.environ.get("API_BASE_URL", "https://clan-gpt-api.onrender.com")


def get(endpoint: str) -> dict:
    try:
        response = requests.get(BASE_URL + endpoint, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"API-Fehler bei {endpoint}: {e}") from e
