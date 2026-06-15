// 스윙 검출(V2, pure pose) — 손목 시계열 → 속도 → 피크(스윙 후보).
// 오디오 완전 배제. rally_cut/swing_detect.wrist_speed_series + hit_events.wrist_peaks 포팅.
// 입력 series는 pose_mp.wristSeries 산출: [{t, wlx,wly,wlv, wrx,wry,wrv}] (실패 프레임 생략).

// 연속 유효표본쌍의 변위/Δt = 손목 속도[px/s]. 좌/우 손목 중 빠른 쪽 채택.
// gap(>maxDt)·저신뢰(visibility<visMin)는 연결을 끊어 가짜 고속도를 막는다.
export function swingSpeed(series, { visMin = 0.3, maxDt = 0.35 } = {}) {
  const tm = [];
  const sp = [];
  for (let i = 1; i < series.length; i++) {
    const a = series[i - 1];
    const b = series[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > maxDt) continue; // 결측/큰 간격 → 끊기
    let best = -1;
    if (a.wlv >= visMin && b.wlv >= visMin) {
      best = Math.max(best, Math.hypot(b.wlx - a.wlx, b.wly - a.wly) / dt);
    }
    if (a.wrv >= visMin && b.wrv >= visMin) {
      best = Math.max(best, Math.hypot(b.wrx - a.wrx, b.wry - a.wry) / dt);
    }
    if (best >= 0) { tm.push((a.t + b.t) / 2); sp.push(best); }
  }
  return { tm, sp };
}

// numpy 기본(linear interpolation) 백분위.
export function percentile(arr, p) {
  if (!arr.length) return 0;
  const s = [...arr].sort((x, y) => x - y);
  const idx = (p / 100) * (s.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

// 평활 속도 시계열의 국소 최대(>= th) = 스윙 시각. minSep 내 피크는 강한 것만 남긴다
// (한 스윙이 여러 피크로 쪼개지는 것 방지 — 라벨 후보는 스윙당 1개).
export function speedPeaks(tm, sp, { pctl = 85, minSep = 0.6, minHeight = 0 } = {}) {
  if (!sp.length) return [];
  const th = Math.max(minHeight, percentile(sp, pctl));
  const cand = [];
  for (let i = 0; i < sp.length; i++) {
    const left = i > 0 ? sp[i - 1] : -Infinity;
    const right = i < sp.length - 1 ? sp[i + 1] : -Infinity;
    if (sp[i] >= th && sp[i] > left && sp[i] >= right) cand.push({ t: tm[i], v: sp[i] });
  }
  cand.sort((a, b) => a.t - b.t);
  const out = [];
  for (const c of cand) {
    const last = out[out.length - 1];
    if (last && c.t - last.t < minSep) { if (c.v > last.v) out[out.length - 1] = c; }
    else out.push(c);
  }
  return out.map((c) => c.t);
}
