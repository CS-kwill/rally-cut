// 실측 ② — pose 추론 속도: MediaPipe PoseLandmarker(WebGL) vs YOLOv8n-pose ONNX
// (onnxruntime-web, webgpu→wasm 폴백). 측정값 = VideoFrame 변환+전처리+추론 per-frame ms.
import { demux, trackDescription, sleep } from './demux.js';

const ORT_VER = '1.19.2';
const MP_VER = '0.10.14';

function loadScript(src) {
  return new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = res;
    s.onerror = () => rej(new Error('스크립트 로드 실패: ' + src));
    document.head.appendChild(s);
  });
}

let mpLandmarker = null;
async function getMediaPipe(log) {
  if (mpLandmarker) return mpLandmarker;
  log('MediaPipe tasks-vision 로딩…');
  const mod = await import(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VER}/+esm`);
  const fileset = await mod.FilesetResolver.forVisionTasks(
    `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VER}/wasm`);
  mpLandmarker = await mod.PoseLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
      delegate: 'GPU',
    },
    runningMode: 'VIDEO',
    numPoses: 1,
  });
  log('MediaPipe 준비 완료 (GPU delegate)');
  return mpLandmarker;
}

const ortSessions = {};
async function getOrtSession(provider, log) {
  if (ortSessions[provider]) return ortSessions[provider];
  if (!window.ort) {
    log('onnxruntime-web 로딩…');
    await loadScript(`https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VER}/dist/ort.webgpu.min.js`);
    ort.env.wasm.wasmPaths = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VER}/dist/`;
  }
  log(`ONNX 세션 생성 (EP=${provider})…`);
  const session = await ort.InferenceSession.create('models/yolov8n-pose.onnx', {
    executionProviders: [provider],
  });
  ortSessions[provider] = session;
  return session;
}

// engine: 'mediapipe' | 'onnx-wasm' | 'onnx-webgpu'
export async function poseThroughput(file, { engine, maxFrames = 120, stride = 4, log }) {
  if (!('VideoDecoder' in window)) throw new Error('WebCodecs 미지원 — 실측 ① 선행 확인');

  let detect; // async (videoFrame, tsMs) => ms
  let providerUsed = engine;

  if (engine === 'mediapipe') {
    const lm = await getMediaPipe(log);
    let lastTs = -1;
    detect = async (frame, tsMs) => {
      const t = performance.now();
      const bmp = await createImageBitmap(frame);
      const ts = Math.max(Math.round(tsMs), lastTs + 1);
      lastTs = ts;
      lm.detectForVideo(bmp, ts);
      bmp.close();
      return performance.now() - t;
    };
  } else {
    let provider = engine === 'onnx-webgpu' ? 'webgpu' : 'wasm';
    let session;
    try {
      session = await getOrtSession(provider, log);
    } catch (e) {
      if (provider === 'webgpu') {
        log('webgpu EP 실패(' + e.message + ') → wasm 폴백');
        provider = 'wasm';
        providerUsed = 'onnx-wasm(폴백)';
        session = await getOrtSession(provider, log);
      } else throw e;
    }
    const SZ = 640;
    const canvas = new OffscreenCanvas(SZ, SZ);
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    const inputName = session.inputNames[0];
    const chw = new Float32Array(3 * SZ * SZ);
    detect = async (frame) => {
      const t = performance.now();
      const sc = Math.min(SZ / frame.displayWidth, SZ / frame.displayHeight);
      const dw = Math.round(frame.displayWidth * sc);
      const dh = Math.round(frame.displayHeight * sc);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, SZ, SZ);
      ctx.drawImage(frame, (SZ - dw) / 2, (SZ - dh) / 2, dw, dh);
      const img = ctx.getImageData(0, 0, SZ, SZ).data;
      const n = SZ * SZ;
      for (let i = 0; i < n; i++) {
        chw[i] = img[i * 4] / 255;
        chw[n + i] = img[i * 4 + 1] / 255;
        chw[2 * n + i] = img[i * 4 + 2] / 255;
      }
      await session.run({ [inputName]: new ort.Tensor('float32', chw, [1, 3, SZ, SZ]) });
      return performance.now() - t;
    };
  }

  // 디코딩하며 stride 간격 프레임만 측정 (60fps 영상 stride=4 → 15fps 샘플링 모사)
  const times = [];
  const frameQ = [];
  let decoder = null;
  let decErr = null;
  let decIdx = 0;
  let done = false;

  await demux(file, {
    onReady: async (info, mp4file) => {
      const vt = info.videoTracks[0];
      const cfg = { codec: vt.codec, codedWidth: vt.video.width, codedHeight: vt.video.height };
      const desc = trackDescription(mp4file, vt.id);
      if (desc) cfg.description = desc;
      decoder = new VideoDecoder({
        output: (f) => {
          if (done || decIdx++ % stride !== 0) { f.close(); return; }
          frameQ.push(f);
        },
        error: (e) => { decErr = e; },
      });
      decoder.configure(cfg);
      log(`디코딩 시작 (${vt.codec}, stride=${stride}, 목표 ${maxFrames}프레임)`);
    },
    onVideoSample: async (s) => {
      if (decErr) throw new Error('디코더 오류: ' + decErr.message);
      if (times.length >= maxFrames) return false;
      decoder.decode(new EncodedVideoChunk({
        type: s.is_sync ? 'key' : 'delta',
        timestamp: Math.round((1e6 * s.cts) / s.timescale),
        duration: Math.round((1e6 * s.duration) / s.timescale),
        data: s.data,
      }));
      while (frameQ.length) {
        const f = frameQ.shift();
        const dt = await detect(f, f.timestamp / 1000);
        f.close();
        times.push(dt);
        if (times.length % 30 === 0) log(`…${times.length}/${maxFrames}프레임`);
        if (times.length >= maxFrames) { done = true; return false; }
      }
      while (decoder.decodeQueueSize > 20) await sleep(2);
    },
  });

  done = true;
  try { if (decoder && decoder.state === 'configured') await decoder.flush(); } catch { /* 중단 시 무시 */ }
  while (frameQ.length) frameQ.shift().close();
  if (times.length === 0) throw new Error('측정된 프레임 없음');

  const warm = times.slice(Math.min(3, times.length - 1)); // 워밍업 3프레임 제외
  const sorted = [...warm].sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)];
  const p90 = sorted[Math.floor(sorted.length * 0.9)];
  const mean = warm.reduce((a, b) => a + b, 0) / warm.length;
  // 17분 60fps 영상을 15fps로 샘플링 = 15300프레임 추론
  const projMin = (15300 * med) / 60000;
  return {
    엔진: providerUsed,
    측정프레임: times.length,
    'ms/frame_중앙값': +med.toFixed(1),
    'ms/frame_평균': +mean.toFixed(1),
    'ms/frame_p90': +p90.toFixed(1),
    추론fps: +(1000 / med).toFixed(1),
    '17분영상_pose패스_예상_분(15fps샘플링)': +projMin.toFixed(1),
  };
}
