// mp4box.js 래퍼 — Blob을 슬라이스 스트리밍으로 파싱한다.
// moov가 파일 끝에 있는 아이폰 .MOV도 appendBuffer가 돌려주는
// "다음에 읽을 오프셋"을 따라가 mdat을 건너뛰고 빠르게 onReady에 도달한 뒤,
// seek(0)으로 되돌아와 샘플을 추출한다.
// 전역 MP4Box / DataStream 은 index.html의 mp4box.all.min.js가 제공.

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 비디오 트랙의 WebCodecs description (avcC/hvcC 본문, 박스 헤더 8바이트 제외)
export function trackDescription(mp4file, trackId) {
  const trak = mp4file.getTrackById(trackId);
  for (const entry of trak.mdia.minf.stbl.stsd.entries) {
    const box = entry.avcC || entry.hvcC || entry.vpcC || entry.av1C;
    if (box) {
      const ds = new DataStream(undefined, 0, DataStream.BIG_ENDIAN);
      box.write(ds);
      return new Uint8Array(ds.buffer, 8);
    }
  }
  return null;
}

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
//   chunkSize  슬라이스 크기 (기본 16MB)
//   audio      true면 오디오 트랙도 추출
//   onReady    async (info, mp4file) => {}
//   onVideoSample  async (sample) => false|void   false 반환 시 중단
//   onAudioSample  async (sample) => {}
// 반환: mp4box info (트랙 메타)
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
  let skipped = false; // moov 탐색 중 mdat을 건너뛰었는가

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
        if (opts.onAudioSample) await opts.onAudioSample(s);
        if (aTrackId !== null) mp4file.releaseUsedSamples(aTrackId, s.number);
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
      const vt = info.videoTracks[0];
      if (!vt) throw new Error('비디오 트랙 없음');
      vTrackId = vt.id;
      mp4file.setExtractionOptions(vt.id, null, { nbSamples: 100 });
      if (opts.audio && info.audioTracks[0]) {
        aTrackId = info.audioTracks[0].id;
        mp4file.setExtractionOptions(aTrackId, null, { nbSamples: 200 });
      }
      if (opts.onReady) await opts.onReady(info, mp4file);
      mp4file.start();
      started = true;
      if (skipped) {
        // mdat을 건너뛰었으므로 샘플 데이터 위치로 복귀
        const sk = mp4file.seek(0, true);
        if (sk && typeof sk.offset === 'number') newOffset = sk.offset;
      }
    }

    await drain();
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
