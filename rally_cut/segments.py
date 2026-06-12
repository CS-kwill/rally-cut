"""타격 시점(초) -> 랠리 구간. 가까운 타격을 묶고 패딩/필터링한다."""
from dataclasses import dataclass
from typing import List


@dataclass
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_segments(
    hits: List[float],
    max_gap: float,
    min_hits: int,
    pad_pre: float,
    pad_post: float,
    min_duration: float,
) -> List[Segment]:
    """인접 타격(간격 <= max_gap)을 한 랠리로 묶는다.

    - min_hits 미만 타격으로 이뤄진 묶음은 버린다(노이즈).
    - 묶음 앞에 pad_pre, 뒤에 pad_post 초의 여유를 둔다(start는 0으로 클램프).
    - 최종 길이가 min_duration 미만이면 버린다.
    """
    if not hits:
        return []
    hits = sorted(hits)

    clusters: List[List[float]] = [[hits[0]]]
    for t in hits[1:]:
        if t - clusters[-1][-1] <= max_gap:
            clusters[-1].append(t)
        else:
            clusters.append([t])

    segments: List[Segment] = []
    for c in clusters:
        if len(c) < min_hits:
            continue
        start = max(0.0, c[0] - pad_pre)
        end = c[-1] + pad_post
        seg = Segment(start=start, end=end)
        if seg.duration >= min_duration:
            segments.append(seg)
    return segments
