// rally-cut 스윙 라벨러 V2 — 포즈(라켓헤드 속도 피크)로 스윙 후보 검출 → 클립마다 동작 선택.
// V2 핵심: 오디오 추출 완전 배제. 스윙 = 라켓헤드가 빠르게 휘둘러지는 것(사용자 도메인 통찰).
// 라켓은 pose에 없으므로 팔(팔꿈치→손목) 연장선으로 외삽, 어깨기준·신장정규화 상대속도 사용.
// 스캔은 폰 역량 최대 활용(rVFC 재생 디코드, full 모델). 임계값은 슬라이더로 즉시 튜닝.
// 출력 labels.csv(id,t,label)는 scripts/swing_label_collect.py(times.csv 모드)로 합류.
import { initPose, wristSeries, wristSeriesPlayback, hasRVFC, resetPose } from './pose_mp.js?v=25';
import { swingSpeed, speedPeaks } from './swing.js?v=25';

const BUILD = 'v2.5';
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
const MINSEP = 0.6;     // 피크 최소 간격(초) — 한 스윙 중복 후보 방지
const DEF_TH = 8.0;     // 라켓헤드 속도 임계 기본(신장/초) — 60fps 데이터 스케일, 슬라이더로 튜닝

const $ = (id) => document.getElementById(id);
let videoFile = null;
let cands = [];          // {id, t, key}
let labels = {};         // key(t.toFixed(2)) -> class (임계값 바꿔도 시각 일치하면 보존)
let speedSeries = { tm: [], sp: [] }; // 스캔/로드 캐시 — 임계값만 바꿔 즉시 재계산
let threshold = DEF_TH;
let dataVideo = '';      // 로드한 JSON의 영상명(파일명 대조용)
let predsMap = {};       // key(t.toFixed(2)) -> {pred, conf, ns}  (모델 예측, predict_labels.py)
let collapseTau = 0.95;  // ns>=tau 고신뢰 nostroke 자동 접기
const LOWCONF = 0.6;     // conf<LOWCONF = 저신뢰(검수 권장 강조)
let playUntil = null;
let rowEls = {};         // 후보 index -> li 엘리먼트 (접기 섹션 포함 점프용)
let activeEl = null;

function status(m) { $('status').textContent = m; }

function shortTc(s) {
  if (!isFinite(s)) s = 0;
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
  const aborter = new AbortController();
  let wake = null;
  const onHide = () => { if (document.hidden) aborter.abort(); };
  document.addEventListener('visibilitychange', onHide);
  try {
    await videoReady(v);
    try { wake = await navigator.wakeLock?.request('screen'); } catch { /* 미지원/거부 무시 */ }
    status('MediaPipe(full) 로딩 중…');
    await initPose((m) => status(m));
    const mode = hasRVFC ? '재생 디코드' : 'seek';
    status(`포즈 검출 중… (${mode})`);
    const t0 = performance.now();
    const onProgress = (t, dur, n) => {
      const el = (performance.now() - t0) / 1000;
      const eta = t > 0 ? el * (dur - t) / t : 0;
      status(`포즈 검출 중(${mode})… ${Math.round(100 * t / dur)}% `
        + `(${shortTc(t)}/${shortTc(dur)}, 표본 ${n}, 남은 ~${shortTc(eta)})`);
    };
    const scan = hasRVFC
      ? wristSeriesPlayback(v, { rate: 1.5, signal: aborter.signal, onProgress })
      : wristSeries(v, { strideSec: 0.04, signal: aborter.signal, onProgress });
    const { series } = await scan;
    v.playbackRate = 1; // 스캔용 배속 → 라벨 재생용 원복
    if (!series.length) { status('근접 선수 포즈를 찾지 못했습니다. 영상/구도를 확인하세요.'); return; }
    speedSeries = swingSpeed(series); // 라켓헤드 상대속도(신장/초)
    rebuildCandidates();
    labels = {};
    $('tuner').hidden = false;
    $('exportBar').hidden = false;
    status(`포즈 표본 ${series.length}개. 슬라이더로 민감도를 맞춘 뒤, 클립을 탭해 동작을 선택하세요.`);
  } catch (e) {
    console.error(e);
    resetPose();
    v.playbackRate = 1;
    if (e && e.name === 'AbortError') {
      status('화면이 꺼져 검출이 중단됐습니다. [포즈 검출]을 다시 누르세요. (자동잠금 방지 시도됨)');
    } else {
      status('검출 실패: ' + (e && e.message || e));
    }
  } finally {
    document.removeEventListener('visibilitychange', onHide);
    try { await wake?.release(); } catch { /* noop */ }
    $('analyze').disabled = false;
  }
}

