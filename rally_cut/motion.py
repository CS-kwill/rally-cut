"""ffmpeg 저해상도 디코딩 + 카메라 흔들림 보정 후 프레임 차분으로 움직임 시계열을 만든다."""
import subprocess
from typing import List, Tuple
import numpy as np


def build_motion_cmd(video: str, fps: int = 4, width: int = 160, height: int = 90) -> List[str]:
    return [
        "ffmpeg", "-v", "error",
        "-i", video,
        "-vf", f"fps={fps},scale={width}:{height},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "pipe:1",
    ]


def _frames(video: str, fps: int, width: int, height: int):
    cmd = build_motion_cmd(video, fps, width, height)
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"ffmpeg 움직임 디코딩 실패:\n{stderr[-1500:]}")
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    fsize = width * height
    n = buf.size // fsize
    return buf[: n * fsize].reshape(n, height, width)


def motion_series(video: str, fps: int = 4, width: int = 160, height: int = 90
                  ) -> Tuple[np.ndarray, np.ndarray]:
    """(시각[초], 움직임점수) 반환. phaseCorrelate로 흔들림 보정 후 프레임 차분 평균."""
    import cv2
    frames = _frames(video, fps, width, height).astype(np.float32)
    n = len(frames)
    if n < 2:
        return np.zeros(0), np.zeros(0)
    win = cv2.createHanningWindow((width, height), cv2.CV_32F)
    times, scores = [], []
    for i in range(1, n):
        prev, cur = frames[i - 1], frames[i]
        # 카메라 흔들림(전역 평행이동) 추정·보정 — 프레임이 충분히 텍스처 있을 때만
        if prev.std() > 1.0 and cur.std() > 1.0:
            (dx, dy), _ = cv2.phaseCorrelate(prev, cur, win)
            M = np.float32([[1, 0, -dx], [0, 1, -dy]])
            cur_al = cv2.warpAffine(cur, M, (width, height),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        else:
            cur_al = cur
        diff = np.abs(cur_al - prev)
        scores.append(float(diff.mean()))
        times.append(i / float(fps))
    return np.asarray(times), np.asarray(scores)
