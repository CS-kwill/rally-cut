// 영상 파일 → 22050Hz mono Float32Array (rally_cut/audio.extract_audio와 동일 규약).
// 경로: mp4box로 AAC 트랙만 추출 → ADTS 래핑 → decodeAudioData(22050 컨텍스트가
// 리샘플) → 채널 평균. 1GB 파일도 비디오 트랙을 메모리에 들이지 않는다.
import { demux, audioSpecificConfig } from './demux.js';

const TARGET_SR = 22050;

function adtsHeader(frameLen, sfIdx, chCfg, profile) {
  const len = frameLen + 7;
  return [
    0xFF, 0xF1,
    ((profile - 1) << 6) | (sfIdx << 2) | (chCfg >> 2),
    ((chCfg & 3) << 6) | ((len >> 11) & 0x3),
    (len >> 3) & 0xFF,
    ((len & 7) << 5) | 0x1F,
    0xFC,
  ];
}

async function aacToAdts(file, { log, onProgress }) {
  const parts = [];
  let total = 0;
  let cfg = null;
  let codec = '';
  await demux(file, {
    onReady: async (info, mp4file) => {
      const at = info.audioTracks[0];
      if (!at) throw new Error('오디오 트랙 없음');
      codec = at.codec;
      if (!/^mp4a/.test(at.codec)) throw new Error('AAC 아님: ' + at.codec);
      const asc = audioSpecificConfig(mp4file, at.id);
      if (!asc || asc.length < 2) throw new Error('AudioSpecificConfig 추출 실패');
      cfg = {
        aot: asc[0] >> 3,
        sfIdx: ((asc[0] & 7) << 1) | (asc[1] >> 7),
        chCfg: (asc[1] >> 3) & 0xF,
      };
      log(`오디오 트랙: ${codec} (AOT ${cfg.aot}, sfIdx ${cfg.sfIdx}, ch ${cfg.chCfg})`);
    },
    onAudioSample: async (s) => {
      parts.push(adtsHeader(s.data.length, cfg.sfIdx, cfg.chCfg,
                            cfg.aot === 5 ? 2 : cfg.aot)); // HE-AAC은 LC로 시그널
      parts.push(s.data.slice());
      total += s.data.length + 7;
    },
    onProgress,
  });
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) { out.set(p, off); off += p.length; }
  return out.buffer;
}

function toMono22050(audioBuffer) {
  // ffmpeg -ac 1 과 동일: 채널 평균
  const n = audioBuffer.length;
  const out = new Float32Array(n);
  for (let c = 0; c < audioBuffer.numberOfChannels; c++) {
    const ch = audioBuffer.getChannelData(c);
    for (let i = 0; i < n; i++) out[i] += ch[i];
  }
  const k = 1 / audioBuffer.numberOfChannels;
  for (let i = 0; i < n; i++) out[i] = Math.fround(out[i] * k);
  return out;
}

export async function extractAudio(file, { log, onProgress } = {}) {
  log = log || (() => {});
  const octx = new OfflineAudioContext(1, 1, TARGET_SR);
  let encoded = null;
  const isMp4 = /\.(mp4|mov|m4v|m4a)$/i.test(file.name) || /mp4|quicktime/.test(file.type);
  if (isMp4) {
    try {
      encoded = await aacToAdts(file, { log, onProgress });
      log(`AAC 추출 완료 (${(encoded.byteLength / 1048576).toFixed(1)}MB) — 디코딩…`);
    } catch (e) {
      log(`mp4 오디오 추출 실패(${e.message}) — 파일 통째 디코딩 폴백`);
    }
  }
  if (!encoded) {
    if (file.size > 400 * 1048576) {
      throw new Error('mp4 추출 실패 + 파일이 400MB 초과 — 통째 디코딩 불가');
    }
    encoded = await file.arrayBuffer();
  }
  const abuf = await octx.decodeAudioData(encoded);
  log(`디코딩 완료: ${abuf.duration.toFixed(1)}s @ ${abuf.sampleRate}Hz ${abuf.numberOfChannels}ch`);
  if (abuf.sampleRate !== TARGET_SR) {
    // 사파리가 컨텍스트 레이트로 리샘플하지 않은 경우: Offline 렌더로 강제 리샘플
    log('컨텍스트 리샘플 미적용 — OfflineAudioContext 렌더로 재샘플…');
    const o2 = new OfflineAudioContext(1, Math.ceil(abuf.duration * TARGET_SR), TARGET_SR);
    const src = o2.createBufferSource();
    src.buffer = abuf;
    src.connect(o2.destination);
    src.start();
    const r = await o2.startRendering();
    return r.getChannelData(0).slice();
  }
  return toMono22050(abuf);
}
