import os
import subprocess
import numpy as np
from scipy.io import wavfile
from rally_cut.audio import build_extract_cmd, extract_audio


def test_build_extract_cmd():
    cmd = build_extract_cmd("in.mp4", "out.wav", sr=22050)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd
    assert "out.wav" in cmd
    assert "22050" in cmd
    assert "-ac" in cmd and "1" in cmd  # mono


def test_extract_audio_integration(tmp_path):
    # ffmpeg로 2초짜리 사인파 wav를 직접 생성한 뒤, 그것을 입력으로 추출
    src = tmp_path / "src.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ar", "44100", "-ac", "2", str(src)],
        check=True, capture_output=True,
    )
    out = tmp_path / "out.wav"
    sr, x = extract_audio(str(src), str(out), sr=22050)
    assert os.path.exists(out)
    assert sr == 22050
    assert x.ndim == 1            # mono
    assert abs(len(x) / sr - 2.0) < 0.1
