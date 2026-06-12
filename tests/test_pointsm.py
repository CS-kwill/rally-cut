import numpy as np
from rally_cut.pointsm import find_dwells, points_from_dwells, gate_segments
from rally_cut.segments import Segment


def _series(total=60.0, fps=6.0, active=()):
    """저속(1.0) 바탕에 active 구간만 고속(20.0)인 합성 속도 시계열."""
    n = int(total * fps)
    t = np.arange(n) / fps
    s = np.full(n, 1.0)
    for a, b in active:
        s[(t >= a) & (t < b)] = 20.0
    return t, s


# --- find_dwells ---

def test_find_dwells_detects_long_low_run():
    t, s = _series(total=30.0, active=[(10.0, 20.0)])
    dwells = find_dwells(t, s, dwell_min=2.0)
    # 0~10s, 20~30s 저속 구간 두 개
    assert len(dwells) == 2
    assert dwells[0][0] <= 0.5 and abs(dwells[0][1] - 10.0) < 1.0
    assert abs(dwells[1][0] - 20.0) < 1.0


def test_find_dwells_ignores_short_pauses():
    # 1초짜리 멈칫(랠리 중 샷 사이)은 dwell이 아님
    t, s = _series(total=30.0, active=[(0.0, 14.0), (15.0, 30.0)])
    dwells = find_dwells(t, s, dwell_min=2.0)
    assert dwells == []


def test_find_dwells_empty_input():
    assert find_dwells(np.zeros(0), np.zeros(0)) == []


# --- points_from_dwells ---

def test_point_confirmed_by_onsets_after_dwell():
    # dwell 0~10s 종료 직후 온셋 군집(11,13,15s) → 포인트 [11-pad_pre, 15+pad_post]
    dwells = [(0.0, 10.0)]
    hits = [11.0, 13.0, 15.0]
    pts = points_from_dwells(dwells, hits, pad_pre=1.0, pad_post=2.0)
    assert len(pts) == 1
    assert abs(pts[0].start - 10.0) < 0.01
    assert abs(pts[0].end - 17.0) < 0.01


def test_bounce_during_dwell_not_a_point():
    # 온셋이 전부 dwell 도중(공 튀기기) → 포인트 없음
    dwells = [(0.0, 10.0)]
    hits = [2.0, 3.0, 4.0, 5.0]
    assert points_from_dwells(dwells, hits) == []


def test_onsets_without_dwell_not_a_point():
    # dwell 없이 온셋만(옆코트 소음 등) → 포인트 없음
    assert points_from_dwells([], [11.0, 13.0, 15.0]) == []


def test_rally_not_split_by_midpoint_pause():
    # 군집이 max_gap 이내로 이어지면 중간 멈칫과 무관하게 한 포인트
    dwells = [(0.0, 10.0)]
    hits = [11.0, 12.5, 14.0, 16.5, 18.0, 20.5]
    pts = points_from_dwells(dwells, hits, max_gap=3.0, pad_pre=1.0, pad_post=2.0)
    assert len(pts) == 1
    assert abs(pts[0].end - 22.5) < 0.01


def test_short_point_two_hits_confirmed():
    # 초단타 포인트: dwell 직후 온셋 2개로도 확정 (min_hits=2)
    dwells = [(0.0, 10.0)]
    hits = [11.0, 12.0]
    pts = points_from_dwells(dwells, hits, min_hits=2, min_duration=2.0)
    assert len(pts) == 1


def test_one_hit_not_enough():
    dwells = [(0.0, 10.0)]
    hits = [11.0]
    assert points_from_dwells(dwells, hits, min_hits=2) == []


def test_two_points_two_dwells():
    dwells = [(0.0, 10.0), (20.0, 25.0)]
    hits = [11.0, 12.0, 13.0, 26.0, 27.0, 28.0]
    pts = points_from_dwells(dwells, hits, pad_pre=1.0, pad_post=2.0)
    assert len(pts) == 2
    assert pts[0].start < pts[0].end <= dwells[1][0] + 1.0
    assert pts[1].start >= 25.0 - 1.0


