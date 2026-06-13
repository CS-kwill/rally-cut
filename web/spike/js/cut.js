// 실측 ③ — 키프레임 스냅 컷 + 재먹싱 (재인코딩 없음)
// mp4box.js로 디먹스 → 요청 시작점 직전 키프레임부터 샘플 수집 → mediabunny로 플랫 mp4 작성.
// mp4-muxer는 raw API가 PTS/DTS를 분리 못 해 B-프레임 HEVC를 못 먹싱했다(W0 스파이크에서
// "DTS went from 0 to -33334"로 확인). mediabunny는 EncodedPacket이 timestamp(표시,초)와
// sequenceNumber(디코드 순서)를 분리해 받아 B-프레임을 정상 처리한다.
// 오디오 cfg 추출 실패(.MOV esds 경로 차이) 시 비디오 단독으로 폴백하고 로그에 남긴다.
import { demux, trackDescription, audioSpecificConfig } from './demux.js';

export async function snapCut(file, { startSec = 5, endSec = 20, log }) {
  const mb = await import('https://cdn.jsdelivr.net/npm/mediabunny@1/+esm');

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
  const codecPrefix = vTrack.codec.split('.')[0];
  const vCodec = /^hvc|^hev/.test(codecPrefix) ? 'hevc' : /^avc/.test(codecPrefix) ? 'avc' : null;
  if (!vCodec) throw new Error('미지원 비디오 코덱: ' + vTrack.codec);

  const audioOk = !!(aTrack && aacCfg && /mp4a/.test(aTrack.codec));
  const tMux = performance.now();

  // mediabunny: EncodedPacket(data, type, timestamp(초,표시=CTS), duration(초), sequenceNumber(디코드순서)).
  // 샘플은 디코드 순서로 add하고 sequenceNumber=i로 디코드 순서를 명시 → B-프레임도 정상.
  const buildMux = async (withAudio) => {
    const target = new mb.BufferTarget();
    const output = new mb.Output({
      format: new mb.Mp4OutputFormat({ fastStart: 'in-memory' }),
      target,
    });
    const vSrc = new mb.EncodedVideoPacketSource(vCodec);
    output.addVideoTrack(vSrc);
    let aSrc = null;
    if (withAudio) {
      aSrc = new mb.EncodedAudioPacketSource('aac');
      output.addAudioTrack(aSrc);
    }
    await output.start();

    for (let i = 0; i < vSamples.length; i++) {
      const s = vSamples[i];
      await vSrc.add(
        new mb.EncodedPacket(
          s.data, s.is_sync ? 'key' : 'delta',
          s.cts / s.timescale - snapStart,
          s.duration / s.timescale,
          i,
        ),
        i === 0 ? { decoderConfig: {
          codec: vTrack.codec,
          codedWidth: vTrack.video.width,
          codedHeight: vTrack.video.height,
          ...(desc ? { description: desc } : {}),
        } } : undefined,
      );
    }

    if (withAudio) {
      let ai = 0;
      for (const s of aSamples) {
        const ts = s.cts / s.timescale - snapStart;
        if (ts < 0) continue; // mediabunny는 음수 타임스탬프를 거부 — 컷 시작 이전 오디오는 버림
        await aSrc.add(
          new mb.EncodedPacket(s.data, 'key', ts, s.duration / s.timescale, ai),
          ai === 0 ? { decoderConfig: {
            // .MOV는 aTrack.codec이 'mp4a'(프로필 없음) — mediabunny는 유효 AAC 코덱
            // 문자열을 요구하므로 합성 ASC의 AOT로 'mp4a.40.<aot>' 구성.
            codec: aTrack.codec.includes('.') ? aTrack.codec : 'mp4a.40.' + (aacCfg[0] >> 3),
            sampleRate: aTrack.audio.sample_rate,
            numberOfChannels: aTrack.audio.channel_count,
            ...(aacCfg ? { description: aacCfg } : {}),
          } } : undefined,
        );
        ai++;
      }
    }

    await output.finalize();
    return target.buffer;
  };

  let buffer;
  let audioIncluded = audioOk;
  try {
    buffer = await buildMux(audioOk);
  } catch (e) {
    log('오디오 포함 먹싱 실패(' + e.message + ') → 비디오 단독 재시도');
    audioIncluded = false;
    buffer = await buildMux(false);
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
