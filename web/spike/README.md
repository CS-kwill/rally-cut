# W0 기술 스파이크 — 아이폰 사파리 실측 4종

웹앱이 폰에서 "분석 → 컷 영상 출력"까지 완주할 수 있는지 판단하기 위한 go/no-go 게이트.
아이폰 사파리에서 아래 4가지를 실측한다.

| # | 항목 | 통과 기준(감) |
|---|---|---|
| ① | WebCodecs 1080p60 순차 디코딩 처리량 | 17분 영상 처리 예산(≤20분) 안에서 디코딩 몫을 충분히 남김 |
| ② | pose 추론 ms/frame — MediaPipe(WebGL) vs YOLOv8n-pose ONNX(wasm/webgpu) | 15fps 샘플링 기준 pose 패스가 예산 안 |
| ③ | mp4box 키프레임 스냅 컷 → mp4-muxer 재먹싱 → 공유시트 저장 | 카메라롤 저장 + 정상 재생 |
| ④ | 1GB 파일 Blob.slice 스트리밍 | 크래시 없이 완주 |

## 실행 방법

WebCodecs는 **보안 컨텍스트(HTTPS 또는 localhost)** 에서만 동작한다.

- **PC 크롬(개발 검증)**: 저장소 루트에서
  `python -m http.server 8000 --directory web/spike` → `http://localhost:8000`
- **아이폰 사파리(본 실측)**: HTTPS 호스팅 URL로 접속 (GitHub Pages 등).
  LAN IP(`http://192.168...`)는 보안 컨텍스트가 아니라 WebCodecs가 비활성화된다.

영상 파일 선택 → ①~④ 실행 → **보고서 복사**.

> 참고: GitHub Pages는 COOP/COEP 헤더를 설정할 수 없어 SharedArrayBuffer 기반 멀티스레드
> wasm은 비활성일 수 있다. 이 경우 ②(pose)는 단일 스레드로 떨어져 더 느리게 측정된다 —
> 이것도 유효한 실측 결과로 기록한다.

## 판정

- ①~④ 통과 → MVP(폰에서 컷 영상 출력) 진행
- ②가 병목 → pose fps 하향(8~10) 재실측 (stride 6~8로 재실행)
- 근본 미달 → 네이티브 경로 재평가 — 이 경우에도 본 산출물(검수 UI)은 재활용

## 구조

- `index.html` — 단일 페이지 UI (한국어)
- `js/demux.js` — mp4box.js 래퍼 (Blob 슬라이스 스트리밍, moov-at-end 대응, 샘플 메모리 해제)
- `js/decode.js` — 실측 ① (VideoDecoder, 백프레셔 decodeQueueSize≤40)
- `js/pose.js` — 실측 ② (MediaPipe tasks-vision / onnxruntime-web, webgpu→wasm 폴백)
- `js/cut.js` — 실측 ③ (GOP 버퍼 스냅, 패스스루 재먹싱, 오디오 실패 시 비디오 단독 폴백)
- `js/main.js` — 실측 ④(Blob 스트리밍) + UI 배선 + 보고서
- `models/yolov8n-pose.onnx` — `yolov8n-pose.pt` 640/opset12 내보내기
  (`YOLO('yolov8n-pose.pt').export(format='onnx', imgsz=640, opset=12, simplify=True)`)

외부 라이브러리는 jsdelivr CDN 사용: mp4box 0.5.2, onnxruntime-web 1.19.2,
@mediapipe/tasks-vision 0.10.14, mp4-muxer(latest).
