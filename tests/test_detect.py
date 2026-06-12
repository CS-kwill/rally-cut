import numpy as np
from rally_cut.detect import detect_hits


def test_detects_clicks_near_truth(make_signal, sr):
    truth = [1.0, 1.6, 2.3, 5.0, 5.5]
    x = make_signal(truth, with_wind=True)
    hits = detect_hits(x, sr)
    # 각 truth 근처(±0.12s)에 검출이 있어야 함
    for t in truth:
        assert any(abs(h - t) < 0.12 for h in hits), f"missed {t}: {hits}"


def test_wind_only_no_or_few_hits(make_signal, sr):
    x = make_signal([], with_wind=True)
    hits = detect_hits(x, sr)
    assert len(hits) <= 1  # 바람만 있으면 거의 검출 없음


def test_returns_sorted_floats(make_signal, sr):
    x = make_signal([3.0, 1.0, 2.0], with_wind=False)
    hits = detect_hits(x, sr)
    assert hits == sorted(hits)
    assert all(isinstance(h, float) for h in hits)
