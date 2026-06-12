# -*- coding: utf-8 -*-
"""공 왕복(net-crossing) 증거: WASB 원시 검출 -> 구간별 연속 특징. 순수 함수.

연결기·공궤적 필터 상수는 고전 CV(공추적_검증_2237.md)와 동일 — WASB 제로샷 평가에서
대조군 가로지름 26->1개로 변별이 검증된 조합(공추적_WASB제로샷_2237.md).
측정 층(이 모듈)은 연속값(가로지름/10s, 커버율)만 산출하고, 게이트 판단(veto)은
pointsm 쪽에서 한다 (외부검토 v3 Q1: 측정=연속, 게이트=보수적 이진).

결측/부재 구분 (v3 Q2의 핵심): 추론 캐시가 없거나 sanity check 미달이면
missing_evidence()(measured=False) — veto 금지. 측정됐는데 신호가 없을 때만
measured=True & rate=0 — veto 가능.
"""
from typing import List, Optional, Sequence, Tuple
import numpy as np

Track = List[Tuple[int, float, float]]  # (frame, x, y)

MAX_JUMP_PX = 120.0   # 연결 최대 점프(px/프레임)
MAX_GAP_FRAMES = 3    # 연결 허용 결측
MIN_LEN_S = 0.3       # 공궤적 최소 길이
MIN_SPEED = 8.0       # 평균속도(px/프레임)
MIN_PATH = 200.0      # 총 이동(px)
MIN_STRAIGHT = 0.3    # 변위/경로 (직선성)
CROSS_SPAN_PX = 400.0  # 가로지름 = 수평 extent

# 2237 코트+여유 다각형(1080p) — 고정 카메라 1회 수동 지정 (v3 Q1-3).
# 상단 배경(펜스/나무) 오검출 차단용. Phase 3-3에서 TennisCourtDetector로 대체 예정.
COURT_POLY_2237: Optional[List[Tuple[float, float]]] = None  # 측정 후 확정


def in_court_mask(xys, polygon) -> np.ndarray:
    """점들(N,2)이 다각형 내부인지. polygon=None이면 전부 True(마스크 없음)."""
    xys = np.asarray(xys, dtype=float).reshape(-1, 2)
    if polygon is None:
        return np.ones(xys.shape[0], dtype=bool)
    if xys.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    from matplotlib.path import Path
    return Path(np.asarray(polygon, dtype=float)).contains_points(xys)


def link_tracks(cands_per_frame: Sequence[Sequence[Tuple[float, float]]],
                max_jump: float = MAX_JUMP_PX,
                max_gap: int = MAX_GAP_FRAMES) -> List[Track]:
    """후보들을 속도 예측 최근접 연결로 트랙으로 묶는다 (고전 CV 연결기와 동일)."""
    tracks: List[Track] = []
    active: List[Track] = []
    for i, cands in enumerate(cands_per_frame):
        used = set()
        nxt: List[Track] = []
        for tr in active:
            li, lx, ly = tr[-1]
            vx = vy = 0.0
            if len(tr) >= 2:
                pi, px, py = tr[-2]
                vx = (lx - px) / max(1, li - pi)
                vy = (ly - py) / max(1, li - pi)
            pred = (lx + vx * (i - li), ly + vy * (i - li))
            best = None
            bd = max_jump * (i - li)
            for j, (cx, cy) in enumerate(cands):
                if j in used:
                    continue
                dd = float(np.hypot(cx - pred[0], cy - pred[1]))
                if dd < bd:
                    bd = dd
                    best = j
            if best is not None:
                used.add(best)
                tr.append((i, cands[best][0], cands[best][1]))
                nxt.append(tr)
            elif i - tr[-1][0] <= max_gap:
                nxt.append(tr)
            else:
                tracks.append(tr)
        for j, (cx, cy) in enumerate(cands):
            if j not in used:
                nxt.append([(i, cx, cy)])
        active = nxt
    tracks.extend(active)
    return tracks