// 캐시된 속도 시계열에서 현재 임계값으로 후보 재계산 (pose 재스캔 없음 — 즉시).
function rebuildCandidates() {
  const times = speedPeaks(speedSeries.tm, speedSeries.sp, { minHeight: threshold, minSep: MINSEP });
  cands = times.map((t, i) => {
    const key = t.toFixed(2);
    const pr = predsMap[key];
    return {
      id: String(i + 1).padStart(4, '0'), t, key,
      pred: pr ? pr.pred : null, conf: pr ? pr.conf : null, ns: pr ? pr.ns : null,
      collapsed: !!(pr && pr.ns >= collapseTau),   // 고신뢰 nostroke → 접기
    };
  });
  renderList();
  summarize();
}

function koOf(key) { return (CLASSES.find((x) => x.key === key) || {}).ko || key; }

function summarize() {
  const swing = cands.filter((c) => labels[c.key] && labels[c.key] !== 'nostroke').length;
  const collapsed = cands.filter((c) => c.collapsed).length;
  const low = cands.filter((c) => !c.collapsed && c.conf != null && c.conf < LOWCONF).length;
  $('summary').textContent = `후보 ${cands.length} · 스윙 ${swing}`
    + (collapsed ? ` · 접힘 ${collapsed}` : '') + (low ? ` · 저신뢰검수 ${low}` : '');
  $('sensval').textContent = `${threshold.toFixed(1)} → 후보 ${cands.length}`;
}

// 후보 1개의 li 생성 (예측 뱃지·저신뢰 강조·예측 버튼 사전선택).
function makeRow(c, i) {
  const li = document.createElement('li');
  li.dataset.i = i;
  const low = c.conf != null && c.conf < LOWCONF;
  if (low) li.classList.add('lowconf');

  const clip = document.createElement('div');
  clip.className = 'clip';
  const badge = c.pred
    ? `<span class="pred${low ? ' low' : ''}">예측 ${koOf(c.pred)}·${c.conf != null ? c.conf.toFixed(2) : '?'}${low ? ' ⚠' : ''}</span>`
    : '';
  clip.innerHTML = `<span>▶ #${i + 1}</span> ${shortTc(c.t)}`
    + `<span class="dur">${(2 * HALF).toFixed(1)}s</span> ${badge}`;
  clip.addEventListener('click', () => jumpPlay(i));

  const cls = document.createElement('div');
  cls.className = 'cls';
  CLASSES.forEach((cl) => {
    const b = document.createElement('button');
    b.textContent = cl.ko;
    if (labels[c.key] === cl.key) b.classList.add('sel');
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      if (labels[c.key] === cl.key) delete labels[c.key];
      else labels[c.key] = cl.key;
      li.classList.toggle('done', !!labels[c.key]);
      cls.querySelectorAll('button').forEach((x) => x.classList.remove('sel'));
      if (labels[c.key] === cl.key) b.classList.add('sel');
      summarize();
    });
    cls.append(b);
  });
  li.classList.toggle('done', !!labels[c.key]);
  li.append(clip, cls);
  rowEls[i] = li;
  return li;
}

function renderList() {
  const ul = $('list');
  ul.innerHTML = '';
  rowEls = {};
  cands.forEach((c, i) => { if (!c.collapsed) ul.appendChild(makeRow(c, i)); });
  const collapsed = cands.filter((c) => c.collapsed);
  if (collapsed.length) {
    const det = document.createElement('details');
    det.className = 'collapsed';
    const sum = document.createElement('summary');
    sum.textContent = `▸ 자동 접힌 고신뢰 nostroke ${collapsed.length}개 (펼쳐 확인)`;
    det.appendChild(sum);
    const inner = document.createElement('ul');
    cands.forEach((c, i) => { if (c.collapsed) inner.appendChild(makeRow(c, i)); });
    det.appendChild(inner);
    ul.appendChild(det);
  }
}

function jumpPlay(i) {
  const v = $('video');
  if (activeEl) activeEl.classList.remove('active');
  activeEl = rowEls[i] || null;
  if (activeEl) activeEl.classList.add('active');
  const t = cands[i].t;
  v.playbackRate = 1;
  v.currentTime = Math.max(0, t - HALF);
  playUntil = t + HALF;
  v.play();
}

$('video').addEventListener('timeupdate', () => {
  const v = $('video');
  if (playUntil !== null && v.currentTime >= playUntil) { v.pause(); playUntil = null; }
});

$('analyze').addEventListener('click', analyze);

