from rally_cut.cli import build_parser


def test_analyze_args():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4", "-o", "cuts.csv"])
    assert ns.command == "analyze"
    assert ns.video == "match.mp4"
    assert ns.out == "cuts.csv"


def test_render_args():
    p = build_parser()
    ns = p.parse_args(["render", "match.mp4", "cuts.csv", "-o", "out.mp4"])
    assert ns.command == "render"
    assert ns.video == "match.mp4"
    assert ns.cuts == "cuts.csv"
    assert ns.out == "out.mp4"


def test_analyze_defaults():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.out == "cuts.csv"
    assert ns.min_hits >= 2


def test_analyze_tuned_defaults():
    # 샘플 경기 영상의 ground-truth 스윕에서 최적화된 기본값 (F1 81%)
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.max_gap == 3.0
    assert ns.min_keep_duration == 8.0


def test_analyze_use_motion_flag_defaults_off():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.use_motion is False
    assert ns.motion_fps == 4
    assert ns.motion_k == 1.0
    assert ns.valley_min == 2.0


def test_analyze_use_motion_flag_on():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4", "--use-motion", "--motion-k", "1.5"])
    assert ns.use_motion is True
    assert ns.motion_k == 1.5


def test_analyze_use_yolo_flag_defaults_off():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.use_yolo is False
    assert ns.yolo_fps == 6
    # 2237 정답 스윕 최적점(k=0.8, dwell_min=2.0)
    assert ns.yolo_k == 0.8
    assert ns.dwell_min == 2.0


def test_analyze_use_yolo_flag_on():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4", "--use-yolo",
                       "--yolo-k", "1.2", "--dwell-min", "3.0"])
    assert ns.use_yolo is True
    assert ns.yolo_k == 1.2
    assert ns.dwell_min == 3.0


def test_analyze_onset_density_defaults():
    # dense_gap 0.6 = 측정 분포(POINT 0.33 vs BOUNCE 0.76)의 보수적 중간값(0.5~0.7 둔감).
    # pad_tail 4.0 = 2237/2238 동시 통과 스윕 채택값 (2237 F1 80 유지, 2238 miss 악화 3s).
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.dense_gap == 0.6
    assert ns.pad_tail == 4.0


def test_analyze_onset_density_overrides():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4", "--dense-gap", "0.5",
                       "--pad-tail", "0"])
    assert ns.dense_gap == 0.5
    assert ns.pad_tail == 0.0


def test_analyze_ball_evidence_defaults():
    # veto-rate 0.0 = veto 꺼짐(기본). 측정 확정값: ③AND② th=0.75, 창 [-0.70,+0.71]
    # (Δt p05/p95), min_hits 2 — 2237 실포인트 veto 0건 검증(공추적_구간증거 보고서)
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4"])
    assert ns.ball_cache is None
    assert ns.pose_cache is None
    assert ns.veto_rate == 0.0
    assert ns.hit_win_lo == -0.70
    assert ns.hit_win_hi == 0.71
    assert ns.veto_min_hits == 2
    assert ns.hard_veto is False


def test_analyze_ball_evidence_args():
    p = build_parser()
    ns = p.parse_args(["analyze", "match.mp4", "--ball-cache", "cache_dir",
                       "--veto-rate", "1.5", "--hard-veto"])
    assert ns.ball_cache == "cache_dir"
    assert ns.veto_rate == 1.5
    assert ns.hard_veto is True
