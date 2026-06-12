"""cuts.csv 입출력. 컬럼: index,start,end,keep,dur."""
import csv
from dataclasses import dataclass
from typing import List
from .segments import Segment
from .timecode import parse_tc, format_tc

FIELDS = ["index", "start", "end", "keep", "dur"]


@dataclass
class CutRow:
    index: int
    start: float
    end: float
    keep: bool

    @property
    def duration(self) -> float:
        return self.end - self.start


def write_cutlist(path: str, segments: List[Segment], min_keep_duration: float = 10.0,
                  veto_flags: List[bool] = None) -> None:
    """veto_flags(소프트 veto): veto된 구간은 행을 유지한 채 keep=N으로 기록 —
    drop이 아니라 추천이므로 사용자가 검수에서 Y로 되돌릴 수 있다 (v3 Q2)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, seg in enumerate(segments, start=1):
            keep = seg.duration >= min_keep_duration
            if veto_flags is not None and veto_flags[i - 1]:
                keep = False
            w.writerow({
                "index": i,
                "start": format_tc(seg.start),
                "end": format_tc(seg.end),
                "keep": "Y" if keep else "N",
                "dur": f"{round(seg.duration)}s",
            })


def _to_bool(text: str) -> bool:
    return str(text).strip().upper() in ("Y", "YES", "1", "TRUE")


def read_cutlist(path: str) -> List[CutRow]:
    rows: List[CutRow] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for rec in r:
            rows.append(CutRow(
                index=int(rec["index"]),
                start=parse_tc(rec["start"]),
                end=parse_tc(rec["end"]),
                keep=_to_bool(rec["keep"]),
            ))
    return rows
