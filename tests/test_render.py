import os
import subprocess
import json
from rally_cut.cutlist import CutRow
from rally_cut.render import build_render_cmd, render


def _kept():
    return [CutRow(1, 1.0, 3.0, True), CutRow(2, 5.0, 6.0, True)]


def test_build_render_cmd_has_concat_and_scale():
    cmd = build_render_cmd("in.mp4", _kept(), "out.mp4", height=720)
    joined = " ".join(cmd)
    assert "filter_complex" in joined
    assert "concat=n=2" in joined
    assert "scale=-2:720" in joined
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "out.mp4"


def test_build_render_cmd_no_kept_raises():
    import pytest
    with pytest.raises(ValueError):
        build_render_cmd("in.mp4", [], "out.mp4")


def _ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def test_render_integration(tmp_path):
    # 10초짜리 테스트 영상(컬러바+사인) 생성
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True, capture_output=True,
    )
    rows = [CutRow(1, 1.0, 3.0, True), CutRow(2, 5.0, 6.0, True), CutRow(3, 8.0, 9.0, False)]
    out = tmp_path / "out.mp4"
    render(str(src), rows, str(out), height=720)
    assert os.path.exists(out)
    # keep=Y 길이 합 = (3-1)+(6-5)=3초. ±0.6초 허용
    assert abs(_ffprobe_duration(str(out)) - 3.0) < 0.6
