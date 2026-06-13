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
  const seenV = new Set();
  const seenA = new Set();

  mp4file.onError = (e) => { fatal = new Error('mp4box: ' + e); };
  mp4file.onReady = (i) => { info = i; };
  // 핵심: mp4box는 moov-at-end(.MOV) + seek 재추출 시 샘플을 뒤섞인 순서로 중복
  // 재방출하고, releaseUsedSamples는 보관 중인 샘플 객체의 .data를 null로 만든다.
  // onSamples 참조를 그대로 큐에 쌓으면 아직 처리 안 한 샘플의 data가 null이 된다.
  // → 방출 즉시 data를 복제하고 번호로 중복제거한 뒤 곧바로 release(메모리 회수).
  mp4file.onSamples = (id, _user, samples) => {
    const isV = id === vTrackId;
    const q = isV ? vq : aq;
    const seen = isV ? seenV : seenA;
    for (const s of samples) {
      if (seen.has(s.number) || s.data == null) continue;
      seen.add(s.number);
      q.push({
        number: s.number, cts: s.cts, dts: s.dts, duration: s.duration,
        timescale: s.timescale, is_sync: s.is_sync, size: s.size,
        data: s.data.slice(),
      });
    }
    if (samples.length) mp4file.releaseUsedSamples(id, samples[samples.length - 1].number);
  };

  let offset = 0;
  let started = false;
  let stopped = false;
  let skipped = false; // moov 탐색 중 mdat을 건너뛰었는가

  // 큐 항목은 이미 복제본(onSamples에서 release 완료) — 여기선 소비만 한다.
  const drain = async () => {
    while ((vq.length || aq.length) && !stopped) {
      if (vq.length) {
        const s = vq.shift();
        const r = opts.onVideoSample ? await opts.onVideoSample(s) : undefined;
        if (r === false) { stopped = true; return; }
      }
      if (aq.length) {
        const s = aq.shift();
        if (opts.onAudioSample) await opts.onAudioSample(s);
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
    // 전방 점프(mdat 건너뛰기)는 moov를 찾기 전(=!started)에만 따른다. moov를 찾고
    // 추출을 시작한 뒤에도 점프하면 mdat 대부분을 건너뛰어 ~16초분만 읽고 끝난다.
    // started 이후엔 순차로 읽어 샘플 데이터를 모두 확보한다.
    if (typeof next === 'number' && next > end && !started) { newOffset = next; skipped = true; }

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
