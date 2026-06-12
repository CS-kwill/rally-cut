"""rally-cut 명령줄 인터페이스: analyze / render."""
import argparse
import os
import sys
from . import audio, detect, segments as seg_mod, cutlist, render as render_mod


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rally-cut",
                                description="테니스 영상 죽은 시간 자동 제거")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="영상 분석 -> cuts.csv")
    a.add_argument("video")
    a.add_argument("-o", "--out", default="cuts.csv")
    a.add_argument("--work", default="work", help="중간 wav 저장 폴더")
    # 기본값은 샘플 경기 영상의 ground-truth 스윕에서 F1 최적점.
    # max-gap 3.0 / min-keep 8.0: Recall 80% · Precision 82% · 제거율 ~45%.
    a.add_argument("--max-gap", type=float, default=3.0)
    a.add_argument("--min-hits", type=int, default=3)
    a.add_argument("--pad-pre", type=float, default=1.5)
    a.add_argument("--pad-post", type=float, default=2.0)
    a.add_argument("--min-duration", type=float, default=3.0)
    a.add_argument("--min-keep-duration", type=float, default=8.0)
    a.add_argument("--use-motion", action="store_true",
                   help="화면 움직임으로 죽은시간 정밀 컷(opencv 필요)")
    a.add_argument("--motion-fps", type=int, default=4)
    a.add_argument("--motion-k", type=float, default=1.0,
                   help="움직임 활성 임계 민감도(p25~p90 갭의 k*0.5 지점; 클수록 엄격)")
    a.add_argument("--valley-min", type=float, default=2.0,
                   help="구간 내부를 분리할 최소 비활성 길이(초)")
    a.add_argument("--use-yolo", action="store_true",
                   help="YOLO 선수추적 dwell 게이트로 후보 검증(ultralytics 필요)")
    a.add_argument("--yolo-fps", type=int, default=6)
    # 기본값은 샘플 경기 영상의 정답 스윕 최적점(k=0.8, dwell_min=2.0):
    # 게이트 OR min_keep으로 Recall 87% 유지 + 초단타 포인트 회복.
    a.add_argument("--yolo-k", type=float, default=0.8,
                   help="dwell 임계 민감도(p25~p90 갭; 클수록 dwell 엄격)")
    a.add_argument("--dwell-min", type=float, default=2.0,
                   help="dwell(서브/리턴 준비 정지)로 인정할 최소 지속(초)")
    # 온셋밀도(AUC 0.89)는 꼬리 트리밍에만 배선. 게이트 keep-OR 보강은 측정 기각:
    # 2237 F1 80->76~79(전 조합), 2238 과보존 337->345s — 둘 다 악화.
    # pad_tail=4.0: 2237 F1 80 유지 + 2238 IoU 49->50, 과보존 -25s, miss +3s(<=5s 허용).
    a.add_argument("--dense-gap", type=float, default=0.6,
                   help="밀집 온셋 간격 임계(초): 직전 온셋과 이 간격 이내면 랠리 리듬"
                        " (꼬리 트리밍의 기준점, 0.5~0.7 둔감)")
    a.add_argument("--pad-tail", type=float, default=4.0,
                   help="마지막 밀집 온셋 뒤 보존 여유(초). 0 이하면 꼬리 트리밍 안 함")
    # 공 왕복 증거 veto (v3 Q2): 추론은 외부(_ball_cache.py, wasb venv) — CLI는 캐시만 소비.
    # veto-rate 0.0 = 꺼짐. 임계는 3-1 분포 측정으로 확정(상수 선결정 금지, v3 Q1).
    a.add_argument("--ball-cache", default=None,
                   help="[실험적/기본 꺼짐] WASB 원시 검출 캐시 폴더. 지정 시 왕복"
                        " 증거 부재 구간을 keep=N으로 강등(소프트 veto). 보류 사유:"
                        " Tennis/공추적_구간증거_측정_20260611.md §5")
    a.add_argument("--pose-cache", default=None,
                   help="[실험적/기본 꺼짐] pose 손목속도 캐시 폴더. veto를"
                        " ③왕복 AND ②타구 복합 조건으로 (③단독은 측정 기각)")
    a.add_argument("--veto-rate", type=float, default=0.0,
                   help="[실험적/기본 꺼짐] 왕복 증거 임계(가로지름 개/10s)."
                        " 0=끔(기본 — 약신호 구간 오인이 측정으로 확인돼 보류)")
    a.add_argument("--hit-win-lo", type=float, default=-0.70,
                   help="[실험적] 타구 정합 창 하한(피크-온셋 초, Δt p05)")
    a.add_argument("--hit-win-hi", type=float, default=0.71,
                   help="[실험적] 타구 정합 창 상한(Δt p95)")
    a.add_argument("--veto-min-hits", type=int, default=2,
                   help="[실험적] 구간을 살리는 최소 검증타구 수(② 증거)")
    a.add_argument("--hard-veto", action="store_true",
                   help="[실험적/기본 꺼짐] veto 구간을 cuts.csv에서 아예 제외"
                        "(기본: keep=N 추천만)")
    # 서브 폴트 보존 (외부검토 v5 §4): 확정 keep 직전 1~2타격 군집 병합/별도 keep.
    a.add_argument("--fault-prepend-window", type=float, default=0.0,
                   help="확정 keep 직전 이 초 이내의 1~2타격 군집(서브 폴트)을"
                        " 보존. 0=끔(기본). 권장 25 — 회귀 측정:"
                        " Tennis/폴트prepend_측정_20260613.md")

    r = sub.add_parser("render", help="cuts.csv -> 720p 영상")
    r.add_argument("video")
    r.add_argument("cuts")
    r.add_argument("-o", "--out", default="out.mp4")
    r.add_argument("--height", type=int, default=720)
    r.add_argument("--crf", type=int, default=23)

    return p