def test_cluster_must_start_within_confirm_window():
    # dwell 종료 후 confirm_window(4s)를 한참 지나 시작한 군집은 미확정
    dwells = [(0.0, 10.0)]
    hits = [20.0, 21.0, 22.0]
    assert points_from_dwells(dwells, hits, confirm_window=4.0) == []


def test_video_start_counts_as_dwell_boundary():
    # 영상이 포인트 도중/직전에 시작해도 t=0 직후 온셋 군집은 포인트
    pts = points_from_dwells([], [1.0, 2.5, 4.0], start_boundary=0.0,
                             pad_pre=1.0, pad_post=2.0, min_duration=3.0)
    assert len(pts) == 1
    assert abs(pts[0].end - 6.0) < 0.01


def test_min_duration_filters_tiny_segments():
    dwells = [(0.0, 10.0)]
    hits = [11.0, 11.2]
    # pad 없이 0.2s 구간 → min_duration=3.0에 걸러짐
    assert points_from_dwells(dwells, hits, pad_pre=0.0, pad_post=0.0,
                              min_duration=3.0) == []


# --- gate_segments (오디오 후보 + dwell 검증 게이트) ---

def test_gate_keeps_segment_with_dwell_end_near_start():
    segs = [Segment(30.0, 36.0)]                 # 6s 후보(짧음)
    dwells = [(20.0, 28.0)]                      # 종료 28s — 시작 30s의 -8~+4 안
    out = gate_segments(segs, dwells, before=8.0, after=4.0, min_keep=10.0)
    assert out == segs


def test_gate_drops_short_segment_without_dwell():
    segs = [Segment(30.0, 36.0)]
    out = gate_segments(segs, [], before=8.0, after=4.0,
                        min_keep=10.0, start_grace=5.0)
    assert out == []


def test_gate_long_segment_kept_without_dwell():
    segs = [Segment(30.0, 45.0)]                 # 15s >= min_keep
    assert gate_segments(segs, [], min_keep=10.0) == segs


def test_gate_video_start_grace():
    segs = [Segment(2.0, 8.0)]                   # 영상 시작 직후
    assert gate_segments(segs, [], start_grace=5.0, min_keep=10.0) == segs


def test_gate_dwell_too_far_does_not_count():
    segs = [Segment(30.0, 36.0)]
    dwells = [(5.0, 15.0)]                       # 종료 15s — 30s에서 -8s 밖
    assert gate_segments(segs, dwells, before=8.0, after=4.0,
                         min_keep=10.0, start_grace=5.0) == []


def test_gate_keeps_short_segment_with_dense_onsets():
    # 짧고 dwell 없어도 온셋이 랠리 리듬(중앙간격 0.4 < 0.6)이면 keep
    segs = [Segment(30.0, 36.0)]
    hits = [31.0, 31.4, 31.8, 32.2, 32.6]
    out = gate_segments(segs, [], min_keep=10.0, start_grace=5.0,
                        hits=hits, dense_gap=0.6)
    assert out == segs


def test_gate_drops_short_sparse_segment():
    # 짧고 dwell 없고 온셋도 성김(중앙간격 1.5 >= 0.6) → drop
    segs = [Segment(30.0, 36.0)]
    hits = [31.0, 32.5, 34.0]
    out = gate_segments(segs, [], min_keep=10.0, start_grace=5.0,
                        hits=hits, dense_gap=0.6)
    assert out == []


def test_gate_hits_none_is_backward_compatible():
    # hits 미지정이면 기존 동작(짧고 dwell 없으면 drop) 그대로
    segs = [Segment(30.0, 36.0)]
    assert gate_segments(segs, [], min_keep=10.0, start_grace=5.0) == []


def test_gate_dense_onsets_outside_segment_do_not_count():
    # 밀집 온셋이 구간 밖에 있으면 keep 사유가 안 됨
    segs = [Segment(30.0, 36.0)]
    hits = [40.0, 40.4, 40.8]
    out = gate_segments(segs, [], min_keep=10.0, start_grace=5.0,
                        hits=hits, dense_gap=0.6)
    assert out == []


# --- onset_median_gap (온셋 밀도: 랠리 0.33s vs 튀기기 0.76s, AUC 0.89) ---

