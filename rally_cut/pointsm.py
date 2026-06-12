"""dwell 주도 포인트 상태 기계: dwell 종료 직후 타구음 군집 = 포인트. 순수 함수."""
from typing import List, Tuple
import numpy as np
from .refine import _active_threshold
from .segments import Segment


def find_dwells(times, speeds, k: float = 1.0, dwell_min: float = 2.0) -> List[Tuple[float, float]]:
    """비활성(백분위-갭 임계 미만)이 dwell_min초 이상 지속되는 구간들.

    dwell = 서브/리턴 준비 자세(같은 자리에 머묾). 랠리 중 샷 사이 멈칫(짧음)은 제외.
    임계는 refine과 동일한 백분위-갭 방식 — 활성/비활성 비율에 강건.
    """
    times = np.asarray(times, dtype=float)
    speeds = np.asarray(speeds, dtype=float)
    if times.size == 0:
        return []
    low = speeds < _active_threshold(speeds, k)
    out: List[Tuple[float, float]] = []
    i = 0
    n = len(low)
    while i < n:
        if low[i]:
            j = i
            while j < n and low[j]:
                j += 1
            s, e = float(times[i]), float(times[j - 1])
            if e - s >= dwell_min:
                out.append((s, e))
            i = j
        else:
            i += 1
    return out


def onset_median_gap(start: float, end: float, hits) -> float:
    """구간 [start, end] 내 온셋들의 중앙 간격(초). 온셋 2개 미만이면 inf.

    측정 근거(오디오_hitbounce_측정_2237.md): 랠리 중앙간격 0.33s vs
    공 튀기기 0.76s, AUC 0.89 — 본 프로젝트 최강 단일 특징.
    """
    h = sorted(t for t in hits if start <= t <= end)
    if len(h) < 2:
        return float("inf")
    return float(np.median(np.diff(h)))


def gate_segments(
    segments,
    dwells,
    before: float = 8.0,
    after: float = 4.0,
    start_grace: float = 5.0,
    min_keep: float = 10.0,
    hits=None,
    dense_gap: float = None,
) -> List[Segment]:
    """오디오 후보 구간을 dwell·온셋밀도 증거로 검증(keep/drop).

    keep 조건(OR):
    - 시작 근처에 dwell 종료가 있음([start-before, start+after]) — 서브 준비 후 시작된 포인트
    - 길이 >= min_keep — 긴 구간은 오디오만으로 신뢰
    - 시작 < start_grace — 녹화가 포인트 도중 시작된 경우 구제
    - (hits·dense_gap 지정 시) 구간 내 온셋 중앙간격 < dense_gap — 랠리 리듬(AUC 0.89)
    즉 drop = 짧음 AND dwell 없음 AND 온셋 성김 — drop 확신도만 올린다(Recall 우선).
    """
    ends = [e for _, e in dwells]
    use_density = hits is not None and dense_gap is not None
    out: List[Segment] = []
    for seg in segments:
        if (seg.start < start_grace
                or seg.end - seg.start >= min_keep
                or any(seg.start - before <= de <= seg.start + after for de in ends)
                or (use_density
                    and onset_median_gap(seg.start, seg.end, hits) < dense_gap)):
            out.append(seg)
    return out


def trim_tail(
    segments,
    hits,
    dense_gap: float = 0.6,
    pad_tail: float = 3.0,
) -> List[Segment]:
    """구간 끝을 마지막 밀집 온셋 + pad_tail로 당긴다 (과보존 꼬리 공략).

    밀집 온셋 = 직전 온셋과 간격 <= dense_gap. 포인트 종료 후 꼬리(공 줍기·걷기)에는
    밀집 타구음이 없다는 측정(AUC 0.89)에 근거. dwell 트리밍(2237 F1 80→53 붕괴로
    기각)과 달리 구간 중간을 못 자른다 — 최악 실패가 꼬리 pad 손실로 한정.
    밀집 온셋이 없는 구간(성긴 진짜 포인트)은 불변, end를 늘리는 일도 없다.
    """
    hits = sorted(float(h) for h in hits)
    out: List[Segment] = []
    for seg in segments:
        h = [t for t in hits if seg.start <= t <= seg.end]
        t_last = None
        for prev, cur in zip(h, h[1:]):
            if cur - prev <= dense_gap:
                t_last = cur
        new_end = seg.end if t_last is None else min(seg.end, t_last + pad_tail)
        out.append(Segment(seg.start, new_end))
    return out


