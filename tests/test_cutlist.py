from rally_cut.segments import Segment
from rally_cut.cutlist import write_cutlist, read_cutlist


def test_write_and_read_roundtrip(tmp_path):
    segs = [Segment(12.0, 38.0), Segment(65.0, 71.0), Segment(100.0, 142.0)]
    path = tmp_path / "cuts.csv"
    write_cutlist(str(path), segs, min_keep_duration=10.0)

    rows = read_cutlist(str(path))
    assert len(rows) == 3
    # 6초짜리 두번째는 자동 keep=False
    assert rows[0].keep is True
    assert rows[1].keep is False
    assert rows[2].keep is True
    assert rows[0].start == 12.0
    assert rows[2].end == 142.0


def test_read_only_returns_kept(tmp_path):
    segs = [Segment(12.0, 38.0), Segment(65.0, 71.0)]
    path = tmp_path / "cuts.csv"
    write_cutlist(str(path), segs, min_keep_duration=10.0)
    kept = [r for r in read_cutlist(str(path)) if r.keep]
    assert len(kept) == 1
    assert kept[0].start == 12.0


def test_write_soft_veto_marks_keep_n(tmp_path):
    # 소프트 veto (v3 Q2): veto된 구간은 행을 유지한 채 keep=N 추천 — 수동 검수로 복구 가능
    segs = [Segment(0.0, 20.0), Segment(30.0, 50.0), Segment(60.0, 80.0)]
    path = tmp_path / "cuts.csv"
    write_cutlist(str(path), segs, min_keep_duration=0.0,
                  veto_flags=[False, True, False])
    rows = read_cutlist(str(path))
    assert [r.keep for r in rows] == [True, False, True]
    assert len(rows) == 3                      # 행은 전부 유지


def test_write_without_veto_flags_backward_compatible(tmp_path):
    segs = [Segment(0.0, 20.0)]
    path = tmp_path / "cuts.csv"
    write_cutlist(str(path), segs, min_keep_duration=0.0)
    assert read_cutlist(str(path))[0].keep is True


def test_user_edited_keep_respected(tmp_path):
    path = tmp_path / "cuts.csv"
    path.write_text(
        "index,start,end,keep,dur\n"
        "1,00:00:12.000,00:00:38.000,N,26s\n"
        "2,00:01:05.000,00:01:11.000,Y,6s\n",
        encoding="utf-8",
    )
    rows = read_cutlist(str(path))
    assert rows[0].keep is False
    assert rows[1].keep is True
    assert rows[1].start == 65.0