from rally_cut.pointsm import onset_median_gap


def test_onset_median_gap_basic():
    # 구간 내 온셋 [1,2,3]: 간격 [1,1] → 중앙값 1.0 (구간 밖 10.0은 무시)
    assert onset_median_gap(0.0, 5.0, [1.0, 2.0, 3.0, 10.0]) == 1.0


def test_onset_median_gap_dense_rally_rhythm():
    # 랠리 리듬(0.33s 간격) → 중앙간격 0.33
    hits = [10.0, 10.33, 10.66, 10.99]
    assert abs(onset_median_gap(9.0, 12.0, hits) - 0.33) < 1e-9


def test_onset_median_gap_fewer_than_two_is_inf():
    assert onset_median_gap(0.0, 5.0, [1.0]) == float("inf")
    assert onset_median_gap(0.0, 5.0, []) == float("inf")


def test_onset_median_gap_unsorted_hits():
    assert onset_median_gap(0.0, 5.0, [3.0, 1.0, 2.0]) == 1.0


# --- trim_tail (온셋밀도 꼬리 트리밍: 과보존 공략, v2 §3-2) ---

from rally_cut.pointsm import trim_tail


def test_trim_tail_pulls_end_after_last_dense_onset():
    # 밀집 온셋 [1.0,1.5,2.0] 후 성긴 온셋 10.0이 end를 20.0까지 끌었던 구간
    # → t_last=2.0, end = 2.0+3.0 = 5.0으로 당김
    segs = [Segment(0.0, 20.0)]
    hits = [1.0, 1.5, 2.0, 10.0]
    out = trim_tail(segs, hits, dense_gap=0.6, pad_tail=3.0)
    assert len(out) == 1
    assert out[0].start == 0.0
    assert abs(out[0].end - 5.0) < 1e-9


def test_trim_tail_no_dense_onsets_unchanged():
    # 성긴 온셋만(간격 4.0 > 0.6) — 성긴 진짜 포인트 보호: 불변
    segs = [Segment(0.0, 12.0)]
    hits = [1.0, 5.0, 9.0]
    assert trim_tail(segs, hits, dense_gap=0.6, pad_tail=3.0) == segs


def test_trim_tail_never_extends_end():
    # end(4.5) < t_last+pad(5.0) → 당기지도 늘리지도 않음
    segs = [Segment(0.0, 4.5)]
    hits = [1.0, 1.5, 2.0]
    out = trim_tail(segs, hits, dense_gap=0.6, pad_tail=3.0)
    assert out[0].end == 4.5


def test_trim_tail_empty_hits_unchanged():
    segs = [Segment(0.0, 10.0)]
    assert trim_tail(segs, [], dense_gap=0.6, pad_tail=3.0) == segs


def test_trim_tail_multiple_segments_independent():
    segs = [Segment(0.0, 20.0), Segment(30.0, 50.0)]
    hits = [1.0, 1.4, 1.8,            # seg1: t_last=1.8 → end 4.8
            31.0, 35.0, 39.0]         # seg2: 성김 → 불변
    out = trim_tail(segs, hits, dense_gap=0.6, pad_tail=3.0)
    assert abs(out[0].end - 4.8) < 1e-9
    assert out[1] == Segment(30.0, 50.0)


# --- veto_segments (v3 Q2: keep-OR 유지 + 물리 증거 부재 시 강등) ---

from rally_cut.pointsm import veto_segments


def _ev(rate, measured=True):
    return {"measured": measured, "rate": rate, "coverage": 0.0}


def test_veto_absent_ball_evidence_flags_segment():
    segs = [Segment(10.0, 30.0)]
    assert veto_segments(segs, [_ev(0.0)], rate_th=1.0) == [True]


def test_veto_present_ball_evidence_keeps():
    segs = [Segment(10.0, 30.0)]
    assert veto_segments(segs, [_ev(2.5)], rate_th=1.0) == [False]


def test_veto_missing_evidence_never_vetoes():
    # 결측(추론 실패/캐시 없음)은 veto 금지 — 현행 유지 (v3 Q2 폴백 안전성)
    segs = [Segment(10.0, 30.0)]
    assert veto_segments(segs, [_ev(0.0, measured=False)], rate_th=1.0) == [False]


