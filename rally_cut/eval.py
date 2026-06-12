"""정답(포인트로그) 대비 컷리스트 채점 + 타임라인 IoU. 순수 함수.

정답 JSON 포맷(고정):
{
  "total": 522.0,                        # 영상 길이(초)
  "groups": [[[s,e]], [[s,e],[s,e]]],    # 포인트 그룹(그룹 중 하나라도 50%+ 커버=회수)
  "nonpoints": [[s,e], ...]              # 명시적 비포인트(공 튀기기 등)
}
"""
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

Span = Tuple[float, float]


@dataclass
class GroundTruth:
    total: float
    groups: List[List[Span]]
    nonpoints: List[Span]


def load_groundtruth(path: str) -> GroundTruth:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return GroundTruth(
        total=float(raw["total"]),
        groups=[[(float(s), float(e)) for s, e in g] for g in raw["groups"]],
        nonpoints=[(float(s), float(e)) for s, e in raw.get("nonpoints", [])],
    )


def _ovl(a: Span, b: Span) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def evaluate_cuts(kept: List[Span], gt: GroundTruth) -> Dict[str, float]:
    """kept 구간들을 정답 대비 채점.

    - recall: 그룹 내 어느 한 포인트가 50%+ 커버되면 그 그룹 회수
    - precision: kept 중 포인트와 40%+ 겹치는 비율
    - nonpoint_fp: kept 중 비포인트와 40%+ 겹치는 개수
    - removed: 제거된 시간 비율
    """
    rec = sum(
        1 for g in gt.groups
        if any(e > s and max((_ovl((s, e), k) for k in kept), default=0) / (e - s) >= 0.5
               for s, e in g)
    )
    tp = np_fp = 0
    for k in kept:
        op = max((_ovl(k, p) for g in gt.groups for p in g), default=0)
        npo = max((_ovl(k, nn) for nn in gt.nonpoints), default=0)
        rd = k[1] - k[0]
        if rd <= 0:
            continue
        if op >= 0.4 * rd:
            tp += 1
        elif npo >= 0.4 * rd:
            np_fp += 1
    kept_dur = sum(e - s for s, e in kept)
    recall = rec / len(gt.groups) if gt.groups else 0.0
    precision = tp / len(kept) if kept else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "removed": 1.0 - kept_dur / gt.total if gt.total else 0.0,
        "nonpoint_fp": np_fp,
        "n_kept": len(kept),
    }


def _merge(spans: List[Span]) -> List[Span]:
    out: List[Span] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def timeline_iou(a: List[Span], b: List[Span]) -> float:
    """두 구간 집합의 타임라인 IoU (합집합 대비 교집합 시간)."""
    a = _merge(list(a))
    b = _merge(list(b))
    inter = sum(_ovl(x, y) for x in a for y in b)
    dur_a = sum(e - s for s, e in a)
    dur_b = sum(e - s for s, e in b)
    union = dur_a + dur_b - inter
    return inter / union if union > 0 else 0.0
