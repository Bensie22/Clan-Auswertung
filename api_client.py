import requests
import sys

BASE_URL = "https://clan-gpt-api.onrender.com"


def get(endpoint: str) -> dict:
    try:
        response = requests.get(BASE_URL + endpoint, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ API-Fehler bei {endpoint}: {e}")
        sys.exit(1)
