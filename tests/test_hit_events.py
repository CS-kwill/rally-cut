# -*- coding: utf-8 -*-
"""hit_events: 손목속도 피크 ↔ 타구음 온셋 정합 -> 검증된 타구 이벤트. 순수 함수 TDD.

설계 근거 (외부검토 v3 Q3):
- 정합 창은 고정 상수가 아니라 Δt 히스토그램의 5~95퍼센타일로 결정(비대칭 허용)
  — match_hits는 (win_lo, win_hi)를 인자로 받는다.
- ③(공)은 구간 증거 전용, 타구 "시점"은 ①온셋+②손목피크의 몫.
- 결측 구분: pose 실패 구간은 missing — veto 금지 경로.
"""
import numpy as np
from rally_cut.hit_events import (
    wrist_peaks, match_hits, hits_per_segment, delta_t,
)
from rally_cut.segments import Segment


# --- wrist_peaks: 평활 속도 시계열에서 국소 최대(이웃보다 크고 임계 이상) ---

def test_wrist_peaks_finds_local_maxima():
    t = np.arange(20) / 10.0
    v = np.zeros(20)
    v[5] = 1.0   # 피크 1
    v[12] = 0.8  # 피크 2
    pk = wrist_peaks(t, v, min_height=0.5)
    assert [round(x, 1) for x in pk] == [0.5, 1.2]


def test_wrist_peaks_threshold_filters_small():
    t = np.arange(10) / 10.0
    v = np.zeros(10)
    v[4] = 0.3
    assert wrist_peaks(t, v, min_height=0.5) == []


def test_wrist_peaks_nan_safe():
    t = np.arange(10) / 10.0
    v = np.full(10, np.nan)
    v[4] = 1.0
    pk = wrist_peaks(t, v, min_height=0.5)
    assert pk == [0.4]


def test_wrist_peaks_empty():
    assert wrist_peaks(np.zeros(0), np.zeros(0)) == []


# --- delta_t: 각 피크와 가장 가까운 온셋의 차이 (피크 - 온셋) ---

def test_delta_t_nearest_onset():
    dts = delta_t(peaks=[1.0, 5.0], onsets=[1.1, 4.0, 5.2])
    assert np.allclose(dts, [-0.1, -0.2])


def test_delta_t_no_onsets():
    assert delta_t([1.0], []) == []


# --- match_hits: 비대칭 창 [win_lo, win_hi] 안에 피크가 있는 온셋 = 검증된 타구 ---

def test_match_hits_asymmetric_window():
    onsets = [10.0, 20.0, 30.0]
    peaks = [9.8, 20.15, 31.0]   # 창 [-0.3, +0.1]: 10.0(피크-0.2 ok), 20.0(+0.15 밖), 30.0(+1.0 밖)
    hits = match_hits(peaks, onsets, win_lo=-0.3, win_hi=0.1)
    assert hits == [10.0]


def test_match_hits_one_peak_validates_one_onset():
    # 피크 1개가 온셋 2개를 동시에 검증하지 않는다 (가장 가까운 것 하나만)
    onsets = [10.0, 10.3]
    peaks = [10.1]
    hits = match_hits(peaks, onsets, win_lo=-0.3, win_hi=0.3)
    assert hits == [10.0]


def test_match_hits_empty_inputs():
    assert match_hits([], [1.0], -0.2, 0.2) == []
    assert match_hits([1.0], [], -0.2, 0.2) == []


# --- hits_per_segment ---

def test_hits_per_segment_counts_inside():
    segs = [Segment(0.0, 15.0), Segment(20.0, 30.0)]
    events = [1.0, 5.0, 14.0, 25.0]
    counts = hits_per_segment(segs, events)
    assert counts == [3, 1]


def test_hits_per_segment_empty_events():
    assert hits_per_segment([Segment(0.0, 10.0)], []) == [0]


# --- counts_from_pose_cache (pose 캐시 -> 구간별 검증타구 수 + 결측 플래그) ---

import json
from rally_cut.hit_events import counts_from_pose_cache


def _make_pose_cache(tmp_path, seg_bounds, series_by_idx):
    meta = {"src": "x.mp4", "pose_fps": 12.0,
            "segments": [[i, s, e] for i, (s, e) in enumerate(seg_bounds)]}
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for i, (t, sp) in series_by_idx.items():
        np.savez(tmp_path / f"seg_{i}.npz", t=np.asarray(t), speed=np.asarray(sp))


def test_counts_from_pose_cache_matches_hits(tmp_path):
    # 구간 0~10s: t=2.0과 t=6.0에 손목피크, 온셋 [2.1, 6.05, 9.0]
    t = np.arange(0, 10, 1.0 / 12)
    sp = np.zeros_like(t)
    sp[24] = 1.0   # t=2.0
    sp[72] = 1.0   # t=6.0
    _make_pose_cache(tmp_path, [(0.0, 10.0)], {0: (t, sp)})
    counts, measured = counts_from_pose_cache(
        str(tmp_path), [Segment(0.0, 10.0)], onsets=[2.1, 6.05, 9.0],
        win_lo=-0.3, win_hi=0.3)
    assert measured == [True]
    assert counts == [2]      # 9.0은 피크 없음 -> 미검증


def test_counts_from_pose_cache_missing_npz(tmp_path):
    _make_pose_cache(tmp_path, [(0.0, 10.0)], {})
    counts, measured = counts_from_pose_cache(
        str(tmp_path), [Segment(0.0, 10.0)], onsets=[1.0],
        win_lo=-0.3, win_hi=0.3)
    assert measured == [False]   # 결측 — veto 금지 경로
    assert counts == [0]


def test_counts_from_pose_cache_unknown_start(tmp_path):
    _make_pose_cache(tmp_path, [(0.0, 10.0)], {})
    counts, measured = counts_from_pose_cache(
        str(tmp_path), [Segment(50.0, 60.0)], onsets=[],
        win_lo=-0.3, win_hi=0.3)
    assert measured == [False]
