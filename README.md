# Beatrice PC

2026-10-10: [로스트아크 API 모듈과 사용법](docs/lostark-api.md). 앱에 저장된 키를 사용하는 공통 통신과 캐릭터·전투정보 조회를 제공합니다. 필요한 기능은 `beatrice.lostark.LostArkClient`에서 호출합니다.

2026-10-10: [Google Drive API 모듈과 사용법](docs/drive-api.md). 개인 기록과 공용 데이터가 공통 통신 모듈을 사용하며, 기록 저장·백업·캐시 정책은 기존 어댑터가 담당합니다.

2026-10-09: 사용자 실게임 테스트 완료 보고를 반영했습니다. [EX 하드 인식 보강](docs/62-exhard-gate-panel.md)과 [단일·다관문 완료 배너 재확인](docs/63-completion-gate-recheck.md)에 변경 내용·검증 근거·미적용 보완 사항을 정리했습니다.

2026-10-08 완료 로직: [완료 배너 → 관문 재확인](docs/63-completion-gate-recheck.md). 관문이 있는 콘텐츠는 배너만으로 저장하지 않고 완료 아이콘을 반복 확인합니다. 종탑 진단 841개 재생에서 조기 2관문 저장 차단·실제 완료 저장 확인, Python 테스트 346개 통과. 앱 재시작 후 적용됩니다.

2026-10-08 인식 보강: [EX 하드 단일 관문 영역 추가 학습](docs/62-exhard-gate-panel.md). 3막 EX 하드의 관문 영역 탐지 누락을 보강했습니다. 기존 72장 퇴행 0, EX 하드 29장 통과, 실제 플레이 재생에서 완료 저장 확인, 전체 테스트 342개 통과. 앱을 완전히 재시작해야 적용됩니다.

2026-10-08 UI 최신: [주간 관문 로그·Pretendard·최종 에셋 기준](docs/61-weekly-record-ui.md). 수요일 06시 기준 주간 이동, 날짜별 완료 로그, 한국어 조사와 관문 생략, 캐릭터명 살구색, 전체 본문 타이틀 20px을 적용했습니다.

2026-10-08: [완료 이력 보존과 주간 중복 방지 실게임 검증](docs/60-weekly-history-verification.md). 주간 반복 상태만 수요일 오전 6시(한국 시간)에 초기화하고 전체 이력은 화면·PC.json에 유지합니다. 이전 주 세르카 기록 이후 새 완료 저장, 같은 주 4막 하드의 실제 중복 차단을 확인했습니다. Python 테스트 342개 통과.

2026-10-08: [Qt 화면 제거와 WinUI 기능 이전](docs/59-native-drive-migration.md). Google 로그인·개인 Drive 기능을 UI 독립 Python 서비스로 옮기고 WinUI 설정에 연결했습니다. 기존 SQLite·JSON·DPAPI 로그인 정보를 유지하며, Qt는 분석 작업자의 Core 신호·스레드에만 사용합니다.

UI 에셋과 디자인 자료의 Git 관리 기준은 [디자인 자료 관리](design/README.md)를 참고합니다. 로컬 스킬 설치본·이전 시안·생성된 검토 이미지는 제외하고, 앱 소스·실행 에셋·최종 지침은 포함합니다.

2026-10-07: [WinUI 3 데스크톱 UI](docs/58-winui-desktop.md)를 적용했습니다. 승인한 태그강조형 기록 카드·사이드바·설정 오버레이를 실제 분석 작업자와 연결합니다. 소스 실행 전 `./ui/Beatrice.App/build.ps1`로 UI를 빌드합니다. 개인 Google Drive는 Google 로그인·권한 연결·저장·불러오기 및 완료 기록 자동 저장을 지원하며, 클라이언트 선택·공용 데이터·기록 삭제도 설정에서 사용할 수 있습니다.