def veto_segments(
    segments,
    ball_evidence,
    rate_th: float,
    hit_counts=None,
    min_hits: int = 2,
) -> List[bool]:
    """keep을 통과한 구간에 대한 물리 증거 veto(강등) 판정 (외부검토 v3 Q2).

    veto ⇐ ③왕복 부재(measured AND rate < rate_th)
           AND ②타구 부재(hit_counts 제공 시: count < min_hits)
    결측(measured=False)은 절대 veto하지 않는다 — 신호가 "측정됐는데 없다"일 때만
    강등(폴백 안전성). keep을 늘리는 경로가 없으므로 Recall 방향 위험이 구조적으로
    차단된다(keep-OR 보강 기각의 교훈). 반환: 구간별 veto 플래그.
    하드 제약: 2237 실포인트 16개에서 veto 0건이어야 임계 채택 가능.
    """
    flags: List[bool] = []
    for i, _seg in enumerate(segments):
        ev = ball_evidence[i]
        ball_absent = bool(ev.get("measured")) and ev.get("rate", 0.0) < rate_th
        if hit_counts is None:
            flags.append(ball_absent)
        else:
            flags.append(ball_absent and hit_counts[i] < min_hits)
    return flags


def trim_to_last_hit(
    segments,
    events,
    hits,
    pad_hit: float = 2.5,
    dense_gap: float = 0.6,
    pad_tail: float = 4.0,
) -> List[Segment]:
    """end 트리밍 증거 위계 (외부검토 v3 Q5).

    구간 내 마지막 "검증된 타구"(events: 온셋↔손목피크 정합)가 있으면
    end = t_last_hit + pad_hit (비행~바운스 물리 prior, 폴백보다 타이트).
    없으면(pose/공 결측 등) 현행 trim_tail(마지막 밀집온셋 + pad_tail) 폴백 —
    증거가 약한 경로일수록 넉넉하게. end를 늘리는 일은 없다. start 불변.
    """
    events = sorted(float(e) for e in events)
    out: List[Segment] = []
    for seg in segments:
        ev_in = [e for e in events if seg.start <= e <= seg.end]
        if ev_in:
            out.append(Segment(seg.start, min(seg.end, ev_in[-1] + pad_hit)))
        else:
            out.extend(trim_tail([seg], hits,
                                 dense_gap=dense_gap, pad_tail=pad_tail))
    return out


