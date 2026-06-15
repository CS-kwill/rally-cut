// MediaPipe PoseLandmarker (WebGL) 래퍼 — 영상에서 근접선수 손목 시계열 추출.
// 외부검토 v7 §0 정정2(온디바이스 pose=MediaPipe) + 옵션C(공통13) 방향.
// seek 기반: <video> currentTime을 stride로 옮기며 detectForVideo. 단순·견고(WebCodecs 글루 회피).
import { PoseLandmarker, FilesetResolver }
  from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';

// full 모델 = lite보다 무겁지만 키포인트 정확도↑ (폰 역량 최대 활용 방침).
const MODEL =
  'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task';
const WASM =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm';

let landmarker = null;

export async function initPose(log) {
  if (landmarker) return landmarker;
  log && log('MediaPipe 로딩 중…');
  const fileset = await FilesetResolver.forVisionTasks(WASM);
  landmarker = await PoseLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL, delegate: 'GPU' },
    runningMode: 'VIDEO',
    numPoses: 2,            // 복식/배경인물 대비 — 근접선수는 최대 bbox로 선택
  });
  return landmarker;
}

// 이미 그 위치면 'seeked'가 안 떠 영원히 멈추므로 즉시 resolve.
// 타임아웃(잠금/백그라운드로 seek가 영영 안 끝나는 경우) 시 reject.
function seek(video, t, timeoutMs = 4000) {
  return new Promise((resolve, reject) => {
    if (Math.abs(video.currentTime - t) < 1e-3) { resolve(); return; }
    let done = false;
    const cleanup = () => { video.removeEventListener('seeked', onSeeked); clearTimeout(timer); };
    const onSeeked = () => { if (done) return; done = true; cleanup(); resolve(); };
    const timer = setTimeout(() => {
      if (done) return; done = true; cleanup(); reject(new Error('seek timeout'));
    }, timeoutMs);
    video.addEventListener('seeked', onSeeked);
    try { video.currentTime = t; } catch (e) { done = true; cleanup(); reject(e); }
  });
}

// 컨텍스트 손실(화면 꺼짐 등) 후 재호출용 — landmarker 폐기 후 다음 initPose가 재생성.
export function resetPose() {
  try { landmarker && landmarker.close && landmarker.close(); } catch { /* noop */ }
  landmarker = null;
}

// 근접선수 = 정규화 랜드마크에서 bbox 면적 최대인 pose.
// 손목=15(L)/16(R), 어깨=11(L)/12(R) — 어깨중심은 스윙(손목의 몸기준 상대운동) 판별 기준.
function nearPlayerWrists(poses, W, H) {
  if (!poses || !poses.length) return null;
  let best = null, bestArea = -1;
  for (const lm of poses) {
    let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    for (const p of lm) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }
    const area = (x1 - x0) * (y1 - y0);
    if (area > bestArea) { bestArea = area; best = { lm, box: [x0 * W, y0 * H, x1 * W, y1 * H] }; }
  }
  if (!best) return null;
  const wl = best.lm[15], wr = best.lm[16];   // 손목 L/R
  const el = best.lm[13], er = best.lm[14];   // 팔꿈치 L/R (라켓헤드 외삽용)
  const sl = best.lm[11], sr = best.lm[12];   // 어깨 L/R (몸 기준)
  return {
    box: best.box,
    wlx: wl.x * W, wly: wl.y * H, wlv: wl.visibility ?? 1,
    wrx: wr.x * W, wry: wr.y * H, wrv: wr.visibility ?? 1,
    elx: el.x * W, ely: el.y * H, elv: el.visibility ?? 1,
    erx: er.x * W, ery: er.y * H, erv: er.visibility ?? 1,
    sx: (sl.x + sr.x) / 2 * W, sy: (sl.y + sr.y) / 2 * H,
    sv: Math.min(sl.visibility ?? 1, sr.visibility ?? 1),
  };
}