앱 실행은 `Run-Beatrice.cmd` 하나로 통합했습니다. 더블클릭하면 관리자 권한을 요청하며 Windows UAC를 승인하면 실행됩니다. 이미 관리자 권한인 환경에서는 추가 요청 없이 실행합니다. 소스 환경의 `.venv-win`과 배포 폴더의 `runtime`을 모두 지원합니다.

2026-10-07: 게임 화면 오버레이는 추후 재작업을 위해 관련 구현·UI·테스트를 제거했습니다. [재작업용 구조와 표시 요구사항](docs/56-game-overlay-prototype.md)만 문서로 보존합니다.

2026-10-07: [스플래시 OBS 준비·자동 분석 시작 및 종료 검증](docs/57-auto-startup.md). 모델과 내장 OBS 엔진을 스플래시에서 준비하며, 게임이 감지되면 자동으로 분석합니다. 시작·정지 버튼을 제거했고 기록 삭제와 Drive 복원 중에는 분석을 보류한 뒤 자동 재개합니다. 테스트 309개 통과. 게임 미연결 상태에서 메인 화면·스플래시 종료 후 OBS 프로세스와 감시 스레드가 남지 않는 것을 실측했습니다.

<!-- MODEL-INVENTORY:START -->
## 현재 모델·클래스 빠른 확인

모델·클래스 변경 시 설정과 이 표를 함께 갱신합니다. `python tools/update_model_inventory.py`로 재생성하며 테스트로 일치 여부를 검사합니다.
과거 작업 일지보다 이 활성 모델 표를 우선합니다.

현재 YOLO **4개 / 21클래스** + 공용 PaddleOCR입니다.

| 활성 모델 | 클래스 | 탐지 대상 |
|---|---|---|
| `character-regions.pt` | `game_menu` | 게임 메뉴 패널 |
| ↳ | `current_name_line` | 현재 캐릭터 이름 줄 |
| ↳ | `switch_dialog` | 캐릭터 변경 확인창 |
| ↳ | `target_name_line` | 변경 대상 이름 |
| ↳ | `loading_indicator` | 오른쪽 아래 회전 표시 — 로딩 전 안내 |
| ↳ | `server_table` | 서버 선택 표의 프레임 |
| ↳ | `selected_character_card` | 파란 선택 표시가 있는 캐릭터 카드 |
| ↳ | `selected_character_name` | 선택된 카드의 이름 |
| ↳ | `game_start_button` | 게임시작 버튼 (선택 화면 보조 신호) |
| ↳ | `loading_progress` | 실제 로딩 진행 막대의 이동하는 발광 표식 |
| `dungeon-regions.pt` | `dungeon_panel` | 관문 있는 레이드 패널 |
| ↳ | `gateless_raid_panel` | 관문 없는 레이드 패널 |
| `dungeon-elements.pt` | `gate_panel` | 전체 관문 아이콘 영역 |
| ↳ | `dungeon_name` | 던전 이름 |
| ↳ | `difficulty` | 난이도 |
| ↳ | `gate_in_progress` | 진행 중 관문 아이콘 |
| ↳ | `gate_completed` | 완료 관문 아이콘 |
| ↳ | `gate_not_started` | 진행 전 관문 아이콘 |
| ↳ | `gateless_title` | 관문 없는 레이드 제목 |
| `completion-overlay.pt` | `completion_overlay` | 중앙 완료 연출 |
| ↳ | `completion_text` | N관문 돌파 / 던전 클리어 문구 영역 |

PaddleOCR은 탐지된 글자 영역을 읽는 공용 한국어 인식기입니다. EasyOCR은 사용하지 않습니다.
고정 화면 좌표나 패널 비율로 OCR 영역을 지정하지 않습니다. 모델 파일은 로컬 관리하며 Git에 포함하지 않습니다.
<!-- MODEL-INVENTORY:END -->

