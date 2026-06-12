# -*- coding: utf-8 -*-
"""ball_evidence: WASB 원시 검출(후보구간 캐시) -> 구간별 왕복 증거. 순수 함수 TDD.

설계 근거 (외부검토 v3 + 공추적_WASB제로샷_2237.md):
- 연결기/공궤적 필터 상수는 고전 CV(_ball_verify2)와 동일 — 측정으로 검증된 값.
- 측정 층은 연속값(가로지름/10s, 커버율), 게이트 층(veto)은 별도 모듈.
- 결측(measured=False)과 부재(rate=0)의 구분이 veto 안전성의 핵심.
"""
import numpy as np
import pytest
from rally_cut.ball_evidence import (
    in_court_mask, link_tracks, ball_tracks, count_crossings, segment_evidence,
    missing_evidence,
)

FPS = 29.97


# --- in_court_mask ---

SQUARE = [(100.0, 100.0), (900.0, 100.0), (900.0, 700.0), (100.0, 700.0)]


def test_mask_inside_outside():
    xys = np.array([[500.0, 400.0],    # 안
                    [50.0, 50.0],      # 밖(좌상)
                    [950.0, 400.0]])   # 밖(우)
    m = in_court_mask(xys, SQUARE)
    assert m.tolist() == [True, False, False]


def test_mask_none_polygon_passes_all():
    xys = np.array([[0.0, 0.0], [9999.0, 9999.0]])
    assert in_court_mask(xys, None).all()


def test_mask_empty_input():
    assert in_court_mask(np.zeros((0, 2)), SQUARE).shape == (0,)


# --- link_tracks (고전 CV 연결기: 속도예측, 120px/f, 결측 3f) ---

def _frames_with_single(points):
    """[(x,y) or None per frame] -> cands_per_frame"""
    return [[p] if p is not None else [] for p in points]


def test_link_straight_motion_single_track():
    pts = [(100.0 + 30.0 * i, 200.0) for i in range(10)]
    tracks = link_tracks(_frames_with_single(pts))
    assert len(tracks) == 1
    assert len(tracks[0]) == 10


def test_link_big_jump_splits():
    pts = [(100.0, 200.0), (110.0, 200.0), (800.0, 200.0)]  # 690px 점프 > 120
    tracks = link_tracks(_frames_with_single(pts))
    assert len(tracks) == 2


def test_link_gap_within_3_frames_continues():
    pts = [(100.0, 200.0), (130.0, 200.0), None, None, (220.0, 200.0)]
    tracks = link_tracks(_frames_with_single(pts))
    assert len(tracks) == 1
    assert len(tracks[0]) == 3


def test_link_gap_over_3_frames_splits():
    pts = [(100.0, 200.0), (130.0, 200.0), None, None, None, None, (250.0, 200.0)]
    tracks = link_tracks(_frames_with_single(pts))
    assert len(tracks) == 2


# --- ball_tracks (공궤적 필터: 0.3s+, 8px/f+, 200px+, 직선성 0.3+) ---

def _track(pts):
    return [(i, x, y) for i, (x, y) in enumerate(pts)]


def test_ball_tracks_fast_straight_passes():
    tr = _track([(100.0 + 25.0 * i, 300.0) for i in range(15)])  # 25px/f x 14f = 350px
    assert ball_tracks([tr], FPS) == [tr]


def test_ball_tracks_static_fails_speed():
    tr = _track([(500.0 + 0.5 * i, 300.0) for i in range(15)])
    assert ball_tracks([tr], FPS) == []


def test_ball_tracks_short_fails_length():
    tr = _track([(100.0 + 50.0 * i, 300.0) for i in range(4)])  # 4f < 0.3s*30
    assert ball_tracks([tr], FPS) == []


def test_ball_tracks_zigzag_fails_straightness():
    # 왕복 진동: 경로는 길지만 변위 ~0
    tr = _track([(100.0 + (50.0 if i % 2 else 0.0), 300.0) for i in range(15)])
    assert ball_tracks([tr], FPS) == []


