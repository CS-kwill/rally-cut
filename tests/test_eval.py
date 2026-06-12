import json
import numpy as np
import pytest
from rally_cut.eval import load_groundtruth, evaluate_cuts, timeline_iou


def test_load_groundtruth(tmp_path):
    gt = {
        "total": 100.0,
        "groups": [[[4, 8]], [[28, 35], [40, 48]]],
        "nonpoints": [[17, 24]],
    }
    p = tmp_path / "gt.json"
    p.write_text(json.dumps(gt), encoding="utf-8")
    g = load_groundtruth(str(p))
    assert g.total == 100.0
    assert g.groups == [[(4.0, 8.0)], [(28.0, 35.0), (40.0, 48.0)]]
    assert g.nonpoints == [(17.0, 24.0)]


def _gt():
    from rally_cut.eval import GroundTruth
    return GroundTruth(total=100.0,
                       groups=[[(10.0, 20.0)], [(40.0, 50.0)], [(70.0, 80.0)]],
                       nonpoints=[(25.0, 35.0)])


def test_evaluate_cuts_perfect():
    m = evaluate_cuts([(10, 20), (40, 50), (70, 80)], _gt())
    assert m["recall"] == 1.0
    assert m["precision"] == 1.0
    assert m["f1"] == 1.0
    assert m["nonpoint_fp"] == 0
    assert abs(m["removed"] - 0.7) < 1e-9


def test_evaluate_cuts_miss_and_fp():
    # 포인트 1개만 커버 + 비포인트 1개 오검출
    m = evaluate_cuts([(10, 20), (25, 35)], _gt())
    assert abs(m["recall"] - 1/3) < 1e-9
    assert abs(m["precision"] - 0.5) < 1e-9
    assert m["nonpoint_fp"] == 1


def test_evaluate_cuts_half_coverage_counts():
    # 그룹의 50%+ 커버 시 회수로 인정
    m = evaluate_cuts([(14.9, 20.0)], _gt())   # 10~20의 51%
    assert abs(m["recall"] - 1/3) < 1e-9


def test_evaluate_cuts_empty():
    m = evaluate_cuts([], _gt())
    assert m["recall"] == 0 and m["precision"] == 0 and m["f1"] == 0


def test_timeline_iou():
    a = [(0.0, 10.0)]
    b = [(5.0, 15.0)]
    assert abs(timeline_iou(a, b) - 5.0/15.0) < 1e-9


def test_timeline_iou_disjoint_and_empty():
    assert timeline_iou([(0, 1)], [(2, 3)]) == 0.0
    assert timeline_iou([], [(2, 3)]) == 0.0