2026-10-06 최신: [내장 OBS·분석 성능 개선 정리](docs/55-capture-performance-summary.md). OBS 단일 캡처, OCR 일괄 제출, CPU 가속, 짧은 프레임 대기 처리를 적용했습니다. 보존 화면 재생에서 던전 분석 중앙값 875→431ms, 전체 회귀 테스트 301개 통과. 실제 실행에서도 사용자가 성능 개선을 확인했습니다.

2026-10-06: [구원의 종탑 제목 인식·목록 제한 제거](docs/48-tower-title-no-dictionary.md). 제목 요소 모델을 보강하고 던전명·난이도 목록 제한을 제거했습니다. 탐지 영역의 OCR 결과로 이름과 단계를 확인하며 어두운 단계 글자 처리도 보완했습니다. 기존 요소 70장 퇴행 0, 종탑 제목과 벨가르딘 완료 재생 확인, 전체 테스트 266개 통과. 앱 재시작 후 적용됩니다.

2026-10-06: [벨가르딘 2관문 인식 보강](docs/47-belgardin-panel-recovery.md). 던전 패널 YOLO를 추가 학습하고 기존 음성 라벨 오류 2장을 수정했습니다. 새로 확인된 같은 던전 제목으로 완료 문맥을 복구합니다. 기존 109장 퇴행 0, 동일 플레이 재생에서 2관문 저장 확인, 전체 테스트 264개 통과. 앱을 완전히 재시작해야 적용됩니다.

2026-09-29: [관문 돌파·던전 클리어 전용 탐지](docs/43-completion-overlay.md). 일반 퀘스트 배너 완료 판단을 중앙 완료 표시 YOLO+OCR로 교체하고, 완료 관측 진단을 순환 프레임과 분리합니다. 모델 구성·검증 범위·정리 내역은 문서를 참고하세요.

2026-09-28 최신: [공용 JSON 매칭·완료 기록 상세](docs/42-content-record-matching.md). 완료 저장 시 던전·난이도·관문이 한 항목으로 확인되면 공용 JSON의 정식 키를 사용하며, 실패·복수 후보는 OCR 원문을 유지합니다. 기록을 클릭하면 해당 관문의 골드·비용·귀속 비율을 확인할 수 있습니다. 앱 재시작 후 적용됩니다.

2026-09-28: [공용 Google Drive 데이터 읽기](docs/41-public-content.md)를 추가했습니다. 공개 폴더의 `JSON/ContentJSON.json`을 로그인 없이 다운로드·검증한 뒤 로컬 캐시로 보관해 사용합니다. 시작 시와 1시간 간격으로 변경을 확인하며 오프라인에서는 마지막 정상 데이터를 사용합니다. 실제 던전 10개/관문 항목 63개 조회와 전체 217개 테스트를 통과했습니다.

2026-09-28 최신: [기간제 아이템 안내가 있는 캐릭터 변경 창 보강](docs/40-variable-character-switch.md). 목록 개수·순서·창 크기 변형으로 캐릭터 YOLO를 추가 학습하고 활성화했습니다. 변경 창 후 로딩에서 대기로 전환하며 고정 좌표는 사용하지 않습니다. 새 창 19건·기존 화면 59건과 저장 진단 146장 재생을 검증했습니다. 앱을 완전히 재시작해야 새 모델을 사용합니다.

2026-09-27 저장 정책 변경: [완료 관문만 DB·리스트에 기록](docs/39-completion-only-storage.md). 진행 상태는 메모리에서 추적하고 완료 확정 때만 저장합니다. 완료 잠금·중복 방지·배너 완료·보류 완료 연결을 유지합니다. 재시작 시 기존 DB의 미완료 행을 정리하며 완료 기록은 보존합니다. 자동 테스트 205건을 통과했습니다.

