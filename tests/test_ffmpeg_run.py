import pytest
from rally_cut.ffmpeg_run import run_ffmpeg


def test_run_ffmpeg_raises_with_stderr_on_bad_input():
    # 존재하지 않는 입력 -> ffmpeg 실패, stderr가 메시지에 포함되어야 함
    with pytest.raises(RuntimeError) as exc:
        run_ffmpeg(["ffmpeg", "-y", "-i", "definitely_missing_input_xyz.mp4",
                    "-f", "null", "-"])
    msg = str(exc.value)
    assert "ffmpeg 명령 실패" in msg
    assert "stderr" in msg
