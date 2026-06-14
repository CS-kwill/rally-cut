// rally-cut 스윙 라벨러 — 오디오 온셋으로 후보 클립 추출 → 클립마다 동작 클래스 선택.
// 출력 labels.csv(id,t,label)는 scripts/swing_label_collect.py에 넣어 pose 추출+라벨 합류.
// 기존 웹앱(web/app) 분석 코드 재사용(audio/dsp/segments) — 같은 오디오 파이프라인.
import { extractAudio } from '../../app/js/audio.js?v=2';
import { detectHits } from '../../app/js/dsp.js?v=2';
import { shortTc } from '../../app/js/segments.js?v=2';

const BUILD = 'v1';
// 클래스 (rally_cut/labeling.SWING_LABEL_CLASSES와 동일). skip=라벨 해제.
const CLASSES = [
  { key: 'serve', ko: '서브' },
  { key: 'serve_under', ko: '언더' },
  { key: 'fh', ko: 'FH' },
  { key: 'bh', ko: 'BH' },
  { key: 'volley', ko: '발리' },
  { key: 'nostroke', ko: '무(노스윙)' },
];
const HALF = 0.8; // 후보 클립 반폭(초)

const $ = (id) => document.getElementById(id);
let videoFile = null;
let cands = [];        // {t}
let labels = {};       // id -> class
let playUntil = null;
let activeRow = -1;

function status(m) { $('status').textContent = m; }

// 오디오 온셋 → 후보 시각 (collect.py auto와 동일: 구간 첫타격=서브후보 + 중간 샘플)
function candidatesFromHits(hits, { maxGap = 3.0, minHits = 2 } = {}) {
  const h = [...hits].sort((a, b) => a - b);
  if (!h.length) return [];
  const clusters = [[h[0]]];
  for (const t of h.slice(1)) {
    const cur = clusters[clusters.length - 1];
    if (t - cur[cur.length - 1] <= maxGap) cur.push(t);
    else clusters.push([t]);
  }
  const cand = [];
  for (const c of clusters) {
    if (c.length < minHits) continue;
    cand.push(c[0]);
    for (let i = 1; i < c.length; i += 3) cand.push(c[i]);
  }
  cand.sort((a, b) => a - b);
  const out = [];
  for (const t of cand) if (!out.length || t - out[out.length - 1] > 1.0) out.push(t);
  return out;
}

async function analyze() {
  $('analyze').disabled = true;
  try {
    status('오디오 추출 중…');
    const x = await extractAudio(videoFile, {
      log: (m) => status(m),
      onProgress: (d, t) => status(`오디오 추출 중… ${Math.round(100 * d / t)}%`),
    });
    status('타구음 검출 중…');
    await new Promise((r) => setTimeout(r, 30));
    const hits = detectHits(x);
    const times = candidatesFromHits(hits);
    cands = times.map((t, i) => ({ id: String(i + 1).padStart(4, '0'), t }));
    labels = {};
    renderList();
    $('exportBar').hidden = false;
    summarize();
    status('클립을 탭해 재생하고, 아래 버튼으로 동작을 선택하세요.');
  } catch (e) {
    console.error(e);
    status('추출 실패: ' + e.message);
  } finally {
    $('analyze').disabled = false;
  }
}

function summarize() {
  const done = Object.keys(labels).length;
  const counts = {};
  for (const v of Object.values(labels)) counts[v] = (counts[v] || 0) + 1;
  const cs = CLASSES.map((c) => counts[c.key] ? `${c.ko}${counts[c.key]}` : null)
    .filter(Boolean).join(' ');
  $('summary').textContent = `후보 ${cands.length}개 · 라벨 ${done}개${cs ? ' (' + cs + ')' : ''}`;
}

function renderList() {
  const ul = $('list');
  ul.innerHTML = '';
  cands.forEach((c, i) => {
    const li = document.createElement('li');
    li.dataset.i = i;

    const clip = document.createElement('div');
    clip.className = 'clip';
    clip.innerHTML = `<span>▶ #${i + 1}</span> ${shortTc(c.t)}`
      + `<span class="dur">${(2 * HALF).toFixed(1)}s</span>`;
    clip.addEventListener('click', () => jumpPlay(i));

    const cls = document.createElement('div');
    cls.className = 'cls';
    CLASSES.forEach((cl) => {
      const b = document.createElement('button');
      b.textContent = cl.ko;
      if (labels[c.id] === cl.key) b.classList.add('sel');
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        if (labels[c.id] === cl.key) delete labels[c.id]; // 같은 버튼 재탭=해제
        else labels[c.id] = cl.key;
        li.classList.toggle('done', !!labels[c.id]);
        cls.querySelectorAll('button').forEach((x) => x.classList.remove('sel'));
        if (labels[c.id]) b.classList.add('sel');
        summarize();
      });
      cls.append(b);
    });

    li.classList.toggle('done', !!labels[c.id]);
    li.append(clip, cls);
    ul.appendChild(li);
  });
}

function jumpPlay(i) {
  const v = $('video');
  if (activeRow >= 0) $('list').children[activeRow]?.classList.remove('active');
  activeRow = i;
  $('list').children[i].classList.add('active');
  const t = cands[i].t;
  v.currentTime = Math.max(0, t - HALF);
  playUntil = t + HALF;
  v.play();
}

$('video').addEventListener('timeupdate', () => {
  const v = $('video');
  if (playUntil !== null && v.currentTime >= playUntil) { v.pause(); playUntil = null; }
});

$('analyze').addEventListener('click', analyze);

// ---- 내보내기 ----
function csvText() {
  const lines = ['id,t,label'];
  for (const c of cands) if (labels[c.id]) lines.push(`${c.id},${c.t.toFixed(2)},${labels[c.id]}`);
  return lines.join('\r\n') + '\r\n';
}
function csvBlob() { return new Blob([csvText()], { type: 'text/csv' }); }
function csvName() {
  return 'swinglabels_' + (videoFile.name.replace(/\.[^.]+$/, '') || 'video') + '.csv';
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
    try { await navigator.share({ files: [f] }); } catch { /* 취소 */ }
  } else status('이 환경은 공유 미지원 — 다운로드/복사를 사용하세요.');
});
$('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(csvText()); status('labels.csv 복사 완료.'); }
  catch {
    const ta = document.createElement('textarea');
    ta.value = csvText(); document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove(); status('복사 완료(폴백).');
  }
});

$('file').addEventListener('change', (e) => {
  videoFile = e.target.files[0] || null;
  if (!videoFile) return;
  $('video').src = URL.createObjectURL(videoFile);
  $('video').hidden = false;
  $('analyze').disabled = false;
  cands = []; labels = {}; $('list').innerHTML = '';
  $('exportBar').hidden = true; $('summary').textContent = '';
  status(`${videoFile.name} (${(videoFile.size / 1048576).toFixed(0)}MB) — [후보 추출]을 누르세요.`);
});

window.addEventListener('error', (e) => status('오류: ' + e.message));
window.addEventListener('unhandledrejection',
  (e) => status('오류: ' + (e.reason && e.reason.message || e.reason)));
{
  const sm = document.querySelector('h1 small');
  if (sm) sm.textContent += ` · ${BUILD}`;
}
status(`영상 파일을 선택하세요. (build ${BUILD})`);
