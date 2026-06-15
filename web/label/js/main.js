// rally-cut 스윙 라벨러 V2 — 포즈(손목속도 피크)로 스윙 후보 검출 → 클립마다 동작 선택.
// V2 핵심: 오디오 추출 완전 배제. v1은 오디오 온셋으로 1.6초마다 무지성 후보였음 →
// V2는 MediaPipe pose로 영상을 훑어 실제 스윙(손목속도 피크)만 후보로.
// 출력 labels.csv(id,t,label)는 scripts/swing_label_collect.py(times.csv 모드)로 합류.
import { initPose, wristSeries } from './pose_mp.js';
import { swingSpeed, speedPeaks } from './swing.js';

const BUILD = 'v2';
// 클래스 (rally_cut/labeling.SWING_LABEL_CLASSES와 동일). 같은 버튼 재탭=해제.
const CLASSES = [
  { key: 'serve', ko: '서브' },
  { key: 'serve_under', ko: '언더' },
  { key: 'fh', ko: 'FH' },
  { key: 'bh', ko: 'BH' },
  { key: 'volley', ko: '발리' },
  { key: 'nostroke', ko: '무(노스윙)' },
];
const HALF = 0.8;       // 후보 클립 반폭(초)
const STRIDE = 0.1;     // pose 샘플 간격(초) = 10fps
const PCTL = 85;        // 속도 피크 임계 백분위 (hit_events 기본과 동일)
const MINSEP = 0.6;     // 피크 최소 간격(초) — 한 스윙 중복 후보 방지

const $ = (id) => document.getElementById(id);
let videoFile = null;
let cands = [];        // {id, t}
let labels = {};       // id -> class
let playUntil = null;
let activeRow = -1;

function status(m) { $('status').textContent = m; }

// 초 → m:ss (오디오 앱 의존 제거 — self-contained)
function shortTc(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function videoReady(v) {
  if (v.readyState >= 1 && v.duration) return Promise.resolve();
  return new Promise((r) => v.addEventListener('loadedmetadata', r, { once: true }));
}

async function analyze() {
  $('analyze').disabled = true;
  const v = $('video');
  try {
    await videoReady(v);
    status('MediaPipe 로딩 중…');
    await initPose((m) => status(m));
    status('포즈 검출 중… (영상 전체 훑기)');
    const { series } = await wristSeries(v, {
      strideSec: STRIDE,
      onProgress: (t, dur) => status(`포즈 검출 중… ${Math.round(100 * t / dur)}% (${shortTc(t)}/${shortTc(dur)})`),
    });
    if (!series.length) { status('근접 선수 포즈를 찾지 못했습니다. 영상/구도를 확인하세요.'); return; }
    status('스윙 후보 계산 중…');
    const { tm, sp } = swingSpeed(series, { maxDt: STRIDE * 3.5 });
    const times = speedPeaks(tm, sp, { pctl: PCTL, minSep: MINSEP });
    cands = times.map((t, i) => ({ id: String(i + 1).padStart(4, '0'), t }));
    labels = {};
    renderList();
    $('exportBar').hidden = false;
    summarize();
    status(`스윙 후보 ${cands.length}개 (포즈 표본 ${series.length}). 클립을 탭해 재생하고 동작을 선택하세요.`);
  } catch (e) {
    console.error(e);
    status('검출 실패: ' + (e && e.message || e));
  } finally {
    $('analyze').disabled = false;
  }
}

function summarize() {
  const done = Object.keys(labels).length;
  const counts = {};
  for (const val of Object.values(labels)) counts[val] = (counts[val] || 0) + 1;
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
status(`영상 파일을 선택하세요. (build ${BUILD}, 오디오 미사용·포즈 기반)`);