def cmd_analyze(ns) -> int:
    os.makedirs(ns.work, exist_ok=True)
    wav = os.path.join(ns.work, "audio.wav")
    print(f"[1/3] 오디오 추출: {ns.video}")
    sr, x = audio.extract_audio(ns.video, wav)
    print("[2/3] 타구음 검출 중...")
    hits = detect.detect_hits(x, sr)
    print(f"      타격 {len(hits)}개 검출")
    segs = seg_mod.build_segments(
        hits, max_gap=ns.max_gap, min_hits=ns.min_hits,
        pad_pre=ns.pad_pre, pad_post=ns.pad_post, min_duration=ns.min_duration,
    )
    if ns.use_yolo:
        from . import yolo_track, pointsm
        print("[2.5/3] YOLO 선수추적 중(전체영상 연속, 시간 걸림)...")
        ytimes, yspeeds = yolo_track.track_speed_continuous(
            ns.video, fps=ns.yolo_fps,
            work_dir=os.path.join(ns.work, "yolo"))
        dwells = pointsm.find_dwells(ytimes, yspeeds,
                                     k=ns.yolo_k, dwell_min=ns.dwell_min)
        before = len(segs)
        segs = pointsm.gate_segments(segs, dwells,
                                     min_keep=ns.min_keep_duration)
        print(f"      dwell 게이트({len(dwells)}개 dwell): {before} -> {len(segs)}구간")
        if ns.pad_tail > 0:
            kept_dur = sum(s.end - s.start for s in segs)
            segs = pointsm.trim_tail(segs, hits,
                                     dense_gap=ns.dense_gap, pad_tail=ns.pad_tail)
            trimmed = kept_dur - sum(s.end - s.start for s in segs)
            print(f"      꼬리 트리밍: {trimmed:.0f}s 제거")
    elif ns.use_motion:
        from . import motion, refine
        print("[2.5/3] 화면 움직임 분석 중...")
        mtimes, mscores = motion.motion_series(ns.video, fps=ns.motion_fps)
        before = len(segs)
        segs = refine.refine_segments(
            segs, mtimes, mscores,
            k=ns.motion_k, valley_min=ns.valley_min, min_duration=ns.min_duration,
        )
        print(f"      움직임 정제: {before} -> {len(segs)}구간")
    # 서브 폴트 prepend (v5 §4) — 최종 keep 직전 1~2타격 군집 보존.
    # veto보다 먼저: 신규/연장 구간은 캐시 start 매칭 실패 → measured=False → veto 불가(안전).
    min_keep = 0.0 if ns.use_yolo else ns.min_keep_duration
    if ns.fault_prepend_window > 0:
        from . import pointsm
        if min_keep > 0:
            segs = [s for s in segs if s.end - s.start >= min_keep]
            min_keep = 0.0  # 이미 반영 — 폴트 keep(짧음)을 다시 죽이지 않는다
        n0, d0 = len(segs), sum(s.end - s.start for s in segs)
        segs = pointsm.prepend_faults(segs, hits, window=ns.fault_prepend_window)
        print(f"      폴트 prepend: +{sum(s.end - s.start for s in segs) - d0:.0f}s, "
              f"{n0} -> {len(segs)}구간")
    veto_flags = None
    if ns.ball_cache and ns.veto_rate > 0:
        from . import ball_evidence, pointsm
        ev = ball_evidence.evidence_from_cache(ns.ball_cache, segs)
        hit_counts = None
        if ns.pose_cache:
            from . import hit_events
            counts, measured = hit_events.counts_from_pose_cache(
                ns.pose_cache, segs, hits, ns.hit_win_lo, ns.hit_win_hi)
            # 결측(②)은 veto 불가 — 충분히 큰 수로 치환 (결측/부재 구분)
            hit_counts = [c if m else 10**9 for c, m in zip(counts, measured)]
        veto_flags = pointsm.veto_segments(segs, ev, rate_th=ns.veto_rate,
                                           hit_counts=hit_counts,
                                           min_hits=ns.veto_min_hits)
        n_meas = sum(1 for e in ev if e["measured"])
        mode = "③AND②" if hit_counts is not None else "③단독(비권장)"
        print(f"      공증거 veto[{mode}]: 측정 {n_meas}/{len(segs)}구간, "
              f"veto {sum(veto_flags)}개"
              f"{' (제외)' if ns.hard_veto else ' (keep=N 추천)'}")
        if ns.hard_veto:
            segs = [s for s, f in zip(segs, veto_flags) if not f]
            veto_flags = None
    print(f"[3/3] 랠리 구간 {len(segs)}개 -> {ns.out}")
    # YOLO 게이트가 이미 keep/drop을 결정 — 구제된 짧은 구간을 다시 죽이지 않는다
    cutlist.write_cutlist(ns.out, segs, min_keep_duration=min_keep,
                          veto_flags=veto_flags)
    return 0


def cmd_render(ns) -> int:
    rows = cutlist.read_cutlist(ns.cuts)
    kept = [r for r in rows if r.keep]
    print(f"keep 구간 {len(kept)}개 렌더링 -> {ns.out}")
    render_mod.render(ns.video, rows, ns.out, height=ns.height, crf=ns.crf)
    print("완료")
    return 0


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "analyze":
        return cmd_analyze(ns)
    if ns.command == "render":
        return cmd_render(ns)
    return 1


if __name__ == "__main__":
    sys.exit(main())
