# YOLO·PaddleOCR 단일 실행 경로 정리

2026-09-25. EasyOCR을 사용하지 않고, 화면 고정 좌표 OCR과 미사용 인식 레거시 코드를 제거했습니다. [정리 후보 점검](30-cleanup-audit.md) 이후 사용자가 지정한 제거 범위를 적용한 결과입니다.

## 남은 실행 경로

원본 화면 → 캐릭터·던전 YOLO → 탐지 영역 안의 PaddleOCR → 캐릭터/던전 확정 → 관문·배너 판단 → 기존 상태 저장입니다. YOLO가 영역을 찾지 못해도 고정된 화면 위치의 텍스트를 대신 읽지 않습니다.

탐지된 메뉴의 초상화 이름 줄, 던전 헤더의 제목·난이도, 로딩 탐지 영역 내부 문구·아이콘의 상대 위치 계산은 유지합니다. 이는 화면 절대 좌표를 읽는 대체 경로와 다릅니다. 관문 모델 입력 정규화 좌표와 데이터 라벨 좌표도 유지합니다. 다른 해상도에서 정상이라는 보장은 아니며 별도 검증이 필요합니다.

## 제거·전환한 내용

- `CharacterVision`의 예전 ROI 모델 초기화, 고정 이름 영역, 고정 팝업 제목 OCR, 화면 오른쪽 아래 고정 로딩 OCR, 메뉴 템플릿 경로를 제거했습니다. 로딩은 YOLO `loading_indicator`가 탐지된 영역에서만 확인합니다.
- `DungeonOCR.analyze` 및 `analyze_panel`의 화면 좌표식 경로와 EasyOCR 분기를 제거했습니다. `engine`은 Paddle만 허용합니다.
- 단독 구형 `DungeonPanelDetector`, 화면 크기·UI 배율을 보정하던 `layout.py`, 구형 `character-model.json`을 제거했습니다. `dungeon-panel.json`은 현행 상대 영역 정의만 남겼습니다.
- 데스크톱의 legacy 설정 분기를 제거하고 효과가 없어진 UI 배율 보정 컨트롤도 제거했습니다.
- `recognize_characters.py`, `predict_video.py`, `read_dungeon.py`를 현재 YOLO 경로로 전환했습니다. `read_dungeon.py`는 전체 이미지 입력만 받으며 잘라낸 패널 JSON은 받지 않습니다. 캐릭터 도구는 `--weights` 대신 `--config`를 받습니다.
- 폐기된 진단·준비 도구 `prepare_character_ocr.py`, `check_character_predictions.py`, `diagnose_character_lines.py`, `check_dungeon_samples.py`, `prepare_role_models.py`를 제거했습니다. 현재 구성의 검사는 `evaluate_ui_bootstrap.py`, `evaluate_raid_banner.py`, `replay_recognition_diagnostics.py`로 수행합니다.
- `models/easyocr/`, `models/character-yolo26n-first.pt`, `models/menu-layout/`을 삭제했습니다. 현재 Windows 가상환경의 EasyOCR 1.7.2도 제거했습니다.
- Windows 배포 의존성과 모델 복사 목록에서 EasyOCR·구형 모델을 제외했습니다. 남아 있는 과거 EasyOCR 휠을 다시 패키징하지 않도록 제외 조건과 검증 조건을 추가했습니다.

과거 macOS 패키지 관측 파일과 이전 단계 문서는 당시 이력입니다. 현재 설치 목록은 `packaging/requirements-windows.txt`입니다. 기존 배포 EXE는 이번에 재빌드하지 않았으므로 새 동작을 포함하지 않습니다.

## 유지한 코드와 자료

캐릭터·던전·관문 활성 모델, PaddleOCR 모델, 완료 배너 처리, 완료 고정·중복 방지 정책, 사용자 DB는 변경하지 않았습니다. 구형 DB 기록을 현재 구조로 옮기는 `legacy_completion` 마이그레이션은 여전히 필요하므로 유지합니다.

`session.py`와 `deferred_session.py`는 영상 이벤트 저장 도구와 테스트에서 사용하므로 미사용 코드로 삭제하지 않았습니다. 과거 학습 초기값과 원본 자료도 이번 인식 경로 정리와 별도로 보존했습니다. 전체 정리 후보 845 MiB를 일괄 삭제한 작업은 아닙니다.

## 검증

- 폐지된 경로의 테스트를 제거·전환하고, 로딩 탐지 누락 시 화면 모서리 OCR을 호출하지 않는 회귀 검사를 추가했습니다. 자동 테스트 125개 통과.
- 실제 UI 재현: 33/33 영역, 추가 오탐 0, OCR·로딩 기능 11/11, 캐릭터 전환·취소 시나리오 6/6, 일반 UI 음성 화면 4/4 통과.
- 배너·레이드·OCR 화면 37/37, 가변 하단 검사 3/3 통과.
- 결과: `outputs/legacy-removal-tests.log`, `outputs/legacy-removal-bootstrap/report.json`, `outputs/legacy-removal-banner.json`, `outputs/legacy-removal-banner.variable.json`.

위 결과는 기존 저장 화면의 재현 검사이며 독립적인 실게임 정확도 평가가 아닙니다. 특히 고정 로딩 보조 경로가 없어졌으므로 추가 게임 화면에서 로딩 YOLO 탐지를 확인할 필요가 있습니다. 새 모델을 학습하거나 교체한 것은 아닙니다. 실행 중인 앱은 완전히 종료한 뒤 `Run-Beatrice.cmd`로 재실행해야 합니다.
