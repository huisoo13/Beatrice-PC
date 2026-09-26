# 완료 배너 작업 후 파일·모델·코드 점검

**정리 실행 완료:** 이 문서의 1차 후보와 중간 결과를 실제 삭제한 내역 및 통합 검증 결과는 [최종 정리·검증](32-cleanup-final-verification.md)을 참고합니다.

**후속 변경:** 아래는 삭제 전 점검 기록입니다. 이후 사용자 요청에 따라 EasyOCR·화면 좌표식 OCR·미사용 인식 레거시를 제거했습니다. 실제 삭제·유지 목록은 [YOLO·PaddleOCR 단일 경로 정리](31-yolo-only-paddle-ocr.md)를 기준으로 합니다. 아래의 “삭제하지 않았다”, “보관” 판단은 점검 당시 상태입니다.

2026-09-25. 현재 설정, 데스크톱 진입점, 도구·테스트의 참조, 실제 파일 크기와 모델 SHA-256을 확인했습니다. 이번에는 문서화와 점검만 수행했으며 파일·모델·코드를 삭제하지 않았습니다. 경로는 저장소 루트 기준이고 크기는 MiB입니다.

## 결론

현재 실행에 필요 없는 중간 산출물이 있습니다. 아래 1차 후보 약 **845 MiB**는 최종 검증 결과와 원본 자료를 보존하면 정리할 수 있습니다. 다만 재생 입력 복사본을 지우면 해당 경로를 사용하는 재생 명령 전에 다시 복사해야 합니다. 소스 코드에서는 이번 조사만으로 곧바로 삭제할 수 있는 미참조 운영 모듈을 확정하지 않았습니다.

`outputs/` 전체를 임시 폴더로 보고 지우면 안 됩니다. 현재 학습·회귀 검사 도구가 이 안의 실제 게임 프레임을 원본으로 참조하며, 일부 학습 초기값과 복구 모델도 들어 있습니다.

## 1차 정리 후보

| 경로 | 크기 | 판단과 조건 |
| --- | ---: | --- |
| `data/datasets/raid-banner-0924/` | 289.5 | 폐기된 전체 패널 라벨의 이전 학습용 변환본. 현재 학습 구성은 v2를 사용. 원본·라벨 보존 후 정리 가능 |
| `data/datasets/raid-banner-header-0924/` | 336.3 | 헤더 학습의 이전 변환본. 현재 v2 데이터셋을 보존하고 정리 가능 |
| `outputs/raid-banner-0924/intermediate.pt`, `intermediate-19.pt`, `intermediate-38.pt` | 합계 59.35 | 선택되지 않은 체크포인트. 최종 모델·학습 초기값으로 선택한 `intermediate-27.pt`와 구별 |
| `outputs/raid-banner-0924/bootstrap/` | 18.31 | 중간 모델 검사 이미지. 최종 `bootstrap-final/`과 최종 보고서를 보존하고 정리 가능 |
| `outputs/raid-banner-0924/gated-replay/` | 50.85 | `outputs/gate-completion-review-0923/`의 부분 복사. 92개 파일 해시 일치 확인 |
| `outputs/raid-banner-0924/gateless-replay/` | 83.31 | `outputs/state-failure-0923/`의 부분 복사. 152개 파일 해시 일치 확인 |
| `outputs/raid-banner-0924/normal-replay/` | 7.62 | `outputs/normal-quest-review-0924/`의 부분 복사. 16개 파일 해시 일치 확인 |

중간 `intermediate-*.json/log`, `*-result.json`, 이전 `*-replay.log`, `check_ocr.py` 등은 현재 앱 실행에 필요 없습니다. 실패 원인 조사 이력으로 잠시 보관하거나 최종 결과만 남길 수 있지만 용량 절감 효과는 작습니다. `candidate-*.json`은 로컬 재현 검사에서 쓰므로 검사 경로 정리와 함께 처리합니다.

## 반드시 보존할 활성 구성

| 항목 | 현재 역할 |
| --- | --- |
| `models/character-regions.pt` | 캐릭터 UI 5클래스. SHA-256 `3a004f05420272f84a349f178dc11a530c114ab13cc790b1b7054a9803337b4b` |
| `models/dungeon-regions.pt` | 던전·관문 패널, 완료 배너, 무관문 헤더 4클래스. SHA-256 `8f1681465a70f9a6d8682b18fc6cb2013128924539a6e41a9928f37c9724ce84` |
| `models/gates-yolo26n-first.pt` | 현재 관문 상태 모델. 파일명에 first가 있어도 활성 모델. SHA-256 `e4287fbd5d7878fad9fbf6c70b779d5e4664959b3b608d4008ff0c338f086355` |
| `models/paddleocr/korean_PP-OCRv5_mobile_rec_infer/` | 캐릭터·던전에서 공유하는 활성 OCR |
| `config/dungeon-panel.json` | 현재도 패널 내부 상대 영역 계산에 사용. `mode=legacy`나 존재하지 않는 옛 weights 항목만 보고 파일 전체를 삭제하면 안 됨 |
| 현재 config 및 `data/annotations/raid-banner-header-v2-0924.json` | 실행 설정·최종 학습 라벨 |
| 사용자 `records.sqlite3` 및 관련 DB 파일 | 실제 기록. 개발 산출물 정리 대상 아님 |

