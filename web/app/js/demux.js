// mp4box.js 래퍼 — Blob 슬라이스 스트리밍 파싱 (web/spike/js/demux.js의 적응판:
// 비디오/오디오 추출을 콜백 유무로 선택). moov-at-end 대응은 spike와 동일.
// 전역 MP4Box / DataStream 은 index.html의 mp4box.all.min.js가 제공.

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// AAC AudioSpecificConfig (esds → DecoderSpecificInfo).
// 아이폰 .MOV(QuickTime)는 mp4box가 mp4a 밑 esds를 못 파싱(boxes 비어있음) →
// 그 경우 samplerate/channel_count로 AAC-LC ASC를 합성(아이폰 카메라는 AAC-LC).
const AAC_SR_INDEX = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
                      16000, 12000, 11025, 8000, 7350];
export function audioSpecificConfig(mp4file, trackId) {
  const trak = mp4file.getTrackById(trackId);
  const entry = trak && trak.mdia.minf.stbl.stsd.entries[0];
  // 1) 정규 경로: esds → DecoderSpecificInfo
  try {
    const data = entry.esds.esd.descs[0].descs[0].data;
    if (data && data.length >= 2) return data;
  } catch { /* esds 미파싱 → 합성 폴백 */ }
  // 2) 합성 폴백 (.MOV): AAC-LC(AOT 2) 가정, samplerate/channel_count에서 ASC 2바이트 구성
  try {
    const sr = Math.round(entry.samplerate);
    const ch = entry.channel_count || 2;
    const sfIdx = AAC_SR_INDEX.indexOf(sr);
    if (sfIdx < 0) return null;
    const aot = 2; // AAC-LC
    return new Uint8Array([
      (aot << 3) | (sfIdx >> 1),
      ((sfIdx & 1) << 7) | (ch << 3),
    ]);
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
  const seenV = new Set();
  const seenA = new Set();

  mp4file.onError = (e) => { fatal = new Error('mp4box: ' + e); };
  mp4file.onReady = (i) => { info = i; };
  // moov-at-end(.MOV) + seek 재추출 시 mp4box는 샘플을 뒤섞인 순서로 중복 재방출하고,
  // releaseUsedSamples는 보관 중인 샘플 객체의 .data를 null로 만든다. onSamples 참조를
  // 그대로 큐에 쌓으면 아직 처리 안 한 샘플의 data가 null이 된다. → 방출 즉시 복제+번호
  // 중복제거 후 곧바로 release. (web/spike/js/demux.js와 동일 수정)
  mp4file.onSamples = (id, _user, samples) => {
    let q, seen;
    if (id === vTrackId) { q = vq; seen = seenV; }
    else if (id === aTrackId) { q = aq; seen = seenA; }
    else return;
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
  let skipped = false;

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
        const r = opts.onAudioSample ? await opts.onAudioSample(s) : undefined;
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
    // 전방 점프(mdat 건너뛰기)는 moov 탐색 전(=!started)에만. started 이후에도 점프하면
    // mdat 대부분을 건너뛰어 ~16초분 오디오만 읽고 끝난다(17분 경기 → 첫 16초만 분석).
    if (typeof next === 'number' && next > end && !started) { newOffset = next; skipped = true; }

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