// 영상 전체를 strideSec 간격으로 훑어 근접선수 손목 시계열 반환.
// 반환: [{t, box:[x0,y0,x1,y1], wlx,wly,wlv, wrx,wry,wrv}] (검출 실패 프레임은 생략)
export async function wristSeries(video, { strideSec = 0.1, maxSec = 0, log, onProgress, signal } = {}) {
  await initPose(log);
  const W = video.videoWidth, H = video.videoHeight;
  const dur = maxSec ? Math.min(maxSec, video.duration) : video.duration;
  const out = [];
  let tsMono = 0;
  let lastProg = -1;
  let failStreak = 0;                     // detectForVideo 연속 실패(=GPU 컨텍스트 손실 징후)
  for (let t = 0; t < dur; t += strideSec) {
    if (signal && signal.aborted) throw new DOMException('aborted', 'AbortError');
    try { await seek(video, t); }
    catch (e) {
      // seek 타임아웃 = 화면 꺼짐/백그라운드로 디코더 정지. 조용히 공회전하지 않고 중단.
      throw new Error('영상 탐색이 멈췄습니다(화면 꺼짐 등). 다시 시도하세요.');
    }
    tsMono += 1000;                       // detectForVideo는 단조증가 타임스탬프 필요
    let res;
    try { res = landmarker.detectForVideo(video, tsMono); failStreak = 0; }
    catch (e) {
      if (++failStreak > 30) throw new Error('포즈 엔진이 멈췄습니다(화면 꺼짐 등). 다시 시도하세요.');
      continue;
    }
    const w = nearPlayerWrists(res.landmarks, W, H);
    if (w) out.push({ t, ...w });
    // 진행률은 검출 성공 여부와 무관하게 스캔 위치 기준(0.5s마다) — 검출 0이어도 멈춘 듯 안 보이게.
    if (onProgress && t - lastProg >= 0.5) { lastProg = t; onProgress(t, dur, out.length); }
  }
  return { series: out, W, H, dur };
}

export const hasRVFC = 'requestVideoFrameCallback' in HTMLVideoElement.prototype;

// 폰 역량 최대 활용 경로: 영상을 재생하며 requestVideoFrameCallback으로 디코드되는
// 프레임마다 pose 추출(순차 HW 디코드 — seek보다 빠르고 고프레임). minDt로 과샘플만 제한.
// rate=배속(브라우저가 클램프하면 그 값). seek 대비 ~native fps 샘플링.
export async function wristSeriesPlayback(
  video, { rate = 4, minDt = 1 / 30, log, onProgress, signal } = {}) {
  await initPose(log);
  const W = video.videoWidth, H = video.videoHeight;
  const dur = video.duration;
  const out = [];
  let tsMono = 0, lastT = -1e9, lastProg = -1, handle = null;
  video.muted = true;
  video.playbackRate = rate;
  return await new Promise((resolve, reject) => {
    const cleanup = () => {
      try { if (handle) video.cancelVideoFrameCallback(handle); } catch { /* noop */ }
      video.removeEventListener('ended', onEnded);
      document.removeEventListener('visibilitychange', onHide);
      try { video.pause(); } catch { /* noop */ }
    };
    const onEnded = () => { cleanup(); resolve({ series: out, W, H, dur }); };
    const onHide = () => {
      // 화면 꺼짐/백그라운드 → 재생 정지로 콜백이 영영 안 와 멈춤. 즉시 중단.
      if (document.hidden) { cleanup(); reject(new DOMException('aborted', 'AbortError')); }
    };
    const onFrame = (_now, meta) => {
      if (signal && signal.aborted) { cleanup(); reject(new DOMException('aborted', 'AbortError')); return; }
      const t = meta.mediaTime;
      if (t - lastT >= minDt) {
        lastT = t;
        tsMono += 1000;
        try {
          const res = landmarker.detectForVideo(video, tsMono);
          const w = nearPlayerWrists(res.landmarks, W, H);
          if (w) out.push({ t, ...w });
        } catch { /* 프레임 스킵 */ }
      }
      if (onProgress && t - lastProg >= 0.5) { lastProg = t; onProgress(t, dur, out.length); }
      handle = video.requestVideoFrameCallback(onFrame);
    };
    document.addEventListener('visibilitychange', onHide);
    video.addEventListener('ended', onEnded);
    handle = video.requestVideoFrameCallback(onFrame);
    video.play().catch((e) => { cleanup(); reject(e); });
  });
}
