"""움직임 시계열로 오디오 Segment를 재군집(trim/split/drop)한다. 순수 함수."""
from typing import List
import numpy as np
from .segments import Segment


def _active_threshold(scores: np.ndarray, k: float) -> float:
    """영상 전체 움직임 분포에서 '활성' 임계값(전역). 비율에 강건한 백분위 갭 방식.

    하위사분위(p25, 죽은시간 기준선)와 p90(활성 수준) 사이를 k 비율로 나눈 지점.
    median+MAD는 이진/편향 분포에서 무너지므로 백분위로 대체.
    - 사실상 움직임 없음(p90~0) → 임계 1.0 (전부 비활성 → drop)
    - 분산 없음(균일 양수) → 임계를 살짝 낮춰 전부 활성
    """
    s = np.asarray(scores, dtype=float)
    lo = float(np.percentile(s, 25))
    hi = float(np.percentile(s, 90))
    if hi <= 1e-9:
        return 1.0                 # 움직임 거의 없음 → 활성 없음
    if hi - lo <= 1e-9:
        return lo - 1e-9           # 균일 양수 → 전부 활성
    return lo + k * 0.5 * (hi - lo)


def refine_segments(
    segments: List[Segment],
    mtimes,
    mscores,
    k: float = 1.0,
    valley_min: float = 2.0,
    min_duration: float = 3.0,
    pad: float = 0.0,
) -> List[Segment]:
    """각 오디오 구간 안에서 '활성' 프레임만 valley_min 간격으로 재군집.

    - trim: 군집 경계가 구간 앞뒤 비활성을 자동 제거
    - split: 활성 프레임 간 간격이 valley_min 초과면 다른 군집(=분리)
    - drop: 활성 프레임이 없거나 군집 길이가 min_duration 미만이면 버림
    움직임 샘플이 전혀 없으면(시계열 비어있음 또는 구간에 샘플 없음) 원본 구간 유지(폴백).

    threshold는 영상 전체 움직임 분포에서 전역으로 1회 계산 — 죽은시간이 풍부한
    전체 기준으로 봐야 순수 정지/튀기기 구간을 올바르게 drop할 수 있다.
    """
    mtimes = np.asarray(mtimes, dtype=float)
    mscores = np.asarray(mscores, dtype=float)
    if mtimes.size == 0:
        return list(segments)

    thr = _active_threshold(mscores, k)     # 전역 threshold(영상 전체 분포 기준)

    out: List[Segment] = []
    for seg in segments:
        mask = (mtimes >= seg.start) & (mtimes <= seg.end)
        idx = np.where(mask)[0]
        if idx.size == 0:
            out.append(seg)                 # 폴백: 움직임 정보 없음 → 유지
            continue
        act_times = mtimes[idx][mscores[idx] >= thr]
        if act_times.size == 0:
            continue                        # drop: 움직임 없음(순수 튀기기/정지)
        clusters = [[float(act_times[0])]]
        for t in act_times[1:]:
            if t - clusters[-1][-1] <= valley_min:
                clusters[-1].append(float(t))
            else:
                clusters.append([float(t)])
        for c in clusters:
            s = max(seg.start, c[0] - pad)
            e = min(seg.end, c[-1] + pad)
            if e - s >= min_duration:
                out.append(Segment(s, e))
    return out