2026-09-27 최신: [Google 로그인](docs/37-google-login.md)과 [Drive 저장·불러오기 및 완료 기록 자동 저장](docs/38-google-drive.md)을 추가했습니다. 로그인은 Windows DPAPI로 보관하며, JSON에는 캐릭터·던전·난이도·관문·상태와 완료별 고유 `recordID`, `updatedAt`을 저장합니다. 업로드 후 읽기 검증, 실패 재시도, 재실행 후 미전송 기록 처리, 복원 전 로컬 백업을 지원합니다. 전체 201개 테스트와 실제 Drive 왕복·자동 업로드 검증을 통과했습니다. 사용자도 저장·불러오기·재실행 유지를 확인했습니다. iOS 공유 규칙은 문서에 정리했으며 현재 PC는 PC.json 하나를 갱신하고 수요일 오전 6시(한국 시간)에 주간 반복 판정만 초기화합니다. 완료 이력은 화면과 PC.json에 계속 유지하며 다음 주 완료는 별도 ID로 추가합니다. recordID·updatedAt 비교 규칙은 Drive 문서에 정리했습니다. iOS 구현과 실제 장치 간 연동은 별도 작업입니다.

2026-09-27 최신: [스플래시·주기적 프로세스 감지](docs/35-client-auto-detection.md). 일반 권한으로 LOSTARK 프로세스를 1초마다 확인합니다. 새로고침은 기존 감시까지 종료한 뒤 스플래시에서 최초 조회부터 다시 시작합니다. 제외한 WMI 방식은 [이벤트 감시 검토 기록](docs/36-process-events-investigation.md)에 남겼습니다.

2026-09-26 실게임 확인: 사용자가 고정 좌표 제거 버전을 직접 테스트해 정상 동작을 확인했습니다. [변경 구조·검증 결과·활성 모델](docs/34-direct-region-resolution-training.md)에 정리했습니다. 모델 바이너리와 원본 이미지는 기존 정책대로 로컬에 보존하며 Git에 포함하지 않습니다.

2026-09-26 최신: [다중 해상도 직접 영역 탐지·학습 결과](docs/34-direct-region-resolution-training.md). 캐릭터명·변경 로딩·던전명·난이도·관문을 실제 YOLO 탐지 박스로 읽도록 전환했습니다. 고정 화면 좌표, 패널 내부 비율 OCR, 옛 관문 crop 좌표 변환을 실행 경로에서 제거하고 모델 3개를 활성화했습니다. 제공 원본과 기존 기록 재생은 통과했으며 추가 축소 화면의 극소 글자 OCR 1건은 미확정으로 남습니다. 앱을 완전히 재시작해야 적용됩니다.

2026-09-26 최신: [캐릭터 변경 대기 전환 복구·고정 좌표 조사](docs/33-character-loading-recovery.md). 로딩 탐지 누락을 캐릭터 YOLO로 보강하고, 로딩 영역의 실제 글자 줄을 찾아 읽도록 수정했습니다. 화면 고정 좌표 OCR은 복원하지 않았습니다.

2026-09-25 정리 완료: [중간 산출물 846 MiB 정리 및 최종 통합 검증](docs/32-cleanup-final-verification.md). 활성 모델·원본·복구 자료를 보존하고 테스트·UI 인식·완료 저장 재생 검사를 통과했습니다.

2026-09-25 최신: [EasyOCR·고정 좌표 OCR·인식 레거시 제거](docs/31-yolo-only-paddle-ocr.md). 현재 실행은 YOLO 탐지와 PaddleOCR만 사용합니다. 로딩도 탐지 영역 안에서만 확인하며 앱을 완전히 재시작해야 적용됩니다.

2026-09-25 문서 점검: [완료 배너 구현·활성화·검증 정리](docs/29-raid-completion-banner.md), [불필요 파일·모델·코드 점검](docs/30-cleanup-audit.md). 정리 후보와 보존 대상을 구분했으며 파일 삭제는 하지 않았습니다.

2026-09-24 최신: [레이드 완료 배너로 관문 누락 보완](docs/29-raid-completion-banner.md). 현재 레이드가 확인된 경우 관문 아이콘 또는 공통 완료 배너로 완료를 저장합니다. 관문 없는 레이드는 상단 헤더로 구분하고 `레이드 전체`로 표시합니다. 하단 도전 과제·목표 내용은 헤더 학습 영역과 제목 OCR에서 제외합니다.