// 오프디바이스 pose 결과(JSON) 불러오기 — 폰 검출 없이 후보+슬라이더 즉시.
// JSON = {video, fps, dur, tm:[...], sp:[...]} (scripts/offdevice_pose.py 산출).
function applySwingData(data) {
  if (!data || !Array.isArray(data.tm) || !Array.isArray(data.sp) || data.tm.length !== data.sp.length) {
    status('JSON 형식 오류: tm/sp 배열이 필요합니다.'); return;
  }
  speedSeries = { tm: data.tm, sp: data.sp };
  dataVideo = data.video || '';
  labels = {};
  predsMap = {};
  collapseTau = (typeof data.collapse_tau === 'number') ? data.collapse_tau : 0.95;
  // 모델 예측이 있으면 predsMap 구성 + 각 후보 라벨을 예측으로 사전채움(final=pred 기본).
  if (Array.isArray(data.preds)) {
    for (const p of data.preds) {
      const k = Number(p.t).toFixed(2);
      predsMap[k] = { pred: p.pred, conf: p.conf, ns: p.ns };
      if (p.pred) labels[k] = p.pred;   // 사전선택
    }
  }
  $('tuner').hidden = false;
  $('exportBar').hidden = false;
  rebuildCandidates();
  const npred = Object.keys(predsMap).length;
  let warn = '';
  if (videoFile && dataVideo && !videoFile.name.toLowerCase().startsWith(dataVideo.toLowerCase().replace(/\.[^.]+$/, ''))) {
    warn = ` ⚠ 영상(${videoFile.name})과 데이터(${dataVideo}) 이름이 다름`;
  } else if (!videoFile) {
    warn = ' — 재생하려면 같은 영상도 선택하세요';
  }
  status(`로드: 표본 ${data.sp.length} (${dataVideo || '?'}, ${data.dur || '?'}s)`
    + (npred ? ` · 모델예측 ${npred}개 사전선택됨` : ' · 예측 없음(수동)') + `.${warn}`);
}

$('datafile').addEventListener('change', (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    try { applySwingData(JSON.parse(rd.result)); }
    catch (err) { status('JSON 파싱 실패: ' + err.message); }
  };
  rd.readAsText(f);
});

// 민감도 슬라이더 — 임계값만 바꿔 즉시 후보 재계산(재스캔 없음).
$('sens').addEventListener('input', (e) => {
  threshold = parseFloat(e.target.value);
  rebuildCandidates();
});

// ---- 내보내기 ----
// 예측 있으면 round-trip(채점용): id,t,pred,conf,final. 없으면 기존 id,t,label.
function csvText() {
  const hasPred = Object.keys(predsMap).length > 0;
  if (!hasPred) {
    const lines = ['id,t,label'];
    for (const c of cands) if (labels[c.key]) lines.push(`${c.id},${c.t.toFixed(2)},${labels[c.key]}`);
    return lines.join('\r\n') + '\r\n';
  }
  const lines = ['id,t,pred,conf,final'];
  for (const c of cands) {
    lines.push(`${c.id},${c.t.toFixed(2)},${c.pred || ''},${c.conf != null ? c.conf : ''},${labels[c.key] || ''}`);
  }
  return lines.join('\r\n') + '\r\n';
}
function csvBlob() { return new Blob([csvText()], { type: 'text/csv' }); }
function csvName() {
  const base = (videoFile && videoFile.name.replace(/\.[^.]+$/, ''))
    || (dataVideo && dataVideo.replace(/\.[^.]+$/, '')) || 'video';
  return 'swinglabels_' + base + '.csv';
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
  const v = $('video');
  v.src = URL.createObjectURL(videoFile);
  v.hidden = false;
  v.playbackRate = 1;
  $('analyze').disabled = false;
  cands = []; labels = {}; speedSeries = { tm: [], sp: [] }; dataVideo = '';
  $('list').innerHTML = '';
  $('tuner').hidden = true; $('exportBar').hidden = true; $('summary').textContent = '';
  status(`${videoFile.name} (${(videoFile.size / 1048576).toFixed(0)}MB) — 이제 [스윙데이터(JSON)]를 불러오세요.`);
});

window.addEventListener('error', (e) => status('오류: ' + e.message));
window.addEventListener('unhandledrejection',
  (e) => status('오류: ' + (e.reason && e.reason.message || e.reason)));
{
  const sm = document.querySelector('h1 small');
  if (sm) sm.textContent += ` · ${BUILD}`;
}
status(`① 영상 선택 → ② 스윙데이터(JSON) 불러오기. (build ${BUILD}, 오프디바이스 pose)`);
