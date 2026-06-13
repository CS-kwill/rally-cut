// rally-cut 웹앱 V0.5 — 분석(오디오 온셋·군집) + 검수(탭 점프·keep 토글) + cuts.csv 내보내기.
// 컷 영상 출력은 W1 후속(스파이크 ③ 검증 후). 기존 파라미터 고정 = Python CLI(audio-only)와 동일.
import { extractAudio } from './audio.js';
import { detectHits } from './dsp.js';
import { buildSegments, writeCutsCsv, formatTc, shortTc } from './segments.js';

const PARAMS = { maxGap: 3.0, minHits: 3, padPre: 1.5, padPost: 2.0, minDuration: 3.0 };
const MIN_KEEP = 8.0; // CLI audio-only 경로의 --min-keep-duration 기본값과 동일

const $ = (id) => document.getElementById(id);
let videoFile = null;
let segments = []; // {start, end, keep}
let hits = [];
let playUntil = null;
let activeRow = -1;

function status(msg) { $('status').textContent = msg; }

// ---------- 분석 ----------
async function analyze() {
  $('analyze').disabled = true;
  try {
    status('오디오 추출 중…');
    const x = await extractAudio(videoFile, {
      log: (m) => status(m),
      onProgress: (done, total) =>
        status(`오디오 추출 중… ${Math.round(100 * done / total)}%`),
    });
    status('타구음 검출 중…');
    await new Promise((r) => setTimeout(r, 30)); // UI 갱신 양보
    hits = detectHits(x);
    status(`타격 ${hits.length}개 — 구간 묶는 중…`);
    const segs = buildSegments(hits, PARAMS);
    segments = segs.map((s) => ({ ...s, keep: s.end - s.start >= MIN_KEEP }));
    renderList();
    $('exportBar').hidden = false;
    summarize(`타격 ${hits.length}개 → 구간 ${segments.length}개`);
    status('분석 완료. 행을 탭하면 해당 구간을 재생합니다.');
  } catch (e) {
    console.error(e);
    status('분석 실패: ' + e.message);
  } finally {
    $('analyze').disabled = false;
  }
}

function summarize(prefix) {
  const kept = segments.filter((s) => s.keep);
  const kd = kept.reduce((a, s) => a + s.end - s.start, 0);
  const dur = $('video').duration || 0;
  $('summary').textContent =
    `${prefix ? prefix + ' / ' : ''}keep ${kept.length}개 ${shortTc(kd)}`
    + (dur ? ` (원본 ${shortTc(dur)}, ${Math.round(100 * (1 - kd / dur))}% 제거)` : '');
}

// ---------- 목록 ----------
function renderList() {
  const ul = $('list');
  ul.innerHTML = '';
  segments.forEach((seg, i) => {
    const li = document.createElement('li');
    li.className = seg.keep ? 'keep' : 'drop';
    li.dataset.i = i;

    const play = document.createElement('div');
    play.className = 'cell';
    play.innerHTML = `<b>#${i + 1}</b> ${shortTc(seg.start)}–${shortTc(seg.end)}`
      + `<span class="dur">${Math.round(seg.end - seg.start)}s</span>`;
    play.addEventListener('click', () => jumpPlay(i));

    const btn = document.createElement('button');
    btn.textContent = seg.keep ? 'KEEP' : 'CUT';
    btn.className = 'toggle';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      seg.keep = !seg.keep;
      li.className = (seg.keep ? 'keep' : 'drop') + (i === activeRow ? ' active' : '');
      btn.textContent = seg.keep ? 'KEEP' : 'CUT';
      summarize('');
    });

    li.append(play, btn);
    ul.appendChild(li);
  });
}

function jumpPlay(i) {
  const v = $('video');
  const seg = segments[i];
  if (activeRow >= 0) {
    const prev = $('list').children[activeRow];
    if (prev) prev.classList.remove('active');
  }
  activeRow = i;
  $('list').children[i].classList.add('active');
  v.currentTime = seg.start;
  playUntil = seg.end;
  v.play();
}

$('video').addEventListener('timeupdate', () => {
  const v = $('video');
  if (playUntil !== null && v.currentTime >= playUntil) {
    v.pause();
    playUntil = null;
  }
});

$('analyze').addEventListener('click', analyze);

// ---------- 내보내기 ----------
function csvBlob() {
  return new Blob([writeCutsCsv(segments)], { type: 'text/csv' });
}

function csvName() {
  return 'cuts_' + (videoFile.name.replace(/\.[^.]+$/, '') || 'video') + '.csv';
}

$('dl').addEventListener('click', () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(csvBlob());
  a.download = csvName();
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
});

$('share').addEventListener('click', async () => {
  const f = new File([csvBlob()], csvName(), { type: 'text/csv' });
  if (navigator.canShare && navigator.canShare({ files: [f] })) {
    try { await navigator.share({ files: [f] }); } catch { /* 사용자 취소 */ }
  } else {
    status('이 환경은 공유 미지원(HTTP LAN 등) — 다운로드/복사를 사용하세요.');
  }
});

$('copy').addEventListener('click', async () => {
  const text = writeCutsCsv(segments);
  try {
    await navigator.clipboard.writeText(text);
    status('cuts.csv 내용을 클립보드에 복사했습니다.');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    status('cuts.csv 내용을 클립보드에 복사했습니다(폴백).');
  }
});

// ---------- 파일 선택 ----------
$('file').addEventListener('change', (e) => {
  videoFile = e.target.files[0] || null;
  if (!videoFile) return;
  $('video').src = URL.createObjectURL(videoFile);
  $('video').hidden = false;
  $('analyze').disabled = false;
  segments = [];
  $('list').innerHTML = '';
  $('exportBar').hidden = true;
  $('summary').textContent = '';
  status(`${videoFile.name} (${(videoFile.size / 1048576).toFixed(0)}MB) — [분석]을 누르세요.`);
});

window.addEventListener('error', (e) => status('오류: ' + e.message));
window.addEventListener('unhandledrejection',
  (e) => status('오류: ' + (e.reason && e.reason.message || e.reason)));

status('영상 파일을 선택하세요.');
