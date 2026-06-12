"""cuts.csv의 keep 구간을 720p로 잘라 이어붙인다."""
from typing import List
from .cutlist import CutRow
from .ffmpeg_run import run_ffmpeg


def build_render_cmd(src: str, kept_rows: List[CutRow], dst: str,
                     height: int = 720, crf: int = 23) -> List[str]:
    rows = [r for r in kept_rows if r.keep]
    if not rows:
        raise ValueError("no kept segments to render")

    parts = []
    labels = []
    for i, r in enumerate(rows):
        parts.append(
            f"[0:v]trim=start={r.start}:end={r.end},setpts=PTS-STARTPTS,"
            f"scale=-2:{height}[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={r.start}:end={r.end},asetpts=PTS-STARTPTS[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    concat = "".join(labels) + f"concat=n={len(rows)}:v=1:a=1[outv][outa]"
    filtergraph = ";".join(parts + [concat])

    return [
        "ffmpeg", "-y",
        "-i", src,
        "-filter_complex", filtergraph,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        dst,
    ]


def render(src: str, rows: List[CutRow], dst: str,
           height: int = 720, crf: int = 23) -> str:
    cmd = build_render_cmd(src, rows, dst, height=height, crf=crf)
    run_ffmpeg(cmd)
    return dst
