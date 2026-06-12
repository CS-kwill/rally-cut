// W0 스파이크 메인 — 파일 선택, 실측 4종 실행, 보고서 수집/복사
import { decodeThroughput } from './decode.js';
import { poseThroughput } from './pose.js';
import { snapCut } from './cut.js';

const $ = (id) => document.getElementById(id);
const report = { 기기: {}, 실측: {} };
let videoFile = null;
let cutBlob = null;

// ---------- 로그/보고 ----------
function log(msg) {
  const el = $('log');
  el.textContent += msg + '\n';
  el.scrollTop = el.scrollHeight;
}

function setResult(key, value) {
  report.실측[key] = value;
  $('report').textContent = JSON.stringify(report, null, 2);
}

async function deviceInfo() {
  const d = {
    UA: navigator.userAgent,
    코어: navigator.hardwareConcurrency || null,
    화면: `${screen.width}x${screen.height}@${devicePixelRatio}x`,
    보안컨텍스트: window.isSecureContext,
    WebCodecs: 'VideoDecoder' in window,
    VideoEncoder: 'VideoEncoder' in window,
    WebGPU: !!navigator.gpu,
    OffscreenCanvas: 'OffscreenCanvas' in window,
  };
  try {
    const est = await navigator.storage.estimate();
    d.저장소할당_GB = +((est.quota || 0) / 2 ** 30).toFixed(1);
  } catch { /* 미지원 */ }
  report.기기 = d;
  $('report').textContent = JSON.stringify(report, null, 2);
  if (!d.보안컨텍스트) log('⚠ 보안 컨텍스트 아님 — WebCodecs 등이 비활성화됩니다. HTTPS 또는 localhost로 여세요.');
  if (!d.WebCodecs) log('⚠ 이 브라우저는 WebCodecs를 지원하지 않습니다.');
}

// ---------- 실측 ④ Blob 스트리밍 ----------
async function blobStream(file, chunkMB) {
  const cs = chunkMB * 1048576;
  let read = 0;
  let maxLat = 0;
  const t0 = performance.now();
  let lastLog = t0;
  for (let off = 0; off < file.size; off += cs) {
    const t = performance.now();
    const buf = await file.slice(off, Math.min(off + cs, file.size)).arrayBuffer();
    read += buf.byteLength;
    const lat = performance.now() - t;
    if (lat > maxLat) maxLat = lat;
    if (performance.now() - lastLog > 2000) {
      log(`…${(read / 1048576).toFixed(0)}MB 읽음`);
      lastLog = performance.now();
    }
  }
  const sec = (performance.now() - t0) / 1000;
  return {
    파일_MB: +(file.size / 1048576).toFixed(1),
    소요_s: +sec.toFixed(1),
    'MB/s': +(read / 1048576 / sec).toFixed(1),
    최대청크지연_ms: +maxLat.toFixed(0),
    완주: read === file.size,
  };
}

// ---------- 실행 래퍼 ----------
async function runTest(btn, key, fn) {
  if (!videoFile && key !== '기기') { log('먼저 영상 파일을 선택하세요.'); return; }
  btn.disabled = true;
  const t0 = performance.now();
  log(`\n===== ${key} 시작 =====`);
  try {
    const r = await fn();
    setResult(key, r);
    log(`${key} 완료 (${((performance.now() - t0) / 1000).toFixed(1)}s)`);
  } catch (e) {
    console.error(e);
    setResult(key, { 오류: e.message });
    log(`${key} 실패: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

// ---------- 배선 ----------
$('file').addEventListener('change', (e) => {
  videoFile = e.target.files[0] || null;
  if (videoFile) {
    log(`파일: ${videoFile.name} (${(videoFile.size / 1048576).toFixed(1)}MB)`);
    report.파일 = { 이름: videoFile.name, MB: +(videoFile.size / 1048576).toFixed(1) };
    document.querySelectorAll('button.test').forEach((b) => { b.disabled = false; });
  }
});

$('t1').addEventListener('click', () =>
  runTest($('t1'), '①디코딩처리량', () =>
    decodeThroughput(videoFile, { seconds: +$('t1sec').value || 0, log })));

$('t2mp').addEventListener('click', () =>
  runTest($('t2mp'), '②pose_MediaPipe', () =>
    poseThroughput(videoFile, { engine: 'mediapipe', maxFrames: +$('t2n').value, stride: +$('t2stride').value, log })));

$('t2wasm').addEventListener('click', () =>
  runTest($('t2wasm'), '②pose_ONNX_wasm', () =>
    poseThroughput(videoFile, { engine: 'onnx-wasm', maxFrames: +$('t2n').value, stride: +$('t2stride').value, log })));

$('t2gpu').addEventListener('click', () =>
  runTest($('t2gpu'), '②pose_ONNX_webgpu', () =>
    poseThroughput(videoFile, { engine: 'onnx-webgpu', maxFrames: +$('t2n').value, stride: +$('t2stride').value, log })));

$('t3').addEventListener('click', () =>
  runTest($('t3'), '③스냅컷', async () => {
    const { result, blob } = await snapCut(videoFile, {
      startSec: +$('t3start').value, endSec: +$('t3end').value, log,
    });
    cutBlob = blob;
    $('t3share').disabled = false;
    $('t3dl').disabled = false;
    log('컷 생성 완료 — [공유/저장] 버튼으로 카메라롤 저장을 테스트하세요.');
    return result;
  }));

$('t3share').addEventListener('click', async () => {
  if (!cutBlob) return;
  const f = new File([cutBlob], 'rally-cut-spike.mp4', { type: 'video/mp4' });
  try {
    if (navigator.canShare && navigator.canShare({ files: [f] })) {
      await navigator.share({ files: [f] });
      report.실측['③스냅컷'].공유저장 = '성공(시트 표시)';
    } else {
      report.실측['③스냅컷'].공유저장 = 'navigator.share 파일 미지원';
      log('이 브라우저는 파일 공유를 지원하지 않습니다 — 다운로드 버튼을 사용하세요.');
    }
  } catch (e) {
    report.실측['③스냅컷'].공유저장 = '실패/취소: ' + e.message;
  }
  $('report').textContent = JSON.stringify(report, null, 2);
});

$('t3dl').addEventListener('click', () => {
  if (!cutBlob) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(cutBlob);
  a.download = 'rally-cut-spike.mp4';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
});

$('t4').addEventListener('click', () =>
  runTest($('t4'), '④Blob스트리밍', () => blobStream(videoFile, +$('t4mb').value || 16)));

$('copy').addEventListener('click', async () => {
  const text = `=== rally-cut W0 스파이크 보고 (${new Date().toISOString()}) ===\n`
    + JSON.stringify(report, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    log('보고서를 클립보드에 복사했습니다.');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    log('보고서를 클립보드에 복사했습니다(폴백).');
  }
});

window.addEventListener('error', (e) => log('전역 오류: ' + e.message));
window.addEventListener('unhandledrejection', (e) => log('비동기 오류: ' + (e.reason && e.reason.message || e.reason)));

deviceInfo();
log('영상 파일을 선택한 뒤 각 실측 버튼을 누르세요. 결과는 하단 보고서에 누적됩니다.');
