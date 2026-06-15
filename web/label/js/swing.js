// 스윙 검출(V2, pure pose) — 라켓헤드(추정) 속도 피크 = 스윙 후보. 오디오 완전 배제.
//
// 사용자 도메인 통찰(2026-06-15): 스윙 = 라켓헤드가 빠르게 휘둘러지는 것. 손목보다
// 라켓헤드가 지렛대가 길어 훨씬 빠르다 → 걷기/공줍기와 변별력 큼. 라켓은 pose 랜드마크에
// 없으므로 팔(팔꿈치→손목) 연장선으로 라켓헤드를 외삽한다.
//   tip = wrist + RACKET_RATIO * (wrist - elbow)
// 그리고 "걸어갈 때 손목도 같이 이동"하는 병진운동을 빼기 위해 어깨중심 기준 상대운동을,
// 카메라 거리 무관하도록 신장(box 높이)으로 정규화한다. 단위 = 신장/초.
// 백분위(상대) 임계는 영상 내용과 무관하게 항상 상위 N%를 통과시켜 걷기를 스윙으로
// 오검출 → 폐기. 대신 절대 임계값(신장/초) 사용.

const RACKET_RATIO = 1.8;   // 손목 너머 라켓헤드까지 외삽 비율(전완 길이 배수, 근사)

function tip(wx, wy, ex, ey) {
  return [wx + RACKET_RATIO * (wx - ex), wy + RACKET_RATIO * (wy - ey)];
}

// 한 팔의 라켓헤드(어깨 기준, 신장 정규화) 상대속도[신장/초]. 가시성 불충분 시 -1.
function armTipSpeed(a, b, h, w, e, visMin) {
  if (a[w + 'v'] < visMin || b[w + 'v'] < visMin) return -1;
  if (a[e + 'v'] < visMin || b[e + 'v'] < visMin) return -1;
  const [ax, ay] = tip(a[w + 'x'], a[w + 'y'], a[e + 'x'], a[e + 'y']);
  const [bx, by] = tip(b[w + 'x'], b[w + 'y'], b[e + 'x'], b[e + 'y']);
  // 어깨중심 기준 상대위치를 신장으로 정규화
  const arx = (ax - a.sx) / h, ary = (ay - a.sy) / h;
  const brx = (bx - b.sx) / h, bry = (by - b.sy) / h;
  return Math.hypot(brx - arx, bry - ary);
}

// 라켓헤드 속도 시계열. 좌/우 팔 중 빠른 쪽(=라켓 든 팔) 채택.
// gap(>maxDt)·저신뢰(visibility<visMin)·어깨 미검출은 연결을 끊는다.
// 반환 sp 단위 = 신장/초 (속도 = 상대변위/Δt를 dt로 나눔).
export function swingSpeed(series, { visMin = 0.4, maxDt = 0.2 } = {}) {
  const tm = [];
  const sp = [];
  for (let i = 1; i < series.length; i++) {
    const a = series[i - 1];
    const b = series[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > maxDt) continue;
    if (a.sv < visMin || b.sv < visMin) continue;       // 몸 기준 필요
    const h = ((a.box[3] - a.box[1]) + (b.box[3] - b.box[1])) / 2;
    if (!(h > 1)) continue;
    const sl = armTipSpeed(a, b, h, 'wl', 'el', visMin); // 왼팔
    const sr = armTipSpeed(a, b, h, 'wr', 'er', visMin); // 오른팔
    const best = Math.max(sl, sr);
    if (best >= 0) { tm.push((a.t + b.t) / 2); sp.push(best / dt); }
  }
  return { tm, sp };
}

// numpy 기본(linear interpolation) 백분위 — 통계/UI용 (피크 임계엔 미사용).
export function percentile(arr, p) {
  if (!arr.length) return 0;
  const s = [...arr].sort((x, y) => x - y);
  const idx = (p / 100) * (s.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

// 라켓헤드 속도의 국소 최대 중 minHeight(신장/초) 이상 = 스윙 시각.
// minSep 내 피크는 강한 것만(한 스윙 = 후보 1개). 절대 임계 → 조용한 구간은 0개.
export function speedPeaks(tm, sp, { minHeight = 2.0, minSep = 0.6 } = {}) {
  if (!sp.length) return [];
  const cand = [];
  for (let i = 0; i < sp.length; i++) {
    const left = i > 0 ? sp[i - 1] : -Infinity;
    const right = i < sp.length - 1 ? sp[i + 1] : -Infinity;
    if (sp[i] >= minHeight && sp[i] > left && sp[i] >= right) cand.push({ t: tm[i], v: sp[i] });
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