def test_veto_with_hit_counts_requires_both_absent():
    # ②타구 이벤트가 있으면(>=min_hits) ③이 부재라도 veto 안 함
    segs = [Segment(0.0, 20.0), Segment(30.0, 50.0)]
    ev = [_ev(0.0), _ev(0.0)]
    flags = veto_segments(segs, ev, rate_th=1.0,
                          hit_counts=[3, 0], min_hits=2)
    assert flags == [False, True]


def test_veto_hit_counts_none_uses_ball_only():
    # 2C-1 합류 전: hit_counts=None이면 ③ 단독으로 판단
    segs = [Segment(0.0, 20.0)]
    assert veto_segments(segs, [_ev(0.0)], rate_th=1.0, hit_counts=None) == [True]


# --- trim_to_last_hit (v3 Q5: 증거 위계 — 검증 타구 우선, 결측 시 trim_tail 폴백) ---

from rally_cut.pointsm import trim_to_last_hit


def test_trim_to_last_hit_uses_verified_hit():
    segs = [Segment(0.0, 20.0)]
    out = trim_to_last_hit(segs, events=[3.0, 8.0], hits=[1.0, 1.4, 8.0, 15.0],
                           pad_hit=2.5, dense_gap=0.6, pad_tail=4.0)
    assert abs(out[0].end - 10.5) < 1e-9   # 8.0 + 2.5 — 검증 타구 우선


def test_trim_to_last_hit_falls_back_to_trim_tail():
    # 구간 내 검증 타구 없음 → 현행 trim_tail 경로(마지막 밀집온셋 1.4 + 4.0 = 5.4)
    segs = [Segment(0.0, 20.0)]
    out = trim_to_last_hit(segs, events=[], hits=[1.0, 1.4, 9.0],
                           pad_hit=2.5, dense_gap=0.6, pad_tail=4.0)
    assert abs(out[0].end - 5.4) < 1e-9


def test_trim_to_last_hit_never_extends():
    segs = [Segment(0.0, 4.0)]
    out = trim_to_last_hit(segs, events=[3.5], hits=[3.5],
                           pad_hit=2.5, dense_gap=0.6, pad_tail=4.0)
    assert out[0].end == 4.0


def test_trim_to_last_hit_start_unchanged():
    segs = [Segment(5.0, 20.0)]
    out = trim_to_last_hit(segs, events=[7.0], hits=[7.0],
                           pad_hit=2.0, dense_gap=0.6, pad_tail=4.0)
    assert out[0].start == 5.0 and abs(out[0].end - 9.0) < 1e-9


# --- prepend_faults (v5 §4: 확정 keep 직전 서브 폴트 1~2타격 군집 보존) ---

from rally_cut.pointsm import prepend_faults


def test_fault_far_before_start_becomes_separate_keep():
    # 폴트(20.0) → 10초 뒤 포인트 시작(30.0): 별도 keep [18.5, 22.0]
    segs = [Segment(30.0, 45.0)]
    hits = [20.0, 31.0, 32.0, 33.0]
    out = prepend_faults(segs, hits, window=25.0, pad_pre=1.5, pad_post=2.0,
                         merge_gap=3.0)
    assert len(out) == 2
    assert abs(out[0].start - 18.5) < 1e-9 and abs(out[0].end - 22.0) < 1e-9
    assert out[1] == Segment(30.0, 45.0)


def test_fault_near_start_extends_segment():
    # 폴트(27.0)+pad_post(2.0)=29.0, 시작 30.0과 간격 1.0 <= merge_gap → 연장
    segs = [Segment(30.0, 45.0)]
    hits = [27.0, 31.0, 32.0, 33.0]
    out = prepend_faults(segs, hits, window=25.0, pad_pre=1.5, pad_post=2.0,
                         merge_gap=3.0)
    assert len(out) == 1
    assert abs(out[0].start - 25.5) < 1e-9 and out[0].end == 45.0


