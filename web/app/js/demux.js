// mp4box.js 래퍼 — Blob 슬라이스 스트리밍 파싱 (web/spike/js/demux.js의 적응판:
// 비디오/오디오 추출을 콜백 유무로 선택). moov-at-end 대응은 spike와 동일.
// 전역 MP4Box / DataStream 은 index.html의 mp4box.all.min.js가 제공.

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// AAC AudioSpecificConfig (esds → DecoderSpecificInfo)
export function audioSpecificConfig(mp4file, trackId) {
  try {
    const trak = mp4file.getTrackById(trackId);
    const esds = trak.mdia.minf.stbl.stsd.entries[0].esds;
    return esds.esd.descs[0].descs[0].data || null;
  } catch {
    return null;
  }
}

// opts:
//   chunkSize      슬라이스 크기 (기본 16MB)
//   onReady        async (info, mp4file) => {}
//   onVideoSample  async (sample) => false|void   지정 시에만 비디오 추출
//   onAudioSample  async (sample) => false|void   지정 시에만 오디오 추출
//   onProgress     (읽은 바이트, 전체) => {}
export async function demux(blob, opts) {
  const chunkSize = opts.chunkSize || 16 * 1024 * 1024;
  const mp4file = MP4Box.createFile();
  let info = null;
  let fatal = null;
  let vTrackId = null;
  let aTrackId = null;
  const vq = [];
  const aq = [];

  mp4file.onError = (e) => { fatal = new Error('mp4box: ' + e); };
  mp4file.onReady = (i) => { info = i; };
  mp4file.onSamples = (id, _user, samples) => {
    (id === vTrackId ? vq : aq).push(...samples);
  };

  let offset = 0;
  let started = false;
  let stopped = false;
  let skipped = false;

  const drain = async () => {
    while ((vq.length || aq.length) && !stopped) {
      if (vq.length) {
        const s = vq.shift();
        const r = opts.onVideoSample ? await opts.onVideoSample(s) : undefined;
        mp4file.releaseUsedSamples(vTrackId, s.number);
        if (r === false) { stopped = true; return; }
      }
      if (aq.length) {
        const s = aq.shift();
        const r = opts.onAudioSample ? await opts.onAudioSample(s) : undefined;
        if (aTrackId !== null) mp4file.releaseUsedSamples(aTrackId, s.number);
        if (r === false) { stopped = true; return; }
      }
    }
  };

  while (offset < blob.size && !stopped) {
    if (fatal) throw fatal;
    const end = Math.min(offset + chunkSize, blob.size);
    const buf = await blob.slice(offset, end).arrayBuffer();
    buf.fileStart = offset;
    const next = mp4file.appendBuffer(buf);
    let newOffset = end;
    if (typeof next === 'number' && next > end) { newOffset = next; skipped = true; }

    if (info && !started) {
      if (opts.onVideoSample && info.videoTracks[0]) {
        vTrackId = info.videoTracks[0].id;
        mp4file.setExtractionOptions(vTrackId, null, { nbSamples: 100 });
      }
      if (opts.onAudioSample && info.audioTracks[0]) {
        aTrackId = info.audioTracks[0].id;
        mp4file.setExtractionOptions(aTrackId, null, { nbSamples: 500 });
      }
      if (opts.onReady) await opts.onReady(info, mp4file);
      mp4file.start();
      started = true;
      if (skipped) {
        const sk = mp4file.seek(0, true);
        if (sk && typeof sk.offset === 'number') newOffset = sk.offset;
      }
    }

    await drain();
    if (opts.onProgress) opts.onProgress(Math.min(newOffset, blob.size), blob.size);
    offset = newOffset;
  }

  if (!stopped) {
    mp4file.flush();
    await drain();
  }
  mp4file.stop();
  if (fatal) throw fatal;
  if (!info) throw new Error('mp4 파싱 실패 (moov 미발견)');
  return info;
}
