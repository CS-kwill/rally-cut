// Python 대조 테스트: WAV(pcm_s16le) → detectHits/buildSegments → JSON 출력.
// 사용: node parity.mjs <audio.wav>
// 비교 상대: rally_cut의 detect_hits + build_segments (Python 참조 구현)
import { readFileSync } from 'node:fs';
import { detectHits, SR } from '../js/dsp.js';
import { buildSegments } from '../js/segments.js';

function readWav(path) {
  const buf = readFileSync(path);
  if (buf.toString('ascii', 0, 4) !== 'RIFF') throw new Error('RIFF 아님');
  let off = 12;
  let fmt = null;
  let data = null;
  while (off + 8 <= buf.length) {
    const id = buf.toString('ascii', off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === 'fmt ') {
      fmt = {
        format: buf.readUInt16LE(off + 8),
        channels: buf.readUInt16LE(off + 10),
        sampleRate: buf.readUInt32LE(off + 12),
        bits: buf.readUInt16LE(off + 22),
      };
    } else if (id === 'data') {
      data = buf.subarray(off + 8, off + 8 + size);
    }
    off += 8 + size + (size % 2);
  }
  if (!fmt || !data) throw new Error('fmt/data 청크 없음');
  if (fmt.format !== 1 || fmt.bits !== 16) throw new Error('pcm_s16le만 지원');
  const n = data.length >> 1;
  const ch = fmt.channels;
  const out = new Float32Array(Math.trunc(n / ch));
  // scipy wavfile 경로와 동일: int16 평균(다채널) 후 /32767
  for (let i = 0; i < out.length; i++) {
    let acc = 0;
    for (let c = 0; c < ch; c++) acc += data.readInt16LE(2 * (i * ch + c));
    out[i] = Math.fround((acc / ch) / 32767);
  }
  return { sr: fmt.sampleRate, x: out };
}

const { sr, x } = readWav(process.argv[2]);
if (sr !== SR) throw new Error(`샘플레이트 ${sr} != ${SR}`);
const hits = detectHits(x);
const segs = buildSegments(hits);
console.log(JSON.stringify({
  n_hits: hits.length,
  hits: hits.map((t) => +t.toFixed(4)),
  segments: segs.map((s) => [+s.start.toFixed(3), +s.end.toFixed(3)]),
}));