def test_bounce_rhythm_cluster_ignored():
    # 3타격+ 연쇄(공 튀기기 리듬, 간격 ~1s)는 폴트가 아님 — 불변
    segs = [Segment(30.0, 45.0)]
    hits = [20.0, 21.0, 22.0, 23.0, 31.0, 32.0]
    out = prepend_faults(segs, hits, window=25.0, cluster_gap=2.0, max_cluster=2)
    assert out == segs


def test_double_fault_two_clusters_both_kept():
    # 폴트 두 번(12.0, 20.0 — 간격 8s > cluster_gap): 두 군집 모두 보존
    segs = [Segment(30.0, 45.0)]
    hits = [12.0, 20.0, 31.0, 32.0, 33.0]
    out = prepend_faults(segs, hits, window=25.0, pad_pre=1.5, pad_post=2.0,
                         merge_gap=3.0)
    assert len(out) == 3
    assert abs(out[0].start - 10.5) < 1e-9
    assert abs(out[1].start - 18.5) < 1e-9
    assert out[2] == Segment(30.0, 45.0)


def test_hits_inside_other_segments_not_candidates():
    # 직전 구간 내부 온셋은 폴트 후보가 아님
    segs = [Segment(0.0, 22.0), Segment(30.0, 45.0)]
    hits = [21.0, 31.0]
    out = prepend_faults(segs, hits, window=25.0)
    assert out == segs


def test_cooldown_after_previous_segment_end():
    # 직전 구간 종료(20.0) 후 cooldown(5.0) 이내 온셋(23.0)은 후보 제외
    # (꼬리 트리밍이 막 잘라낸 온셋을 도로 흡수하지 않기 위함)
    segs = [Segment(0.0, 20.0), Segment(40.0, 55.0)]
    hits = [23.0, 41.0, 42.0]
    out = prepend_faults(segs, hits, window=25.0, cooldown=5.0)
    assert out == segs


def test_fault_after_cooldown_is_kept():
    # 직전 구간 종료(20.0) + cooldown(5.0) 밖의 단일 온셋(28.0) → 별도 keep
    segs = [Segment(0.0, 20.0), Segment(40.0, 55.0)]
    hits = [28.0, 41.0, 42.0]
    out = prepend_faults(segs, hits, window=25.0, cooldown=5.0,
                         pad_pre=1.5, pad_post=2.0, merge_gap=3.0)
    assert len(out) == 3
    assert abs(out[1].start - 26.5) < 1e-9 and abs(out[1].end - 30.0) < 1e-9


def test_chained_merge_pulls_start_through_near_clusters():
    # 가장 가까운 군집 흡수로 start가 당겨지면, 그 앞 군집도 연쇄 판정
    # 27.0 흡수 → start 25.5, 23.0+2.0=25.0과 간격 0.5 <= merge_gap → 연쇄 흡수
    segs = [Segment(30.0, 45.0)]
    hits = [23.0, 27.0, 31.0, 32.0, 33.0]
    out = prepend_faults(segs, hits, window=25.0, pad_pre=1.5, pad_post=2.0,
                         merge_gap=3.0)
    assert len(out) == 1
    assert abs(out[0].start - 21.5) < 1e-9


def test_prepend_never_changes_end_or_drops_segments():
    segs = [Segment(10.0, 20.0), Segment(40.0, 55.0)]
    hits = [2.0, 32.0, 41.0]
    out = prepend_faults(segs, hits, window=25.0)
    assert sum(1 for s in out if s.end in (20.0, 55.0)) == 2
    assert sum(s.end - s.start for s in out) >= 25.0  # keep이 줄지 않음


def test_prepend_empty_inputs():
    assert prepend_faults([], [1.0, 2.0], window=25.0) == []
    segs = [Segment(10.0, 20.0)]
    assert prepend_faults(segs, [], window=25.0) == segs


def test_prepend_start_clamped_to_zero():
    # 영상 시작 직전 폴트: pad_pre가 0 밑으로 못 내려감
    segs = [Segment(5.0, 15.0)]
    hits = [1.0, 6.0, 7.0]
    out = prepend_faults(segs, hits, window=25.0, pad_pre=1.5, pad_post=2.0,
                         merge_gap=3.0)
    assert out[0].start == 0.0
