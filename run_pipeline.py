"""
Pipeline-Orchestrierung: Führt alle Analyse-Skripte in der richtigen Reihenfolge aus.
Bei einem Fehler wird die Pipeline gestoppt und der Fehler gemeldet.
Verwendung: python run_pipeline.py
"""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

STEPS = [
    ("Prefetch",         "prefetch.py"),
    ("Full Auto",        "full_auto.py"),
    ("Smart Mode",       "smart_mode.py"),
    ("Coaching Mode",    "coaching_mode.py"),
    ("Commander Mode",   "commander_mode.py"),
    ("Merge Outputs",    "merge_outputs.py"),
]


def run_step(label: str, script: str) -> bool:
    print(f"[→] {label} ...", flush=True)
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / script)],
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        print(f"[✗] {label} FEHLGESCHLAGEN (Exit {result.returncode})")
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        return False
    print(f"[✓] {label}")
    if result.stdout.strip():
        print(f"    {result.stdout.strip()}")
    return True


def main():
    print("=== Pipeline gestartet ===")
    for label, script in STEPS:
        if not run_step(label, script):
            print(f"\n[!] Pipeline abgebrochen bei: {label}")
            sys.exit(1)
    print("\n=== Pipeline abgeschlossen: dashboard_data.json aktualisiert ===")


if __name__ == "__main__":
    main()
