# -*- coding: utf-8 -*-
"""검증된 타구 이벤트: 손목속도 피크(②) ↔ 타구음 온셋(①) 시간 정합. 순수 함수.

Phase 2B 측정 근거: 12fps 손목속도로 서브(0.38) > 랠리(0.155) > 정지(0.138) 분리,
팔 키포인트 신뢰 0.69~0.86 — 야간에도 시점 검출 가능 (Phase2B_YOLO_검증결과.md).
정합 창은 Δt 히스토그램(피크-온셋)의 5~95퍼센타일로 데이터가 결정 — 비대칭 허용
(외부검토 v3 Q3). 12fps에서 피크 "크기"는 과소추정될 수 있어 시점만 사용한다.
pose 추론 자체는 호출 측(스크립트/CLI) 책임 — 이 모듈은 시계열만 다룬다.
"""
from typing import List, Sequence
import numpy as np


def wrist_peaks(times, speeds, min_height: float = 0.0) -> List[float]:
    """평활 손목속도 시계열의 국소 최대 시각들. NaN은 0으로 간주."""
    times = np.asarray(times, dtype=float)
    v = np.nan_to_num(np.asarray(speeds, dtype=float), nan=0.0)
    if v.size < 1:
        return []
    out: List[float] = []
    for i in range(v.size):
        left = v[i - 1] if i > 0 else -np.inf
        right = v[i + 1] if i < v.size - 1 else -np.inf
        if v[i] >= min_height and v[i] > left and v[i] >= right:
            out.append(float(times[i]))
    return out


def delta_t(peaks: Sequence[float], onsets: Sequence[float]) -> List[float]:
    """각 피크에 대해 (피크 시각 - 가장 가까운 온셋 시각). 창 결정용 분포 재료."""
    onsets = sorted(float(o) for o in onsets)
    if not onsets:
        return []
    out = []
    for p in peaks:
        nearest = min(onsets, key=lambda o: abs(p - o))
        out.append(float(p) - nearest)
    return out


def match_hits(peaks: Sequence[float], onsets: Sequence[float],
               win_lo: float, win_hi: float) -> List[float]:
    """창 [win_lo, win_hi] 안에 손목피크가 있는 온셋들 = 검증된 타구 시각.

    피크 1개는 가장 가까운 온셋 1개만 검증한다(중복 검증 방지).
    창 부호: dt = 피크 - 온셋 (피크가 온셋보다 빠르면 음수).
    """
    onsets = sorted(float(o) for o in onsets)
    peaks = sorted(float(p) for p in peaks)
    if not onsets or not peaks:
        return []
    used_onsets = set()
    for p in peaks:
        best = None
        bd = float("inf")
        for k, o in enumerate(onsets):
            if k in used_onsets:
                continue
            dt = p - o
            if win_lo <= dt <= win_hi and abs(dt) < bd:
                bd = abs(dt)
                best = k
        if best is not None:
            used_onsets.add(best)
    return [onsets[k] for k in sorted(used_onsets)]


def hits_per_segment(segments, events: Sequence[float]) -> List[int]:
    """구간별 검증된 타구 수 (veto의 ② 증거)."""
    events = sorted(float(e) for e in events)
    return [sum(1 for e in events if seg.start <= e <= seg.end)
            for seg in segments]


def counts_from_pose_cache(cache_dir: str, segments, onsets,
                           win_lo: float, win_hi: float,
                           peak_pctl: float = 85.0):
    """pose 캐시(_pose_cache.py 산출)에서 구간별 검증타구 수를 만든다.

    반환 (counts, measured) — measured=False(npz 없음/매칭 실패)는 veto 금지 경로.
    피크 임계는 캐시 전체 속도 분포의 percentile (절대 상수 금지, v3 Q3 정신).
    매칭은 start 시각(게이트/트리밍이 start를 안 바꿈)."""
    import json
    import os
    meta_path = os.path.join(cache_dir, "meta.json")
    if not os.path.exists(meta_path):
        return [0] * len(segments), [False] * len(segments)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    by_start = {round(float(s), 2): int(i) for i, s, e in meta["segments"]}
    series = {}
    all_speeds: List[float] = []
    for i, _s, _e in meta["segments"]:
        p = os.path.join(cache_dir, f"seg_{int(i)}.npz")
        if os.path.exists(p):
            z = np.load(p)
            series[int(i)] = (z["t"], z["speed"])
            all_speeds.extend(np.asarray(z["speed"]).tolist())
    th = float(np.percentile(all_speeds, peak_pctl)) if all_speeds else 0.0
    onsets = sorted(float(o) for o in onsets)
    counts: List[int] = []
    measured: List[bool] = []
    for seg in segments:
        idx = by_start.get(round(float(seg.start), 2))
        if idx is None or idx not in series:
            counts.append(0)
            measured.append(False)
            continue
        t, sp = series[idx]
        peaks = wrist_peaks(t, sp, min_height=th)
        seg_on = [o for o in onsets if seg.start <= o <= seg.end]
        counts.append(len(match_hits(peaks, seg_on, win_lo, win_hi)))
        measured.append(True)
    return counts, measured
