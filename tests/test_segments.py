from rally_cut.segments import build_segments, Segment


def test_two_clusters_split_by_gap():
    # 0~4초에 타격 모임, 20초 공백, 25~30초에 또 모임
    hits = [0.5, 1.2, 2.0, 3.1, 4.0, 25.0, 26.4, 28.0, 30.0]
    segs = build_segments(
        hits, max_gap=6.0, min_hits=2,
        pad_pre=1.5, pad_post=2.0, min_duration=3.0,
    )
    assert len(segs) == 2
    # 첫 구간: 0.5-1.5 패딩 -> 0, 끝 4.0+2.0=6.0
    assert segs[0].start == 0.0
    assert segs[0].end == 6.0
    assert segs[1].start == 25.0 - 1.5
    assert segs[1].end == 30.0 + 2.0


def test_single_hit_cluster_dropped_by_min_hits():
    hits = [5.0, 50.0, 51.0, 52.0]  # 5.0은 외톨이
    segs = build_segments(hits, max_gap=6.0, min_hits=2,
                          pad_pre=1.0, pad_post=1.0, min_duration=0.0)
    assert len(segs) == 1
    assert segs[0].start == 50.0 - 1.0


def test_short_segment_dropped_by_min_duration():
    hits = [10.0, 10.4, 10.8]  # 매우 짧은 묶음
    segs = build_segments(hits, max_gap=6.0, min_hits=2,
                          pad_pre=0.0, pad_post=0.0, min_duration=3.0)
    assert segs == []


def test_negative_start_clamped_to_zero():
    hits = [0.2, 1.0, 2.0]
    segs = build_segments(hits, max_gap=6.0, min_hits=2,
                          pad_pre=5.0, pad_post=0.0, min_duration=0.0)
    assert segs[0].start == 0.0


def test_empty_input():
    assert build_segments([], max_gap=6.0, min_hits=2,
                          pad_pre=1.0, pad_post=1.0, min_duration=1.0) == []
