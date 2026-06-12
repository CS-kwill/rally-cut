import subprocess
import numpy as np
from rally_cut.motion import build_motion_cmd, motion_series


def test_build_motion_cmd():
    cmd = build_motion_cmd("in.mp4", fps=4, width=160, height=90)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd
    assert "fps=4" in joined
    assert "scale=160:90" in joined
    assert "gray" in joined
    assert cmd[-1] == "pipe:1"


def test_motion_series_detects_movement(tmp_path):
    # 앞 2초 정지(단색) + 뒤 2초 움직임(testsrc) 영상
    src = tmp_path / "mv.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=2:r=15",
         "-f", "lavfi", "-i", "testsrc=s=160x90:d=2:r=15",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
         "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True,
    )
    times, scores = motion_series(str(src), fps=4, width=160, height=90)
    assert len(times) == len(scores)
    assert len(scores) >= 6
    # 앞 절반(정지) 평균 < 뒤 절반(움직임) 평균
    half = len(scores) // 2
    assert scores[:half].mean() < scores[half:].mean()