2026-09-23 최신: [전체 관문 현재 상태 저장과 완료 지연 보완](docs/28-whole-gate-state.md). 모든 관문의 최초 상태를 저장하고 전체 배열 변경을 함께 갱신합니다. 완료는 초기화 전까지 고정하며 관문별 현재 행 하나만 유지합니다. 관문 모델도 보완 학습했습니다. 앱을 완전히 재시작해야 적용됩니다.

앞선 수정: [전투·완료 화면의 관문 기록 보완](docs/27-gate-completion-recovery.md).

앞선 수정: [매칭 모드 던전 탐지 보완](docs/26-dungeon-matching-model.md).

2026-09-22 최신: [캐릭터·던전 모델 분리, OCR 속도 개선과 던전 정보 10초 유지](docs/25-role-models-and-stable-context.md)를 활성화했습니다. 앱을 완전히 재시작하면 `캐릭터·던전 분리 탐지`로 실행됩니다. 실제 실패 사례의 앞선 수정은 [진단 기록 재생 결과](docs/24-live-recognition-fixes.md)에 있습니다.

로스트아크 화면에서 관문 상태를 읽고 캐릭터별 완료 기록을 로컬에 저장하는 Windows 앱을 단계적으로 개발합니다. 현재 Windows 실게임 환경에서 인식 동작을 확인하고 있으며, 다양한 화면과 전환 경로는 계속 검증합니다.

현재 저장 정책·실게임 확인·로그 위치는 [전체 관문 현재 상태](docs/28-whole-gate-state.md), 인식 구조는 [역할별 모델과 확정 정보 유지](docs/25-role-models-and-stable-context.md)를 확인합니다. [YOLO·OCR 통합 정리](docs/21-yolo-ocr-current.md)와 이전 단계별 문서는 작성 당시 구현 기록입니다.

이전 전환 단계: [던전 패널 YOLO 전환 준비](docs/22-dungeon-panel-yolo.md).

이전 통합 구성: [캐릭터·전환·던전·관문 통합 YOLO](docs/23-integrated-ui-yolo.md). 현재 모델 구성은 README 상단 표를 참고하세요. 3440×1440 기존 기록과 제공된 1920×1080·2508×1411 및 강제 21:9 화면을 검사했습니다. 미학습 해상도·UI의 실게임 검증은 계속 필요합니다. 모델 파일은 로컬에 있으며 Git에 포함되지 않습니다.

최신 OCR: 던전명은 목록 제한 없이 읽고, 실시간 표시는 관문 UI와 난이도 표기를 함께 확인합니다. 난이도/모드 표기는 노말·하드·헬·익스트림·싱글 모드·매칭 모드를 지원합니다. 긴 제목은 넓은 영역에서 공백을 포함한 글자 줄을 추려 읽습니다. 캐릭터명은 PaddleOCR로 레벨을 포함한 줄을 읽고 레벨만 제거합니다. 변경 팝업만 열거나 취소하면 기존 캐릭터를 유지합니다. 팝업 직후 오른쪽 아래 로딩 아이콘과 대기 문구를 함께 관측하면 재확인 상태로 전환하며, 로딩 중 기존 초상화는 재확정하지 않습니다. 맵 이동과 캡처 중단만으로 캐릭터를 초기화하지 않습니다. 실제 미학습 이름과 다양한 전환 경로는 추가 검증이 필요합니다. [기존 검증 기록](docs/19-dungeon-ocr.md).

최신 변경: [캐릭터 미확정 이벤트의 SQLite 임시 저장과 사후 확정](docs/18-deferred-events.md).

## 현재 구현