# --- count_crossings (x extent >= 400px) ---

def test_crossings_counts_wide_track():
    wide = _track([(100.0 + 40.0 * i, 300.0) for i in range(15)])   # 560px
    narrow = _track([(100.0 + 15.0 * i, 300.0) for i in range(15)])  # 210px
    assert count_crossings([wide, narrow]) == 1


# --- segment_evidence ---

def test_segment_evidence_rate_and_coverage():
    # 20초 구간, 가로지름 2개 -> 1.0개/10s
    wide1 = _track([(100.0 + 40.0 * i, 300.0) for i in range(15)])
    wide2 = [(i + 300, x, y) for i, x, y in
             _track([(100.0 + 40.0 * i, 300.0) for i in range(15)])]
    ev = segment_evidence([wide1, wide2], dur_s=20.0, n_frames=600)
    assert ev["measured"] is True
    assert abs(ev["rate"] - 1.0) < 1e-9
    assert abs(ev["coverage"] - 30 / 600) < 1e-9


def test_segment_evidence_no_tracks_is_absence_not_missing():
    ev = segment_evidence([], dur_s=10.0, n_frames=300)
    assert ev["measured"] is True      # 측정됐는데 부재 — veto 가능 경로
    assert ev["rate"] == 0.0
    assert ev["coverage"] == 0.0


def test_missing_evidence_is_not_measured():
    ev = missing_evidence()
    assert ev["measured"] is False     # 결측 — veto 금지 경로 (v3 Q2)


# --- evidence_from_cache (캐시 폴더 -> 구간별 증거; 결측 처리 포함) ---

from rally_cut.ball_evidence import evidence_from_cache
from rally_cut.segments import Segment
import json


def _make_cache(tmp_path, seg_bounds, csv_rows_by_idx):
    meta = {"src": "x.MOV", "fps": FPS, "th": 0.3,
            "segments": [[i, s, e] for i, (s, e) in enumerate(seg_bounds)]}
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for i, rows in csv_rows_by_idx.items():
        lines = ["frame,x,y,score"] + [f"{f},{x},{y},{sc}" for f, x, y, sc in rows]
        (tmp_path / f"seg_{i}.csv").write_text("\n".join(lines), encoding="utf-8")


def test_evidence_from_cache_ball_flight(tmp_path):
    # seg0: 40px/f 직선 비행 15프레임 = 가로지름 1개, 10s 구간 -> rate 1.0
    flight = [(i, 100.0 + 40.0 * i, 300.0, 12.0) for i in range(15)]
    _make_cache(tmp_path, [(5.0, 15.0)], {0: flight})
    ev = evidence_from_cache(str(tmp_path), [Segment(5.0, 15.0)])
    assert ev[0]["measured"] is True
    assert abs(ev[0]["rate"] - 1.0) < 1e-9


def test_evidence_from_cache_missing_csv(tmp_path):
    _make_cache(tmp_path, [(5.0, 15.0)], {})   # meta는 있는데 CSV 없음
    ev = evidence_from_cache(str(tmp_path), [Segment(5.0, 15.0)])
    assert ev[0]["measured"] is False


def test_evidence_from_cache_unknown_segment_start(tmp_path):
    _make_cache(tmp_path, [(5.0, 15.0)], {})
    ev = evidence_from_cache(str(tmp_path), [Segment(99.0, 110.0)])
    assert ev[0]["measured"] is False


def test_evidence_from_cache_trimmed_end_still_matches(tmp_path):
    # 게이트/트리밍은 start를 안 바꾸므로 start로 후보를 매칭한다
    flight = [(i, 100.0 + 40.0 * i, 300.0, 12.0) for i in range(15)]
    _make_cache(tmp_path, [(5.0, 15.0)], {0: flight})
    ev = evidence_from_cache(str(tmp_path), [Segment(5.0, 9.0)])  # end 트리밍됨
    assert ev[0]["measured"] is True
    assert ev[0]["rate"] > 0
