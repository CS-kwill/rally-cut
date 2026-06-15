// MediaPipe PoseLandmarker (WebGL) 래퍼 — 영상에서 근접선수 손목 시계열 추출.
// 외부검토 v7 §0 정정2(온디바이스 pose=MediaPipe) + 옵션C(공통13) 방향.
// seek 기반: <video> currentTime을 stride로 옮기며 detectForVideo. 단순·견고(WebCodecs 글루 회피).
import { PoseLandmarker, FilesetResolver }
  from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';

const MODEL =
  'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';
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

function seek(video, t) {
  return new Promise((resolve) => {
    const onSeeked = () => { video.removeEventListener('seeked', onSeeked); resolve(); };
    video.addEventListener('seeked', onSeeked);
    video.currentTime = t;
  });
}

// 근접선수 = 정규화 랜드마크에서 bbox 면적 최대인 pose. 손목=15(L)/16(R).
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
  const wl = best.lm[15], wr = best.lm[16];
  return {
    box: best.box,
    wlx: wl.x * W, wly: wl.y * H, wlv: wl.visibility ?? 1,
    wrx: wr.x * W, wry: wr.y * H, wrv: wr.visibility ?? 1,
  };
}

// 영상 전체를 strideSec 간격으로 훑어 근접선수 손목 시계열 반환.
// 반환: [{t, box:[x0,y0,x1,y1], wlx,wly,wlv, wrx,wry,wrv}] (검출 실패 프레임은 생략)
export async function wristSeries(video, { strideSec = 0.1, maxSec = 0, log, onProgress } = {}) {
  await initPose(log);
  const W = video.videoWidth, H = video.videoHeight;
  const dur = maxSec ? Math.min(maxSec, video.duration) : video.duration;
  const out = [];
  let tsMono = 0;
  for (let t = 0; t < dur; t += strideSec) {
    await seek(video, t);
    tsMono += 1000;                       // detectForVideo는 단조증가 타임스탬프 필요
    let res;
    try { res = landmarker.detectForVideo(video, tsMono); }
    catch (e) { continue; }
    const w = nearPlayerWrists(res.landmarks, W, H);
    if (w) out.push({ t, ...w });
    if (onProgress && (out.length % 10 === 0)) onProgress(t, dur);
  }
  return { series: out, W, H, dur };
}