def prepend_faults(
    segments,
    hits,
    window: float = 25.0,
    cluster_gap: float = 2.0,
    max_cluster: int = 2,
    pad_pre: float = 1.5,
    pad_post: float = 2.0,
    merge_gap: float = 3.0,
    cooldown: float = 5.0,
) -> List[Segment]:
    """확정 keep 직전의 서브 폴트(1~2타격 군집)를 보존한다 (외부검토 v5 §4).

    폴트의 물리: 퍼스트서브 폴트 → 수 초~십수 초 후 세컨드서브 → 포인트(=확정
    keep). 즉 폴트는 항상 확정 keep의 직전 window초 이내에 위치한다 — 위치 제약이
    강해, min_hits를 전역으로 낮추는 것(Precision 붕괴 — 측정 역사)과 달리
    오검출 여지가 작다.

    - 후보 = 어떤 keep에도 속하지 않고, 직전 keep 종료 후 cooldown초 밖의 온셋
      (꼬리 트리밍이 막 잘라낸 온셋을 도로 흡수하지 않기 위함)
    - cluster_gap으로 군집화, 1~max_cluster 타격 군집만 폴트 후보
      (3타격+ 연쇄는 공 튀기기 리듬 — 중앙간격 0.76s 측정 — 이라 제외)
    - 군집 [first-pad_pre, last+pad_post]가 뒤 구간 시작과 merge_gap 이내면
      구간을 앞으로 연장해 흡수(연쇄 가능), 멀면 별도 keep
    - end 불변, keep을 줄이는 경로 없음 — Recall 방향 위험이 구조적으로 차단
    """
    segs = sorted(segments, key=lambda s: s.start)
    hits = sorted(float(h) for h in hits)
    out: List[Segment] = []
    used = set()
    for seg in segs:
        prev_end = out[-1].end if out else None
        cand = []
        for h in hits:
            if h in used or not (seg.start - window <= h < seg.start):
                continue
            if any(s.start <= h <= s.end for s in segs):
                continue
            if prev_end is not None and h <= prev_end + cooldown:
                continue
            cand.append(h)
        clusters: List[List[float]] = []
        for h in cand:
            if clusters and h - clusters[-1][-1] <= cluster_gap:
                clusters[-1].append(h)
            else:
                clusters.append([h])
        spans = [(max(0.0, c[0] - pad_pre), c[-1] + pad_post, c)
                 for c in clusters if len(c) <= max_cluster]
        new_start = seg.start
        extras = []
        for s0, e0, c in reversed(spans):  # 구간에 가까운 군집부터 연쇄 판정
            used.update(c)
            if new_start - e0 <= merge_gap:
                new_start = max(0.0, s0)
            else:
                extras.append((s0, e0))
        for s0, e0 in sorted(extras):
            if prev_end is not None:
                s0 = max(s0, prev_end)
            if out and s0 <= out[-1].end and out[-1] not in segs:
                out[-1] = Segment(out[-1].start, max(out[-1].end, e0))
            else:
                out.append(Segment(s0, e0))
        out.append(Segment(new_start, seg.end))
    return out


def points_from_dwells(
    dwells,
    hits,
    confirm_window: float = 4.0,
    max_gap: float = 3.0,
    min_hits: int = 2,
    pad_pre: float = 1.0,
    pad_post: float = 2.0,
    min_duration: float = 3.0,
    start_boundary: float = None,
) -> List[Segment]:
    """dwell 종료 직후 온셋 군집이 있으면 포인트로 확정.

    - 군집: dwell 종료 후 confirm_window 내에 시작, 온셋 간격 max_gap 이내 연쇄
    - dwell *도중* 온셋(서브 전 공 튀기기)은 군집 시작점이 될 수 없음
    - dwell 없는 온셋(옆코트 소음)은 포인트가 아님 — 오디오는 검증자 역할
    - start_boundary(보통 0.0): 영상 시작을 dwell 종료로 취급 — 녹화가 포인트
      도중/직전에 시작된 경우를 구제
    """
    hits = sorted(float(h) for h in hits)
    dwells = list(dwells)
    if start_boundary is not None:
        dwells = [(start_boundary, start_boundary)] + dwells
    out: List[Segment] = []
    used_until = -1e18
    for ds, de in dwells:
        # dwell 종료 후 confirm_window 내 첫 온셋 (이전 포인트에 쓰인 온셋 제외)
        cluster: List[float] = []
        for h in hits:
            if h <= max(de, used_until):
                continue
            if not cluster:
                if h - de > confirm_window:
                    break
                cluster.append(h)
            elif h - cluster[-1] <= max_gap:
                cluster.append(h)
            else:
                break
        if len(cluster) < min_hits:
            continue
        s = cluster[0] - pad_pre
        e = cluster[-1] + pad_post
        if e - s >= min_duration:
            out.append(Segment(s, e))
            used_until = cluster[-1]
    return out
