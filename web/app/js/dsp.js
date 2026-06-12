// rally_cut/detect.py의 충실 포팅 (22050Hz 고정).
// 필터 설계는 런타임에 하지 않는다 — scipy butter 계수를 상수로 임베드
// (빌드 스크립트로 사전 생성, 환경 무관 순수 함수 = Node 대조 테스트 가능).

// butter(4, [1500, 8000] @ 22050Hz, btype='band', output='sos') — scipy 동일
export const SOS = [
  [0.15809758736043159, 0.31619517472086317, 0.15809758736043159, 1.0, 0.6099137080629292, 0.14866010640728733],
  [1.0, -2.0, 1.0, 1.0, -1.2217866629299974, 0.40076718591509963],
  [1.0, 2.0, 1.0, 1.0, 1.025935479716188, 0.6062245976417846],
  [1.0, -2.0, 1.0, 1.0, -1.5976851330018245, 0.7627222544578306],
];
export const SOS_ZI = [
  [0.2015065101407237, 0.10463880396141331],
  [-0.35960409750115524, 0.35960409750115524],
  [0.0, 0.0],
  [-0.0, 0.0],
];
export const PADLEN = 24;
export const SR = 22050;

// 단일 2차 섹션, Direct Form II Transposed (scipy sosfilt와 동일 점화식)
function sosfiltSection(b0, b1, b2, a1, a2, x, z0, z1) {
  const n = x.length;
  for (let i = 0; i < n; i++) {
    const xi = x[i];
    const y = b0 * xi + z0;
    z0 = b1 * xi - a1 * y + z1;
    z1 = b2 * xi - a2 * y;
    x[i] = y;
  }
}

function sosfilt(x, ziScale) {
  // x를 제자리 필터링. ziScale = 초기조건 스케일(x[0] 또는 y[-1]) — sosfiltfilt 규약
  for (let s = 0; s < SOS.length; s++) {
    const [b0, b1, b2, , a1, a2] = SOS[s];
    sosfiltSection(b0, b1, b2, a1, a2, x,
                   SOS_ZI[s][0] * ziScale, SOS_ZI[s][1] * ziScale);
  }
}

// scipy sosfiltfilt(padtype='odd', padlen=PADLEN) 포팅: 영위상 전후방 필터
export function sosfiltfilt(x) {
  const n = x.length;
  if (n <= PADLEN) throw new Error(`입력이 너무 짧음 (${n} <= padlen ${PADLEN})`);
  const ext = new Float64Array(n + 2 * PADLEN);
  for (let i = 0; i < PADLEN; i++) ext[i] = 2 * x[0] - x[PADLEN - i];
  for (let i = 0; i < n; i++) ext[PADLEN + i] = x[i];
  for (let i = 0; i < PADLEN; i++) ext[PADLEN + n + i] = 2 * x[n - 1] - x[n - 2 - i];

  sosfilt(ext, ext[0]);
  ext.reverse();
  sosfilt(ext, ext[0]);
  ext.reverse();

  const out = new Float32Array(n); // detect.py는 filtfilt 결과를 float32로 캐스팅
  for (let i = 0; i < n; i++) out[i] = Math.fround(ext[PADLEN + i]);
  return out;
}

function median(arr) {
  const a = Float64Array.from(arr).sort();
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

// detect_hits(x, sr=22050) 포팅 — x: Float32Array mono [-1,1]
export function detectHits(x, {
  frame = 0.02,
  minSeparation = 0.12,
  threshold = 6.0,
} = {}) {
  if (x.length === 0) return [];
  const y = sosfiltfilt(x);

  const hop = Math.max(1, Math.trunc(frame * SR));
  const nFrames = Math.trunc(y.length / hop);
  if (nFrames === 0) return [];
  const rms = new Float64Array(nFrames);
  for (let f = 0; f < nFrames; f++) {
    let acc = 0;
    const base = f * hop;
    for (let j = 0; j < hop; j++) { const v = y[base + j]; acc += v * v; }
    rms[f] = Math.sqrt(acc / hop + 1e-12);
  }

  const med = median(rms);
  const dev = new Float64Array(nFrames);
  for (let i = 0; i < nFrames; i++) dev[i] = Math.abs(rms[i] - med);
  const thresh = med + threshold * (median(dev) + 1e-12);

  const times = [];
  let last = -1e9;
  for (let i = 1; i < nFrames - 1; i++) {
    if (rms[i] >= thresh && rms[i] >= rms[i - 1] && rms[i] >= rms[i + 1]) {
      const t = (i * hop) / SR;
      if (t - last >= minSeparation) {
        times.push(t);
        last = t;
      }
    }
  }
  return times;
}