def ball_tracks(tracks: Sequence[Track], fps: float,
                min_len_s: float = MIN_LEN_S, min_speed: float = MIN_SPEED,
                min_path: float = MIN_PATH,
                min_straight: float = MIN_STRAIGHT) -> List[Track]:
    """공다운 궤적만: 길이·평균속도·총이동·직선성 (고전 CV 필터와 동일)."""
    out: List[Track] = []
    min_len = int(min_len_s * fps)
    for tr in tracks:
        if len(tr) < min_len:
            continue
        xs = np.array([p[1] for p in tr])
        ys = np.array([p[2] for p in tr])
        fs = np.array([p[0] for p in tr])
        disp = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
        path = float(np.hypot(np.diff(xs), np.diff(ys)).sum())
        span = max(1, int(fs[-1] - fs[0]))
        if path / span < min_speed:
            continue
        if path < min_path:
            continue
        if disp / max(path, 1e-9) < min_straight:
            continue
        out.append(tr)
    return out


def count_crossings(tracks: Sequence[Track],
                    span_px: float = CROSS_SPAN_PX) -> int:
    """코트 가로지름 궤적 수 (수평 extent >= span_px)."""
    return sum(1 for tr in tracks
               if max(p[1] for p in tr) - min(p[1] for p in tr) >= span_px)


def segment_evidence(tracks: Sequence[Track], dur_s: float, n_frames: int,
                     span_px: float = CROSS_SPAN_PX) -> dict:
    """구간별 왕복 증거 (측정 층, 연속값).

    rate: 가로지름 수를 구간 길이로 정규화(개/10s) — 절대 개수는 긴 구간에 유리(v3 Q1).
    coverage: 공궤적이 덮는 프레임 비율.
    measured=True: 추론이 수행된 구간 — rate=0이면 "부재"(veto 가능).
    """
    covered = set()
    for tr in tracks:
        covered.update(p[0] for p in tr)
    return {
        "measured": True,
        "rate": count_crossings(tracks, span_px) * 10.0 / max(dur_s, 1e-9),
        "coverage": len(covered) / max(1, n_frames),
    }


def missing_evidence() -> dict:
    """결측 — 캐시 없음/추론 실패/sanity 미달. veto 금지 경로 (v3 Q2)."""
    return {"measured": False, "rate": 0.0, "coverage": 0.0}


def evidence_from_cache(cache_dir: str, segments, polygon=None) -> List[dict]:
    """원시 검출 캐시(_ball_cache.py 산출)에서 구간별 증거를 만든다.

    매칭은 start 시각으로 한다 — 게이트/트리밍은 start를 바꾸지 않으므로
    트리밍된 구간도 원 후보의 캐시를 찾는다. rate 정규화는 원 후보의 전체 길이
    기준(증거는 구간 정체성에 대한 것). 캐시/CSV 없으면 missing_evidence().
    """
    import csv
    import json
    import os
    meta_path = os.path.join(cache_dir, "meta.json")
    if not os.path.exists(meta_path):
        return [missing_evidence() for _ in segments]
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    fps = float(meta["fps"])
    by_start = {round(float(s), 2): (int(i), float(s), float(e))
                for i, s, e in meta["segments"]}
    out: List[dict] = []
    for seg in segments:
        m = by_start.get(round(float(seg.start), 2))
        if m is None:
            out.append(missing_evidence())
            continue
        idx, cs, ce = m
        csv_path = os.path.join(cache_dir, f"seg_{idx}.csv")
        if not os.path.exists(csv_path):
            out.append(missing_evidence())
            continue
        n_frames = max(1, int((ce - cs) * fps))
        cands: List[List[Tuple[float, float]]] = [[] for _ in range(n_frames)]
        with open(csv_path, encoding="utf-8") as f:
            rows = [(int(r["frame"]), float(r["x"]), float(r["y"]))
                    for r in csv.DictReader(f)]
        if rows and polygon is not None:
            keep = in_court_mask(np.array([[x, y] for _, x, y in rows]), polygon)
            rows = [r for r, k in zip(rows, keep) if k]
        for fi, x, y in rows:
            if 0 <= fi < n_frames:
                cands[fi].append((x, y))
        tracks = ball_tracks(link_tracks(cands), fps)
        out.append(segment_evidence(tracks, ce - cs, n_frames))
    return out
