# rally-cut 웹앱 V0.5 — 분석 + 검수

브라우저에서: 파일 선택 → 오디오 추출 → 온셋·군집(타구음 검출) →
구간 목록(탭 점프 재생 + KEEP/CUT 토글) → `cuts.csv` 내보내기.
**컷 영상 출력은 다음 버전** — 현재는 분석·검수까지.

## 실행

- 로컬 PC: 저장소 루트에서
  `python -m http.server 8765 --directory web` → `http://localhost:8765/app/`
- 같은 Wi-Fi의 폰: `http://<PC IP>:8765/app/`
  (V0.5는 WebCodecs를 쓰지 않으므로 HTTP LAN으로 충분. 단 HTTP에서는 [공유] 버튼이
  비활성 — [다운로드]/[복사] 사용.)
- 공개 호스팅(HTTPS): GitHub Pages 등에 올리면 폰 단독으로 접속 가능.

## Python CLI와의 정합

- 알고리즘 계층은 Python CLI(audio-only 경로)와 **비트 수준으로 일치**하도록 포팅:
  scipy `butter(4, [1500,8000]@22050)` 계수를 상수로 임베드하고
  `sosfiltfilt`/RMS/MAD/피크/`build_segments`/타임코드를 그대로 옮겼다
  (Python의 짝수 반올림 포함).
- 재검: `node web/app/test/parity.mjs <audio.wav>` 출력을 Python 참조 결과와 대조.
- 브라우저 전체 경로(AAC 디코딩 → 22050 리샘플)는 디코더 차이로 수 ms급 오차가 날 수
  있어, 같은 영상으로 CLI `analyze` 결과와 한 번 대조해두면 안전하다.

## 구조

- `js/demux.js` — mp4box 래퍼(오디오 트랙만 추출, 대용량 파일 안전)
- `js/audio.js` — AAC→ADTS→`decodeAudioData`(22050 컨텍스트 리샘플)→채널 평균
- `js/dsp.js` — `detect.py` 포팅 (SOS 상수, 환경 무관 — Node에서도 동작)
- `js/segments.js` — `build_segments`/cutlist/timecode 포팅
- `js/main.js` — UI: 목록·탭 점프(구간 끝 자동 정지)·토글·CSV(다운로드/공유/복사)

## 파라미터 (CLI audio-only 경로와 동일, 고정)

max_gap 3.0 / min_hits 3 / pad_pre 1.5 / pad_post 2.0 / min_duration 3.0,
keep 기본값 = dur ≥ 8.0s (짧은 구간도 목록에 남아 토글로 살릴 수 있음).
