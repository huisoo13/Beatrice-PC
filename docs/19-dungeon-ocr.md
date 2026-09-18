# 던전 이름·난이도 OCR — 현재 구현

왼쪽 상단의 텍스트를 읽어 dungeonName과 difficulty를 만들고, 관문 완료 이벤트와 함께 저장한다. 화면의 던전/관문 제목을 그대로 dungeonName에 사용한다. 별도의 상위 레이드 이름으로 변환하지 않는다.

## OCR 엔진과 역할

던전 OCR은 PaddleOCR의 한국어 `korean_PP-OCRv5_mobile_rec` 모델을 사용한다. 기존 EasyOCR로 실패하던 카멘과 긴 제목을 같은 원본에서 비교한 뒤 변경했다. 캐릭터 이름 OCR은 기존 EasyOCR를 유지한다. 한 던전 제목을 두 엔진으로 동시에 읽는 구조는 아니다.

공식 사용법·모델 출처: [PaddleOCR 문자 인식 문서](https://www.paddleocr.ai/main/en/version3.x/module_usage/text_recognition.html). 모델은 models/paddleocr에 내려받았으며 원본 URL·파일 해시는 manifest.json에 기록했다. 일반 분석은 로컬 모델만 사용하며 게임 이미지를 외부로 전송하지 않는다.

`beatrice/dungeon.py`의 DungeonOCR는 BGR 이미지 배열을 입력받는다. 현재 지원 크기는 3440×1440이다. 관심 영역은 Swift의 CGRect처럼 읽을 사각형을 지정한 것이다. 이름·난이도 영역을 각각 자르고, 글자 주변 여백을 줄인 뒤 회색조·확대·밝기 반전 이미지에서 읽는다. 입력 파일/영상과 무관하게 같은 analyze 함수를 쓴다.

`beatrice/paddle_reader.py`는 OCR 엔진의 결과를 공통 형태로 바꾸는 작은 어댑터다. Swift의 서비스 구현체를 교체하되 호출하는 쪽의 데이터 구조를 유지하는 것과 같다. 새 YOLO 학습은 하지 않았다.

## 검증과 안정화

최소 두 전처리 결과의 문자열이 같아야 한다. 일치한 읽기는 각각 신뢰도 0.5 이상, 적어도 하나는 0.65 이상이어야 한다. 이 값은 개발 설정이며 정확도를 보장하지 않는다.

`config/dungeon-ocr.json`에는 제공된 화면에서 육안 전사한 던전 이름 5개와 하드/노말을 검증 목록으로 넣었다. 공백·쉼표·콜론·대괄호를 제외한 **글자가 정확히 일치**해야 채택한다. 카엔을 카멘으로 유사도 치환하지 않는다. PaddleOCR가 원본 글자를 카멘으로 읽은 결과를 채택한다. 새 던전·난이도는 검수 후 목록에 추가해야 하며, 등록되지 않은 텍스트는 OCR 원문만 보존한다. 전체 게임 지원 목록은 아니다.

DungeonTracker는 같은 필드를 3회 연속 확인하면 안정화한다. 누락·오독·긴 관측 간격·다른 이름이 나오면 해당 확정값을 비워 이전 화면의 값을 잘못 재사용하지 않는다. difficulty만 읽혔다면 dungeonName은 null이고 contextStatus는 ocr_partial이다. 둘 다 확인되면 ocr_verified, 둘 다 미확정이면 ocr_pending이다. null은 Swift Optional의 nil처럼 미확정을 뜻한다.

## 저장 연결

RecordingSession.observe와 DeferredRecordingSession.observe의 dungeon_context 인자로 **같은 프레임의 안정화 결과**를 전달한다. 확정 이벤트와 임시 이벤트에 텍스트·상태·OCR 원문·엔진 이름을 저장한다. 나중에 캐릭터가 확인되어도 임시 이벤트의 던전 정보와 원래 시각은 유지한다.

OCR가 미확정이어도 관문 완료 자체는 기록한다. 나중에 OCR만 성공했다고 이전 기록을 자동 보정하거나 기존 null 데이터를 일괄 수정하는 기능은 아직 없다. 던전 이름만으로 레이드 진행 ID나 주간 초기화 기준을 만들지 않는다.

## 실행

현재 Mac의 `.venv-ml`에서 실행한다. 모델을 다른 환경에 준비할 때는 `tools/prepare_dungeon_ocr.py`를 실행한다. 설치된 버전은 requirements-ml-macos-observed.txt에 기록했으며 이 파일 자체가 Windows 호환성을 보장하지 않는다.

```bash
# 한 장의 OCR 결과 확인
.venv-ml/bin/python tools/read_dungeon.py data/raw/SAMPLE_006.jpg \
  --output outputs/dungeon-image.json

# 7장 전체의 OCR 비교 이미지와 JSON 생성
.venv-ml/bin/python tools/check_dungeon_samples.py

# 새 영상: 관문 탐지 + 던전 OCR
.venv-ml/bin/python tools/predict_video.py '/Users/huisoo/Downloads/SAMPLE_VIDEO.mp4' \
  --output outputs/video001-dungeon-paddle

# 이미 분석한 영상의 원본 좌상단 패널에 OCR 추가
.venv-ml/bin/python tools/read_dungeon.py outputs/video002/observations.json \
  --output outputs/dungeon-video002-paddle/observations.json

.venv-ml/bin/python -m unittest discover -s tests -v
```

각 관측의 dungeonObservation은 한 프레임 OCR이고 dungeonContext는 연속 관측 결과다. 한 장의 결과만으로 이벤트를 확정하지 않는다. 영상 분석에서 OCR을 끄려면 --without-dungeon-ocr를 지정한다.

## 실제 검증 결과 (2026-09-17)

| 원본 이미지 | 던전 이름 | 난이도 |
| --- | --- | --- |
| SAMPLE_001 | 고통의 마녀, 세르카 | 하드 |
| SAMPLE_002 | 종막 : 최후의 날 | 노말 |
| SAMPLE_003 | 서막 : 붉어진 백야의 나선 | 하드 |
| SAMPLE_004 | 1막 : 대지를 부수는 업화의 궤적 | 노말 |
| SAMPLE_005~007 | 어둠군단장 카멘 | 하드 |

이름과 난이도 모두 **7/7장**이 정답 전사와 일치했다. 같은 개발 샘플에서 기존 EasyOCR의 이름은 3/7장이었다. 기존 결과는 outputs/dungeon-samples-easyocr에 보존했고 새 결과는 outputs/dungeon-samples/report.json 및 preview.jpg에 있다. 전처리와 엔진을 선택하는 데 사용한 자료이므로 독립 정확도나 모든 던전의 성능을 의미하지 않는다.

영상과 저장 경로도 실행했다:

- SAMPLE_VIDEO: 실제 영상 디코딩·YOLO·PaddleOCR를 함께 실행해 144회 관측했다. 완료 1관문 기록에 `종막 : 최후의 날 / 하드`가 저장됐다.
- SAMPLE_VIDEO_002: 기존 원본 패널 153개를 PaddleOCR로 분석했다. 완료 2관문 기록에 `고통의 마녀, 세르카 / 하드`가 저장됐다. 캐릭터 확정을 영상 20초로 지연 주입해 임시 저장→확정 흐름을 확인했고, 재실행 추가 기록은 0건이었다.
- 저장 검증의 캐릭터와 녹화 시작 절대시각은 테스트용으로 주입했다. 실제 캐릭터 동시 인식 검증은 아니며 모든 기록은 test_only다. 완료 시각은 원래 관측 시각을 유지한다.
- 결과 DB/JSON: outputs/dungeon-paddle-video001.sqlite/.json, outputs/dungeon-paddle-storage.sqlite/.json 및 dungeon-paddle-storage-repeat.json.
- 회귀 테스트 **42개 통과**, 캐릭터 모델의 기존 학습 이미지 재검사도 12/12박스 일치·추가 박스 0개였다. 설치 후 pip check는 충돌 요구사항을 보고하지 않았다.

첫 영상의 분석 루프는 Mac CPU에서 약 37.1초로 약 29초 영상보다 오래 걸렸다. 실시간 처리 성능은 아직 충족한다고 말할 수 없다. 첫 영상의 메타데이터 프레임 수와 실제 디코딩 수는 12프레임 차이가 있어 해당 차이를 출력 메타데이터에 남겼다. 영상의 모든 프레임이 완전하게 처리됐다고 주장하지 않는다. Windows·다른 UI 배율·다른 해상도·미등록 던전은 추가 검증 대상이다.
