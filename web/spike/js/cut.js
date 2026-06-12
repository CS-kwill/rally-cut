// 실측 ③ — 키프레임 스냅 컷 + 재먹싱 (재인코딩 없음)
// mp4box.js로 디먹스 → 요청 시작점 직전 키프레임부터 샘플 수집 → mp4-muxer로 플랫 mp4 작성.
// b-프레임 재정렬·오디오 esds 추출 등은 스파이크에서 실패 자체가 측정 데이터다 —
// 오디오 실패 시 비디오 단독으로 폴백하고 로그에 남긴다.
import { demux, trackDescription, audioSpecificConfig } from './demux.js';

export async function snapCut(file, { startSec = 5, endSec = 20, log }) {
  const mm = await import('https://cdn.jsdelivr.net/npm/mp4-muxer/+esm');

  let vTrack = null;
  let aTrack = null;
  let desc = null;
  let aacCfg = null;
  const vSamples = [];
  const aSamples = [];
  let gop = [];
  let collecting = false;

  await demux(file, {
    audio: true,
    onReady: async (info, mp4file) => {
      vTrack = info.videoTracks[0];
      aTrack = info.audioTracks[0] || null;
      desc = trackDescription(mp4file, vTrack.id);
      if (aTrack) aacCfg = audioSpecificConfig(mp4file, aTrack.id);
      log(`video=${vTrack.codec}, audio=${aTrack ? aTrack.codec : '없음'}, AAC cfg=${aacCfg ? aacCfg.length + 'B' : '추출실패'}`);
    },
    onVideoSample: async (s) => {
      const t = s.cts / s.timescale;
      const copy = { cts: s.cts, duration: s.duration, timescale: s.timescale, is_sync: s.is_sync, data: s.data.slice() };
      if (!collecting) {
        if (s.is_sync) gop = [];
        gop.push(copy);
        if (t >= startSec) { collecting = true; vSamples.push(...gop); gop = []; }
      } else if (t <= endSec + 0.5) {
        vSamples.push(copy);
      } else {
        return false;
      }
    },
    onAudioSample: async (s) => {
      const t = s.cts / s.timescale;
      if (t >= startSec - 12 && t <= endSec + 0.5) {
        aSamples.push({ cts: s.cts, duration: s.duration, timescale: s.timescale, data: s.data.slice() });
      }
    },
  });

  if (!vSamples.length) throw new Error('수집된 비디오 샘플 없음 — start/end 확인');

  const snapStart = Math.min(...vSamples.map((s) => s.cts / s.timescale));
  const t0us = Math.round(1e6 * snapStart);
  const codecPrefix = vTrack.codec.split('.')[0];
  const vCodec = /^hvc|^hev/.test(codecPrefix) ? 'hevc' : /^avc/.test(codecPrefix) ? 'avc' : null;
  if (!vCodec) throw new Error('mp4-muxer 미지원 비디오 코덱: ' + vTrack.codec);

  const audioOk = !!(aTrack && aacCfg && /mp4a/.test(aTrack.codec));
  const tMux = performance.now();

  const buildMux = (withAudio) => {
    const target = new mm.ArrayBufferTarget();
    const muxer = new mm.Muxer({
      target,
      video: { codec: vCodec, width: vTrack.video.width, height: vTrack.video.height },
      audio: withAudio ? {
        codec: 'aac',
        sampleRate: aTrack.audio.sample_rate,
        numberOfChannels: aTrack.audio.channel_count,
      } : undefined,
      fastStart: 'in-memory',
    });
    vSamples.forEach((s, i) => {
      muxer.addVideoChunkRaw(
        s.data, s.is_sync ? 'key' : 'delta',
        Math.max(0, Math.round((1e6 * s.cts) / s.timescale) - t0us),
        Math.round((1e6 * s.duration) / s.timescale),
        i === 0 && desc ? { decoderConfig: { codec: vTrack.codec, description: desc } } : undefined,
      );
    });
    if (withAudio) {
      let first = true;
      for (const s of aSamples) {
        const ts = Math.round((1e6 * s.cts) / s.timescale) - t0us;
        if (ts < 0) continue;
        muxer.addAudioChunkRaw(
          s.data, 'key', ts,
          Math.round((1e6 * s.duration) / s.timescale),
          first ? { decoderConfig: { codec: aTrack.codec, description: aacCfg } } : undefined,
        );
        first = false;
      }
    }
    muxer.finalize();
    return target.buffer;
  };

  let buffer;
  let audioIncluded = audioOk;
  try {
    buffer = buildMux(audioOk);
  } catch (e) {
    log('오디오 포함 먹싱 실패(' + e.message + ') → 비디오 단독 재시도');
    audioIncluded = false;
    buffer = buildMux(false);
  }
  const muxMs = performance.now() - tMux;

  const blob = new Blob([buffer], { type: 'video/mp4' });
  return {
    result: {
      요청구간_s: `${startSec}~${endSec}`,
      스냅시작_s: +snapStart.toFixed(2),
      스냅오차_s: +(startSec - snapStart).toFixed(2),
      비디오샘플: vSamples.length,
      오디오샘플: audioIncluded ? aSamples.length : 0,
      오디오포함: audioIncluded,
      출력_MB: +(blob.size / 1048576).toFixed(1),
      먹싱_ms: +muxMs.toFixed(0),
    },
    blob,
  };
}