## 실행에는 불필요하지만 보존할 자료

- `outputs/raid-banner-0924/intermediate-27.pt`: 최종 v2 학습의 초기값. 현재 앱은 읽지 않지만 같은 학습 과정을 재현하려면 필요합니다.
- `outputs/raid-banner-0924/dungeon-regions-before-banner.pt`: 배너 적용 전 복구 모델. `outputs/training/dungeon-completion-v2-0923/weights/best.pt`와 해시가 같습니다. 둘 중 하나로 합칠 수 있으나 복구 경로를 문서와 함께 정리해야 합니다.
- 최종 `outputs/training/raid-banner-header-v2-0924/`의 설정·결과와 `best.pt`: 활성 모델과 best.pt가 동일한 것은 정상적인 배포 사본입니다. 활성 위치와 학습 보관 위치 중 하나를 무조건 불필요하다고 판단하지 않습니다.
- 캐릭터 `character-roles-v2/weights/best.pt`, 관문 `gate-state-refresh/weights/best.pt`도 각각 활성 모델과 해시가 일치합니다. 복구·학습 이력용으로 보존을 권장합니다.
- `final-eval.json`, `final-eval.variable.json`, `audit-result.json`, `bootstrap-final/report.json`, `*-final.json`, `*-final.summary.json`, `tests.log`: 최종 검증 근거입니다.
- `data/raw/`, 최종 라벨, 원본 진단 폴더: 학습과 미지원 콘텐츠의 후속 분석에 필요합니다. 특히 심연의 역류·가디언 자료는 후속 기능 자료이므로 버리지 않습니다.
- 이전 두 배너 라벨 파일 `raid-banner-0924.json`, `raid-banner-header-0924.json`: 현재 설정은 참조하지 않지만 라벨 변경 및 학습 초기값의 이력입니다. 용량이 작으므로 보관하거나 과거 자료 폴더로 이동하는 편이 낫습니다.

## 이전 모델·코드의 참조 상태

| 항목 | 확인 결과와 후속 판단 |
| --- | --- |
| `models/ui-regions.pt`, `models/ui-menu-recovery.pt` | 현재 split 실행에서는 로드하지 않음. `tools/prepare_role_models.py`가 학습 초기값 생성에 참조. 이력 재현을 유지하려면 보관 |
| `models/character-yolo26n-first.pt` | 현재 split 실행에서는 미사용. `CharacterVision(legacy=True)` 경로가 참조하므로 해당 경로 폐지와 함께 판단 |
| `models/easyocr/` | 현재 Paddle 설정에서는 미사용. EasyOCR 선택 분기와 준비 도구가 남아 있으므로 대체 OCR 지원을 폐지할 때 함께 정리 |
| `beatrice/session.py` | 현재 라이브 저장의 중심은 StateSession이지만 `iso` 같은 공유 함수와 영상 처리·테스트에서 사용. 파일 전체 삭제 불가 |
| `beatrice/deferred_session.py` | 라이브 경로에서 대체됐지만 `tools/store_video_events.py`와 테스트가 사용. 영상 이벤트 기능 유지 여부를 먼저 결정 |
| `DungeonPanelDetector`, 고정 영역 OCR, legacy 캐릭터 코드 | 현재 기본 실행에서는 비활성이나 설정 분기·테스트가 유지됨. 지원 모드를 줄이는 별도 리팩터링 대상으로 분류 |
| `tools/prepare_role_models.py` | 과거 7클래스 통합 모델을 역할별로 분리하는 일회성 도구. 실행 시 활성 `config/character-regions.json`과 `config/dungeon-regions.json`을 다시 씀. 특히 던전을 2클래스로 되돌릴 수 있으므로 현재 모델 준비 절차로 재실행하지 말 것. 향후 출력 경로 인자와 덮어쓰기 방지 추가 또는 archive 이동 권장 |

이 판단은 파일명만으로 결정하지 않고 현재 진입점·설정·정적 참조를 확인한 결과입니다. 모든 선택적 CLI 실행 경로의 동작까지 재검증한 것은 아니므로 오래된 코드의 일괄 삭제를 승인하는 근거로 삼지 않습니다.

## 정리 순서 제안

1. 활성 모델, 직전 복구 모델, 최종 라벨·원본·검증 보고서를 보존합니다.
2. 1차 후보의 이전 데이터셋·미선택 체크포인트·중복 프레임을 정리합니다.
3. 선택적으로 남길 legacy·EasyOCR·영상 이벤트 기능을 결정한 뒤 관련 코드·설정·테스트를 함께 정리합니다.
4. 코드 정리 시 자동 테스트와 활성 모델 로딩 검사를 다시 실행합니다. 데이터셋 복사본만 정리할 때는 전체 모델 재학습이 필요하지 않습니다.

이번 문서화 단계에서는 재학습이나 추가 실게임 검증을 하지 않았습니다. 이전 작업의 132개 자동 테스트 및 이미지 재현 결과는 [완료 배너 작업 문서](29-raid-completion-banner.md)에 기록되어 있습니다.
