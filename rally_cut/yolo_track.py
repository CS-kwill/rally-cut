"""YOLO 근거리 선수 추적으로 속도 시계열을 만든다. (순수 헬퍼 + 통합)"""
import os
import subprocess
from typing import List, Optional, Tuple
import numpy as np


def build_clip_cmd(video: str, start: float, dur: float, dst: str, fps: int = 6) -> List[str]:
    return [
        "ffmpeg", "-y",
        "-ss", str(start), "-t", str(dur),
        "-i", video,
        "-an", "-vf", f"fps={fps}",
        "-c:v", "libx264", "-preset", "ultrafast",
        dst,
    ]


def build_fps_cmd(video: str, dst: str, fps: int = 3) -> List[str]:
    """전체 영상을 목표 fps로 재인코딩(연속 추적용)."""
    return [
        "ffmpeg", "-y",
        "-i", video,
        "-an", "-vf", f"fps={fps}",
        "-c:v", "libx264", "-preset", "ultrafast",
        dst,
    ]


def select_near_player(boxes_xyxy, img_h: float = None,
                       top_frac: float = 0.4) -> Optional[int]:
    """사람 박스(N,4 xyxy) 중 최대 면적(근거리 선수) 인덱스. 비면 None.

    img_h 지정 시 중심 y가 상단 top_frac 이내인 박스(심판/관중/원거리 선수)는
    제외 — 고정 카메라에서 근거리 선수는 항상 화면 하단. 점프성 가짜 속도 차단.
    """
    b = np.asarray(boxes_xyxy, dtype=float)
    if b.ndim != 2 or b.shape[0] == 0:
        return None
    idx = np.arange(b.shape[0])
    if img_h is not None:
        cy = (b[:, 1] + b[:, 3]) / 2.0
        idx = idx[cy >= top_frac * img_h]
        if idx.size == 0:
            return None
    areas = (b[idx, 2] - b[idx, 0]) * (b[idx, 3] - b[idx, 1])
    return int(idx[np.argmax(areas)])


def centroids_to_speed(cx, cy, smooth: int = 5) -> np.ndarray:
    """중심점 시퀀스 → 평활 속도. NaN은 선형보간, 전부 NaN이면 0."""
    cx = np.asarray(cx, dtype=float)
    cy = np.asarray(cy, dtype=float)
    n = len(cx)
    if n == 0:
        return np.zeros(0)
    idx = np.arange(n)
    valid = ~np.isnan(cx)
    if valid.sum() == 0:
        return np.zeros(n)
    cxi = np.interp(idx, idx[valid], cx[valid])
    cyi = np.interp(idx, idx[valid], cy[valid])
    sp = np.zeros(n)
    sp[1:] = np.hypot(np.diff(cxi), np.diff(cyi))
    if smooth > 1 and n >= smooth:
        sp = np.convolve(sp, np.ones(smooth) / smooth, mode="same")
    return sp


def track_speed_continuous(
    video: str,
    fps: int = 3,
    imgsz: int = 640,
    conf: float = 0.2,
    work_dir: str = "work_yolo",
) -> Tuple[np.ndarray, np.ndarray]:
    """전체 영상을 다운샘플해 프레임별 최대면적(근거리 선수) 연속 속도 시계열 생성.

    윈도우별 독립 추적(track_player_speed)과 달리 전 영상 연속 신호 + 평활이라
    dwell 검출에 적합. 선택전략 비교 측정(540p/720p)에서 프레임별 최대면적이
    트랙ID 기반 선택을 모두 이김(AUC 0.71~0.72, dwell 정합 14/17).
    사람 미검출 영상도 0 속도 반환.
    """
    from ultralytics import YOLO
    os.makedirs(work_dir, exist_ok=True)
    clip = os.path.join(work_dir, "full_fps.mp4")
    subprocess.run(build_fps_cmd(video, clip, fps=fps),
                   check=True, capture_output=True)
    model = YOLO("yolov8n.pt")
    cx: List[float] = []
    cy: List[float] = []
    for r in model(clip, stream=True, classes=[0], conf=conf, imgsz=imgsz,
                   verbose=False):
        b = r.boxes
        if b is None or len(b) == 0:
            cx.append(np.nan); cy.append(np.nan); continue
        xyxy = b.xyxy.cpu().numpy()
        j = select_near_player(xyxy, img_h=r.orig_shape[0])
        if j is None:
            cx.append(np.nan); cy.append(np.nan); continue
        x0, y0, x1, y1 = xyxy[j]
        cx.append((x0 + x1) / 2.0); cy.append((y0 + y1) / 2.0)
    sp = centroids_to_speed(np.asarray(cx), np.asarray(cy))
    t = np.arange(len(sp)) / float(fps)
    return t, sp


def track_player_speed(
    video: str,
    windows,
    fps: int = 6,
    imgsz: int = 640,
    conf: float = 0.2,
    work_dir: str = "work_yolo",
) -> Tuple[np.ndarray, np.ndarray]:
    """각 window(원본 초)별로 클립 추출→YOLO person 근거리선수 추적→원본 시간축 속도.

    사람이 한 명도 안 잡혀도(합성영상 등) 크래시 없이 0 속도를 반환한다.
    """
    from ultralytics import YOLO
    os.makedirs(work_dir, exist_ok=True)
    model = YOLO("yolov8n.pt")
    all_t: List[float] = []
    all_s: List[float] = []
    for wi, (ws, we) in enumerate(windows):
        dur = float(we) - float(ws)
        if dur <= 0:
            continue
        clip = os.path.join(work_dir, f"clip_{wi}.mp4")
        subprocess.run(build_clip_cmd(video, float(ws), dur, clip, fps=fps),
                       check=True, capture_output=True)
        cx: List[float] = []
        cy: List[float] = []
        for r in model(clip, stream=True, classes=[0], conf=conf, imgsz=imgsz, verbose=False):
            b = r.boxes
            if b is None or len(b) == 0:
                cx.append(np.nan); cy.append(np.nan); continue
            xyxy = b.xyxy.cpu().numpy()
            j = select_near_player(xyxy, img_h=r.orig_shape[0])
            if j is None:
                cx.append(np.nan); cy.append(np.nan); continue
            x0, y0, x1, y1 = xyxy[j]
            cx.append((x0 + x1) / 2.0); cy.append((y0 + y1) / 2.0)
        sp = centroids_to_speed(cx, cy)
        t = float(ws) + np.arange(len(sp)) / float(fps)
        all_t.extend(t.tolist()); all_s.extend(sp.tolist())
    return np.asarray(all_t), np.asarray(all_s)
