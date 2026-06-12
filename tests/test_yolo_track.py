import numpy as np
import pytest
from rally_cut.yolo_track import build_clip_cmd, select_near_player, centroids_to_speed


def test_build_clip_cmd():
    cmd = build_clip_cmd("in.mp4", 10.0, 5.0, "out.mp4", fps=6)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd and "out.mp4" in cmd
    assert "10.0" in cmd            # -ss start
    assert "5.0" in cmd             # -t dur
    assert "fps=6" in joined
    assert "-an" in cmd             # 오디오 제거


def test_select_near_player_picks_largest_area():
    boxes = np.array([[0, 0, 10, 10],      # 면적 100 (먼 선수)
                      [50, 50, 90, 120]])  # 면적 40*70=2800 (근거리)
    assert select_near_player(boxes) == 1


def test_select_near_player_empty_returns_none():
    assert select_near_player(np.zeros((0, 4))) is None
    assert select_near_player([]) is None


def test_select_near_player_excludes_top_region():
    # 상단 40% 안(중심 y=100 < 0.4*540=216)의 큰 박스(심판/관중)는 제외,
    # 하단의 작은 박스(근거리 선수)를 선택
    boxes = np.array([[0, 0, 300, 200],        # 면적 60000, 중심 y=100 (상단)
                      [50, 400, 90, 500]])     # 면적 4000, 중심 y=450 (하단)
    assert select_near_player(boxes, img_h=540) == 1


def test_select_near_player_all_in_top_returns_none():
    boxes = np.array([[0, 0, 100, 100]])       # 중심 y=50 < 216
    assert select_near_player(boxes, img_h=540) is None


def test_select_near_player_no_img_h_keeps_legacy():
    # img_h 미지정이면 기존 동작(최대 면적) 그대로
    boxes = np.array([[0, 0, 300, 200], [50, 400, 90, 500]])
    assert select_near_player(boxes) == 0


def test_centroids_to_speed_basic():
    # x가 프레임당 +3씩 이동 → 속도 ~3 (양끝 평활 영향 제외)
    cx = np.array([0.0, 3.0, 6.0, 9.0, 12.0])
    cy = np.zeros(5)
    sp = centroids_to_speed(cx, cy, smooth=1)
    assert sp.shape == (5,)
    assert sp[0] == 0.0
    assert np.allclose(sp[1:], 3.0)


def test_centroids_to_speed_interpolates_nan():
    cx = np.array([0.0, np.nan, 4.0])
    cy = np.array([0.0, 0.0, 0.0])
    sp = centroids_to_speed(cx, cy, smooth=1)
    assert not np.isnan(sp).any()


def test_centroids_to_speed_all_nan_returns_zeros():
    cx = np.array([np.nan, np.nan]); cy = np.array([np.nan, np.nan])
    sp = centroids_to_speed(cx, cy, smooth=1)
    assert sp.shape == (2,) and np.all(sp == 0)


def test_build_fps_cmd():
    from rally_cut.yolo_track import build_fps_cmd
    cmd = build_fps_cmd("in.mp4", "out.mp4", fps=3)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd and "out.mp4" in cmd
    assert "fps=3" in joined
    assert "-an" in cmd
    assert "-ss" not in cmd and "-t" not in cmd  # 전체 영상


def test_track_speed_continuous_runs_and_shapes(tmp_path):
    # 합성 영상(사람 없음): 크래시 없이 (times, speeds) 동일 길이, 속도 전부 0
    import subprocess
    from rally_cut.yolo_track import track_speed_continuous
    src = tmp_path / "syn.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=4:r=12",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True,
    )
    times, speeds = track_speed_continuous(str(src), fps=3,
                                           work_dir=str(tmp_path / "yw"))
    assert len(times) == len(speeds)
    assert len(times) >= 1
    assert np.all(speeds == 0)


def test_track_player_speed_runs_and_shapes(tmp_path):
    # 합성 영상(사람 없음): 크래시 없이 (times, speeds) 동일 길이 반환해야 함
    import subprocess
    from rally_cut.yolo_track import track_player_speed
    src = tmp_path / "syn.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=4:r=12",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True,
    )
    times, speeds = track_player_speed(str(src), [(0.0, 4.0)], fps=4,
                                       work_dir=str(tmp_path / "yw"))
    assert len(times) == len(speeds)
    assert len(times) >= 1
