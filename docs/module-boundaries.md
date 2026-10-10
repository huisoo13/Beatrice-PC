# 모듈 경계 정리 (2026-10-10)

앱 제어, 화면 표시, SQLite 저장, 캡처 중단 처리, 오프라인 평가 계산의 책임을 분리했습니다.
기존 JSON 통신 형식, 완료 판정, 수요일 오전 6시 주간 구분, Drive 기록 형식은 유지합니다.

## 구성

| 역할 | 모듈 | 호출부의 책임 |
| --- | --- | --- |
| 공용 데이터 갱신 | `beatrice/catalog_service.py`의 `CatalogService` | Host는 시작 준비·명령 허용·종료 시점을 결정합니다. 서비스는 네트워크 작업, 취소, 캐시, 매칭기, 갱신 주기와 수동 갱신 제한을 관리합니다. |
| 화면용 데이터 변환 | `beatrice/native_presentation.py` | 기록·캐릭터·던전 표시 데이터를 생성합니다. Host·작업자·UI 프레임워크에 의존하지 않습니다. 기존 native_bridge의 표시 함수 import는 유지합니다. |
| 스키마·이전 데이터 변환 | `beatrice/storage_schema.py` | Store가 연결을 생성한 뒤 스키마 초기화와 이전 메타데이터 변환을 호출합니다. |
| 저장·복원·보류 기록 귀속 | `beatrice/storage.py`의 `Store` | 세션과 Drive 어댑터는 SQL을 실행하지 않고 저장소 API를 호출합니다. 주간 DB 복구 SQL도 저장소에서 관리합니다. |
| 기록 화면 | `ui/Beatrice.App/RecordsView.cs` | 주간 탐색, 기록 렌더링, 날짜·문장 배치, 주간 변경 타이머를 관리합니다. 상세 보기와 스크롤·변경 알림은 콜백으로 전달합니다. |
| 보상표 화면 | `ui/Beatrice.App/RewardsView.cs` | 난이도·펼침 선택 상태, 보상표 렌더링, 갱신 상태 표시, 너비별 배치를 관리합니다. 갱신 요청은 콜백으로 전달합니다. |
| 엔진 메시지 모델 | `ui/Beatrice.App/EngineMessages.cs` | JSON 해석을 한곳에서 수행합니다. 프로필·기록·갱신 정보는 타입으로 전달하며 입력 JsonDocument가 해제되어도 보관 데이터가 유효합니다. 기록 배열은 변경 시에만 해석합니다. |
| 공통 화면 토큰 | `ui/Beatrice.App/ViewTheme.cs` | 글꼴·리소스·텍스트·색상 생성 함수를 화면 컴포넌트에 제공합니다. 화면 컴포넌트는 MainWindow나 EngineClient를 참조하지 않습니다. |
| 캡처 중단 처리 | 각 추적기의 `capture_interrupted()` | 호출부는 추적기의 내부 카운터를 직접 수정하지 않습니다. 확정 정보와 이미 소비한 완료 배너는 보존하고 연속 관측 증거만 초기화합니다. |
| 평가 박스 계산 | `tools/evaluation_geometry.py` | 세 평가 스크립트가 같은 IoU 구현을 사용합니다. 모델 라이브러리를 import하지 않으며 면적이 0인 경우 0을 반환합니다. |

MainWindow는 창 생명주기·화면 전환·설정과 엔진 연결을, Host는 작업자 및 로그인·Drive·유지보수의 실행 순서를 계속 관리합니다.

## 저장소 API

- `transaction(snapshot=True)`: 읽기 결과와 Drive revision을 같은 SQLite 스냅샷에서 조회합니다.
- `backup_to(path)`: WAL을 포함한 SQLite 백업을 생성합니다.
- `assign_pending_character(...)`: 보류 소유자의 여러 던전 기록을 원자적으로 캐릭터에 귀속합니다.
- `resolve_pending(segment, mappings)`: 캐릭터 확정 트랜잭션 안에서 보류 이벤트 연결을 저장합니다.
- `replace_history(rows)`: 이력 교체와 동기화 대기 상태 초기화를 한 트랜잭션으로 수행합니다.
- `recover_weekly_history(data, now)`: 이전 주간 DB에서 미복구 기록을 가져오고 필요할 때 업로드 revision을 갱신합니다.

다중 작업의 외부 트랜잭션 안에서 저장 메서드를 호출할 때는 기존 `transactional=False` 규칙을 사용합니다.
Drive 복원은 JSON 검증과 백업을 먼저 수행하고, 기록 교체 실패 시 기존 이력과 업로드 의무를 롤백합니다.

## 검증

- 전체 Python 테스트 **409개 통과**. 새 경계 테스트 9개에는 기록 교체 실패와 여러 보류 그룹 귀속 실패의 롤백, 공용 데이터 취소·캐시 저장 실패, 갱신 제한 유지, 캡처 중단 상태 보존, IoU 계산을 포함합니다.
- .NET 표시·메시지 검사 **45개 통과**. 주간 경계·한국 시간·문장 처리와 해제된 JSON 문서의 데이터 수명을 확인했습니다.
- Release WinUI 빌드 오류 **0개**. NuGet 취약성 데이터 서버 접근 실패에 따른 기존 `NU1900` 경고가 있습니다.
- 데모 UI 자동 검증 통과: 주간 탐색·선택 유지, 보상표 모드 전환·펼침·애니메이션·갱신 제한, 설정·복원 대화상자·포커스, 1280/640/375px 캡처 **24장**.
- 실제 YOLO/OCR/내장 OBS 준비 및 UI 시작 확인 통과. `--startup-check`로 임시 기록 DB를 사용했습니다. 실게임 관측 정확도나 장치 간 Drive 연동을 새로 검증한 것은 아닙니다.
- 내장 OBS 메인·스플래시 종료 검사 모두 통과. 작업자, OBS 자식 프로세스, 프로세스 감시, 상태 수신 스레드가 종료되고 캡처 자원이 해제되었습니다.
- `git diff --check` 통과.

검증 산출물은 `outputs/modularization-python-tests.log`, `outputs/modularization-ui-build.log`,
`outputs/modularization-ui-capture-final/`, `outputs/embedded-obs-probe/shutdown-main.json`,
`outputs/embedded-obs-probe/shutdown-splash.json`에 있습니다.
시작 검증 결과는 개발 UI 실행 파일 옆 `startup-check.txt`와 `startup-review/`에 있습니다.
375px에서 고정 사이드바 때문에 본문이 좁아지는 기존 레이아웃은 이전 캡처와 동일합니다.

## 실행 검사 명령

```powershell
& .venv-win/Scripts/python.exe -m unittest discover -s tests -q
& outputs/dotnet/dotnet.exe run --project ui/Beatrice.Presentation.Tests/Beatrice.Presentation.Tests.csproj -c Release --no-restore
& ./ui/Beatrice.App/build.ps1
& .venv-win/Scripts/python.exe tools/probe_app_shutdown.py --mode main
& .venv-win/Scripts/python.exe tools/probe_app_shutdown.py --mode splash
```
