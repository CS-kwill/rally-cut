import numpy as np
from rally_cut.segments import Segment
from rally_cut.refine import refine_segments


def _series(dur=30.0, fps=4.0):
    t = np.arange(0, dur, 1.0/fps)
    return t, np.ones_like(t)  # caller overwrites scores


def test_global_threshold_drops_dead_segment_with_own_noise():
    # 전역 임계 회귀 테스트: 구간 A는 진짜 랠리(높은 움직임), 구간 B는 죽은시간이지만
    # 자체적으로 약한 변동(노이즈)이 있다. 구간별 임계라면 B의 '상위 절반'이 활성으로
    # 잡혀 살아남지만, 전역 임계(A가 끌어올림)에서는 B 전체가 기준 미만 → drop 되어야 한다.
    t = np.arange(0, 60.0, 0.25)
    s = np.zeros_like(t)
    s[(t >= 5) & (t <= 25)] = 10.0                      # A: 실제 랠리
    rng = np.random.RandomState(0)
    deadmask = (t >= 35) & (t <= 55)
    s[deadmask] = 0.5 + 0.3 * rng.rand(deadmask.sum())  # B: 죽은시간 약한 노이즈
    out = refine_segments([Segment(0.0, 30.0), Segment(35.0, 55.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    # A만 남고 B는 통째로 drop
    assert len(out) == 1
    assert 4.5 <= out[0].start <= 5.5 and 24.5 <= out[0].end <= 25.5


def test_trim_leading_trailing_low_motion():
    t, s = _series(30.0)
    s[:] = 0.0
    s[(t >= 5) & (t <= 25)] = 10.0          # 활성은 5~25s만
    out = refine_segments([Segment(0.0, 30.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert len(out) == 1
    assert 4.5 <= out[0].start <= 5.5
    assert 24.5 <= out[0].end <= 25.5


def test_split_on_internal_valley():
    t, s = _series(30.0)
    s[:] = 0.0
    s[(t >= 1) & (t <= 8)] = 10.0
    s[(t >= 16) & (t <= 22)] = 10.0          # 8~16s = 8초 골짜기(>valley_min)
    out = refine_segments([Segment(0.0, 30.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert len(out) == 2
    assert out[0].end < out[1].start


def test_drop_segment_with_no_motion():
    t, s = _series(20.0)
    s[:] = 0.0                                # 전부 비활성
    out = refine_segments([Segment(0.0, 20.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert out == []


def test_short_active_cluster_dropped_by_min_duration():
    t, s = _series(20.0)
    s[:] = 0.0
    s[(t >= 10) & (t <= 11)] = 10.0          # 1초만 활성 < min_duration
    out = refine_segments([Segment(0.0, 20.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert out == []


def test_no_motion_samples_keeps_segment():
    # 구간 범위에 움직임 샘플이 없으면(시계열 비어있음) 원본 유지(폴백)
    out = refine_segments([Segment(5.0, 15.0)], np.array([]), np.array([]),
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert len(out) == 1
    assert out[0].start == 5.0 and out[0].end == 15.0


def test_short_valley_not_split():
    t, s = _series(30.0)
    s[:] = 0.0
    s[(t >= 2) & (t <= 10)] = 10.0
    s[(t >= 11) & (t <= 20)] = 10.0          # 10~11s = 1초 골짜기(<valley_min)
    out = refine_segments([Segment(0.0, 30.0)], t, s,
                          k=1.0, valley_min=2.0, min_duration=3.0)
    assert len(out) == 1                      # 분리 안 됨
