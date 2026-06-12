// rally_cut/segments.py + cutlist.py + timecode.py 포팅 (환경 무관 순수 함수).

export function buildSegments(hits, {
  maxGap = 3.0,
  minHits = 3,
  padPre = 1.5,
  padPost = 2.0,
  minDuration = 3.0,
} = {}) {
  if (!hits.length) return [];
  const h = [...hits].sort((a, b) => a - b);
  const clusters = [[h[0]]];
  for (const t of h.slice(1)) {
    const cur = clusters[clusters.length - 1];
    if (t - cur[cur.length - 1] <= maxGap) cur.push(t);
    else clusters.push([t]);
  }
  const segments = [];
  for (const c of clusters) {
    if (c.length < minHits) continue;
    const start = Math.max(0.0, c[0] - padPre);
    const end = c[c.length - 1] + padPost;
    if (end - start >= minDuration) segments.push({ start, end });
  }
  return segments;
}

// timecode.format_tc 포팅 (HH:MM:SS.mmm)
export function formatTc(seconds) {
  if (seconds < 0) seconds = 0.0;
  const totalMs = bankersRound(seconds * 1000);
  const h = Math.trunc(totalMs / 3600000);
  let rem = totalMs % 3600000;
  const m = Math.trunc(rem / 60000);
  rem %= 60000;
  const s = Math.trunc(rem / 1000);
  const ms = rem % 1000;
  const p = (v, w) => String(v).padStart(w, '0');
  return `${p(h, 2)}:${p(m, 2)}:${p(s, 2)}.${p(ms, 3)}`;
}

// 화면 표시용 m:ss
export function shortTc(seconds) {
  const m = Math.trunc(seconds / 60);
  const s = Math.trunc(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Python round() = 짝수 반올림 — cutlist 바이트 동일성을 위해 맞춘다
export function bankersRound(v) {
  const r = Math.round(v);
  return (Math.abs(v % 1) === 0.5 && r % 2 !== 0) ? r - Math.sign(v) : r;
}

// cutlist.write_cutlist 포팅 — segments: [{start, end, keep}]
// keep은 이미 결정된 값(검수 토글 반영). CSV 포맷/컬럼은 Python과 동일.
export function writeCutsCsv(segments) {
  const lines = ['index,start,end,keep,dur'];
  segments.forEach((seg, i) => {
    lines.push([
      i + 1,
      formatTc(seg.start),
      formatTc(seg.end),
      seg.keep ? 'Y' : 'N',
      `${bankersRound(seg.end - seg.start)}s`,
    ].join(','));
  });
  return lines.join('\r\n') + '\r\n'; // csv.writer 기본 개행과 동일
}
