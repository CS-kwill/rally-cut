"""ffmpeg/ffprobe subprocess 실행 헬퍼: 실패 시 stderr를 드러낸다."""
import subprocess
from typing import List


def run_ffmpeg(cmd: List[str]) -> subprocess.CompletedProcess:
    """ffmpeg 명령 실행. 실패하면 stderr를 포함한 RuntimeError를 던진다."""
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(
            f"ffmpeg 명령 실패 (exit {proc.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr (마지막 부분):\n{stderr[-2000:]}"
        )
    return proc