- YOLO26n 관문 아이콘 탐지, 상태별 개수와 표시 이미지 출력
- 녹화 영상의 연속 관측 안정화, 완료 이벤트 판단
- 전체 관문 상태는 메모리에서 추적하고 완료만 원자적으로 저장, 캐릭터·던전·관문별 단일 행 유지와 완료 상태 고정
- 별도 YOLO26n 캐릭터 이름 영역 탐지, PaddleOCR 이름 읽기, 변경 중 기록 보류와 저장 모듈 연결

미등록 던전·다른 화면 환경과 캐릭터 전환의 모든 경로 검증은 계속 필요합니다. Google Drive는 수동 저장·복원과 완료 기록 자동 업로드를 지원하며, iOS 앱 연동과 장치 간 자동 병합은 남아 있습니다. 실시간 분석과 앱 UI는 연결되어 있으며 현재 해상도의 사용자 테스트에서 정상 동작하는 것으로 확인했습니다. 초기 문서는 작성 당시 단계의 기록입니다.

## 실행 환경

프로젝트 폴더 `/Users/huisoo/Project/Beatrice-PC`에서 실행합니다. `.venv-ml`은 Python 3.12.14와 학습·분석 라이브러리 환경입니다. `.venv`는 초기 환경 진단·캡처 준비용 Python 3.9.6 환경입니다. Python 가상환경은 SPM과 비슷하게 프로젝트의 의존성을 분리하지만 Python 실행기까지 포함합니다.

```bash
.venv-ml/bin/python -m unittest discover -s tests -v
.venv-ml/bin/python tools/recognize_characters.py \
  'data/raw/character-review/C3.jpg' \
  --output outputs/character-recognition/image.json
```

한 장 실행에서는 observation의 인식 결과를 확인합니다. 현재 캐릭터 확정에는 여러 프레임이 필요하므로 한 장만으로 recordingAllowed가 true가 되지 않습니다. 원본과 모델은 로컬 data/, models/에 있습니다. 설치된 패키지 목록은 requirements-ml-macos-observed.txt에 기록합니다.

## 구성과 읽을 문서

[2026-10-06 누적 작업 정리 및 검증 결과](docs/50-progress-20261006.md)

최신 캐릭터 모델: `character-dim-1006`. 비밀번호 입력 중 어두워진 선택 카드와 이름을
추가 학습했습니다. [학습 내용과 재생 검증 결과](docs/49-dim-character-selection.md)를 참고하세요.

| 역할 | 코드 / 안내 | iOS 개발에 빗대면 |
| --- | --- | --- |
| OBS 게임 캡처 | beatrice/obs_capture.py, [환경 준비](docs/02-windows-setup.md) | 영상 입력 어댑터 |
| 관문 탐지 | tools/yolo_first.py, [학습·추론](docs/09-first-training.md) | 이미지 분석 서비스 |
| 관문 상태 | beatrice/gates.py | 연속 관측을 처리하는 상태 객체 |
| 이벤트 저장 | beatrice/session.py, beatrice/storage.py, [저장 안내](docs/12-local-storage.md) | 모델 계층과 영속 저장소 |
| 캐릭터 인식 | beatrice/character_vision.py, beatrice/character.py, [연결 안내](docs/16-character-recognition.md) | 문자열 인식과 현재 사용자 상태 |

데스크톱 앱은 앱에 포함한 OBS 엔진의 게임 캡처를 유일한 캡처 입력으로 사용합니다. 별도 OBS 설치·실행·가상 카메라 설정은 필요 없습니다. 게임이 관리자 권한이면 앱도 같은 권한으로 실행해야 합니다. [내장 OBS 구조와 검증 범위](docs/50-embedded-obs.md). [OBS 단일 경로 정리 내역](docs/51-obs-only-cleanup.md).

분석 입력은 BGR 이미지 배열입니다. 한 프레임의 관측과 최종 이벤트는 구분합니다. 실제 이벤트에는 시간대가 포함된 절대 시각을 저장하며, 영상 검증 JSON의 videoSeconds는 영상 안의 위치를 뜻합니다. 학습 이미지 재현 결과를 새로운 영상에 대한 정확도로 해석하지 않습니다.
