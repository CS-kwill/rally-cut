# rally-cut

테니스 경기 영상에서 포인트 사이 죽은 시간(공 줍기, 자리 이동, 휴식)을 **타구음 기반으로
자동 검출**해 잘라내고, 랠리만 이어붙인 압축 영상을 만드는 개인용 도구.

두 가지 형태로 동작한다.

- **웹앱 (브라우저, 설치 불필요)** — 폰/PC 브라우저에서 영상의 랠리 구간을 분석하고
  검수해 `cuts.csv`로 내보낸다. → [`web/app/`](web/app/) (V0.5: 분석·검수)
- **Python CLI** — 영상을 분석해 `cuts.csv`를 만들고, 그대로 720p로 렌더한다. → 아래 "CLI"

> 상용 앱(스윙비전 등)의 "포인트 사이 죽은시간 자동 제거"를 오픈소스 CV/오디오로 직접
> 구현하는 개인 프로젝트입니다. 학습/검증에 쓰는 경기 영상·정답 데이터는 비공개이며 이
> 저장소에 포함되지 않습니다.

## 동작 원리

1. **analyze** — 영상에서 오디오를 뽑아 밴드패스 필터로 바람소리(저주파)를 걸러내고,
   날카로운 타구음(고주파 충격음)을 검출한다. 타구음이 모여있는 구간을 랠리로 묶어
   편집 가능한 `cuts.csv`(타임코드 목록)로 저장한다.
2. **검수** — `cuts.csv`의 `keep`(Y/N)을 토글하거나 `start`/`end`를 직접 수정한다.
   (짧은 구간은 자동으로 `keep=N` 추천)
3. **render** — `keep=Y` 구간만 잘라 720p로 재인코딩해 한 영상으로 이어붙인다.

실수로 진짜 포인트를 잘라먹지 않도록, 검출은 "넉넉히 남기는" 쪽(랠리 앞 1.5초 / 뒤 2초
여유)으로 편향되어 있다.

## 웹앱 (브라우저)

설치 없이 브라우저에서 바로 쓴다. 영상을 고르면 오디오를 추출해 랠리 구간을 찾고,
구간 목록에서 탭 점프 재생 + KEEP/CUT 토글 후 `cuts.csv`를 내보낸다.
(현재 V0.5는 분석·검수까지. 컷 영상 출력은 다음 버전.)

- 로컬 실행: `python -m http.server 8765 --directory web` → `http://localhost:8765/app/`
- 알고리즘 계층은 Python CLI의 audio-only 경로와 **비트 수준으로 일치**하도록 포팅됨.

자세한 내용은 [`web/app/README.md`](web/app/README.md) 참고.

## CLI

### 설치

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`ffmpeg`와 `ffprobe`가 PATH에 있어야 한다. (이후 모든 명령은 `.venv\Scripts\python.exe` 사용)

### 사용

1) 분석 — 영상에서 랠리 구간을 찾아 `cuts.csv` 생성

```
.venv\Scripts\python.exe -m rally_cut.cli analyze "경기.mp4" -o cuts.csv
```

2) 검수 — `cuts.csv`를 열어 `keep`(Y/N), `start`/`end` 수정

```
index,start,end,keep,dur
1,00:00:12.000,00:00:38.000,Y,26s
2,00:01:05.000,00:01:11.000,N,6s
3,00:01:40.000,00:02:22.000,Y,42s
```

3) 렌더 — `keep=Y` 구간만 720p로 이어붙임

```
.venv\Scripts\python.exe -m rally_cut.cli render "경기.mp4" cuts.csv -o out.mp4
```

## 튜닝 (검출이 부정확할 때)

`analyze` 옵션으로 조정한다:

- **랠리가 끊겨 여러 조각으로 나뉨** → `--max-gap` 늘리기 (기본 3.0초)
- **포인트 사이 노이즈를 랠리로 잘못 잡음** → `--min-hits` 늘리기 (기본 3)
- **랠리 앞/뒤가 잘림** → `--pad-pre` / `--pad-post` 늘리기 (기본 1.5 / 2.0초)
- **짧은 구간이 너무 많이 keep=Y로 표시됨** → `--min-keep-duration` 늘리기 (기본 8.0초)
- **타구음을 너무 많이/적게 잡음** → `rally_cut/detect.py`의 `detect_hits` threshold 조정
  (기본 6.0, 범위 3.0~8.0; 낮추면 더 민감)

## `--use-yolo` — 선수추적 dwell 게이트 (선택)

```
.venv\Scripts\python.exe -m rally_cut.cli analyze "경기.mp4" -o cuts.csv --use-yolo
```

YOLOv8로 근거리 선수를 전체 영상에서 연속 추적해, "서브/리턴 준비 정지(dwell) 직후에
시작하지 않는 짧은 후보"를 걸러낸다. 오디오만으로는 `--min-keep-duration`이 잘라내던
**초단타 포인트를 회복**한다(Recall 우선 설계). 구간 끝은 "마지막 밀집 타구음 +
`--pad-tail`초"로 당겨 과보존을 줄인다.

- 옵션: `--yolo-k`(dwell 임계 민감도, 기본 0.8), `--dwell-min`(최소 정지 초, 기본 2.0),
  `--yolo-fps`(추적 fps, 기본 6), `--dense-gap`(밀집 온셋 간격 임계, 기본 0.6),
  `--pad-tail`(꼬리 보존 여유, 기본 4.0 — 0이면 트리밍 끔)
- **비용**: CPU 추론이라 느리다 — 9분 영상 ≈ 15~25분, 18분 영상 ≈ 30~50분.
  `ultralytics` 설치 필요. 일괄 배치 처리에 적합.

`--use-motion`(프레임차분)도 있으나 야간/저화질에서 실패가 확인돼 권장하지 않는다.

## 한계

- 타구음 기반이라 바람이 매우 심하거나 옆 코트 소리가 크면 오검출이 생길 수 있다.
- 선수 속도·오디오 신호만으로는 "랠리 본체 안의 죽은시간"을 줄이는 데 한계가 있어,
  공 추적(net-crossing) 신호를 더하는 방향이 다음 로드맵이다.

## 테스트

```
.venv\Scripts\python.exe -m pytest -v
```

## 라이선스 / 면책

개인 학습·실사용 목적의 프로젝트입니다. 입력 영상과 그 처리 결과의 권리·책임은 사용자에게
있습니다.
