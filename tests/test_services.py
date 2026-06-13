"""Unit-Tests für die Score- und Badge-Logik in services.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import compute_trend, compute_streak, get_focus_badge, build_promotion_status


def test_compute_trend_alle_gruen():
    scores = [80, 85, 90, 80, 75, 80]
    assert compute_trend(scores) == "🟢🟢🟢🟢🟢🟢"


def test_compute_trend_gemischt():
    scores = [90, 60, 40]
    result = compute_trend(scores)
    assert "🟢" in result
    assert "🟡" in result
    assert "🔴" in result


def test_compute_trend_max_6_eintraege():
    scores = [90, 90, 90, 90, 90, 90, 90, 90]
    assert len(compute_trend(scores)) == len("🟢") * 6


def test_compute_streak_kein_streak():
    assert compute_streak([80, 90, 95]) == 0


def test_compute_streak_aktiver_streak():
    assert compute_streak([80, 100, 100, 100]) == 3


def test_compute_streak_leer():
    assert compute_streak([]) == 0


def test_get_focus_badge_newcomer():
    result = get_focus_badge(score=95, fame_per_deck=200, participation_count=1)
    assert result["label"] == "NEWCOMER"


def test_get_focus_badge_stark():
    result = get_focus_badge(score=95, fame_per_deck=200, participation_count=5)
    assert result["label"] == "STARK"


def test_get_focus_badge_stabil():
    result = get_focus_badge(score=80, fame_per_deck=150, participation_count=5)
    assert result["label"] == "STABIL"


def test_get_focus_badge_dropper():
    result = get_focus_badge(score=60, fame_per_deck=100, participation_count=5)
    assert result["label"] == "DROPPER"


def test_build_promotion_status_eligible():
    player = {"score": 90, "donations": 60, "strikes": 0, "role": "member"}
    result = build_promotion_status(player)
    assert result["eligible"] is True


def test_build_promotion_status_zu_wenig_score():
    player = {"score": 70, "donations": 60, "strikes": 0, "role": "member"}
    result = build_promotion_status(player)
    assert result["eligible"] is False
    assert any("Score" in m for m in result["missing"])


def test_build_promotion_status_mit_strikes():
    player = {"score": 90, "donations": 60, "strikes": 1, "role": "member"}
    result = build_promotion_status(player)
    assert result["eligible"] is False
    assert any("Strike" in m for m in result["missing"])
