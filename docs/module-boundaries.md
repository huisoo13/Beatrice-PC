# 모듈 경계 정리 (최종 갱신: 2026-10-14)

## 로스트아크 점검 응답 분류 (2026-10-11)

- `lostark.client`가 HTTP 503을 공개 오류 `LostArkMaintenanceError(status=503, retry_after=초)`로 변환합니다. 점검 또는 일시적인 서비스 중단을 의미하며 500/502/504와 구분합니다. 응답 본문이나 키는 노출하지 않습니다.
- 공통 클라이언트는 최소 300초와 Retry-After(초/HTTP 날짜) 중 더 긴 시간 동안 엔드포인트 전송을 보류합니다. 자동 대기·재시도는 없으며 호출자가 재호출 시점을 정합니다.
- `CharacterCatalog`는 `maintenance` 실패 유형을 소유하며 전체 캐릭터 조회를 보류하고 기존 캐시를 유지합니다. 캐시가 없는 정보는 빈 값입니다. 해당 캐릭터의 재시도 시각은 저장하고 전체 보류는 프로세스 내 상태로 유지합니다.
- `LostArkRegistration`은 점검 안내를 전달하고 기존 키를 유지합니다. Host와 MainWindow는 기존 공개 API와 결과 메시지를 연결하며 별도의 오류 해석 로직을 추가하지 않습니다.

제목 첫 숫자 탐지 보강(2026-10-11): `tools/review_title_elements.py`는 검토된 학습 라벨·dim/크기 변형 자료 준비와 실제 YOLO/OCR 재생을 소유하고, 기존 `tools/train_dungeon_panel.py`로 학습한다. 실행 중 인식 모듈·공용 매칭·Store의 경계는 유지한다. 상세 자료와 검증 범위는 [제목 숫자 학습](64-title-first-digit-training.md)을 참고한다.

앱 제어, 화면 표시, SQLite 저장, 캡처 중단 처리, 오프라인 평가 계산의 책임을 분리했습니다.
화면용 통신 형식과 관문 아이콘·배너 판단은 유지합니다. 완료 DB와 Drive 형식은 [완료 기록 계약](63-completion-record-schema.md)에 따라 갱신하며, 캐릭터 확정 이후에만 던전 모델을 실행합니다. 주간 구분은 수요일 오전 6시 한국 시간입니다.

## 구성

| 역할 | 모듈 | 호출부의 책임 |
| --- | --- | --- |
| 골드 보상 관측 | `beatrice/gold_reward.py`의 `GoldRewardDetector` | `analyze(frame, seconds)`는 부모 전용 YOLO로 보상표를, 요소 YOLO로 실제 탐지 crop의 관문 제목·통화 영역을 찾는다. 제목 OCR과 명시적 획득/미획득 클래스가 맞으면 verified를 반환한다. 0.75초 제한·dim 정규화를 소유하고 저장소·UI에는 의존하지 않는다. `config/gold-reward.json`과 그 parentConfig인 `config/gold-reward-panel.json`을 사용한다. |
| 보상과 완료 연결 | `beatrice/gold_reward_session.py`의 `GoldRewardSession` | `register(rows, at)`는 이번 실행에서 새 저장된 ID만 등록한다. `observe(at, name, dungeon, boxes)`는 같은 캐릭터·던전·난이도·완료 관문과 두 번의 fresh 관측을 확인해 Store API로 갱신한다. 120초 만료와 `reset()`을 소유한다. LiveCoordinator는 호출 순서만 연결한다. |
| 계정 캐릭터 캐시 | `beatrice/character_catalog.py`의 `CharacterCatalog` | `ensure(names)`는 미보관 캐릭터와 `refresh(name)` 대기열을 조회합니다. `info(name)`는 복사한 기록용 정보를 반환하고 `take_refresh_results()`로 완료 결과를 전달합니다. `poll()`은 캐시를 저장하며 `decorate`는 기록의 characterInfo를 우선합니다. |
| 기록별 캐릭터 정보 | `character_info.py` / `character_record_service.py` | 전자는 직업·레벨·서버·조회 시각 4개 필드 생성·검증, 후자의 sync는 좌측 이름 변경·새 recordId 감지·조회 결과를 Store 공개 API에 연결합니다. Host는 연결만 담당합니다. SQL·UI 로직은 포함하지 않습니다. |
| 공용 던전 스키마·보상 인덱스 | `beatrice/content_catalog.py`의 `ContentCatalog` | 신규 배열과 이전 객체를 검증하고 보상표 rows를 제공한다. HTTP·SQL·UI에 의존하지 않는다. |
| 던전 이름·기록 별칭 | `beatrice/content_match.py`의 `ContentMatcher` | OCR은 field_name에 비교해 name을 제공한다. Store는 record_candidates로 중복을 검사하고 native_presentation은 display_record_context와 record_detail로 현재 이름·보상을 표시한다. |
| 공용 데이터 갱신 | `beatrice/catalog_service.py`의 `CatalogService` | Host는 시작 준비·명령 허용·종료 시점을 결정합니다. 서비스는 네트워크 작업, 취소, 캐시, 매칭기, 갱신 주기와 수동 갱신 제한을 관리합니다. |
| 화면용 데이터 변환 | `beatrice/native_presentation.py` | 기록·캐릭터·던전 표시 데이터를 생성합니다. Host·작업자·UI 프레임워크에 의존하지 않습니다. 기존 native_bridge의 표시 함수 import는 유지합니다. |
| 완료 JSON 계약 | `beatrice/completion_record.py` | validate·canonical·new_record·recognition_record·period·deduplicate를 제공합니다. DB·Drive는 canonical 완료 JSON을 사용하고 OCR/관문 추적 모듈은 명시적 임시 어댑터를 사용합니다. SQL·HTTP·UI에 의존하지 않습니다. |
| 스키마·이전 데이터 변환 | `beatrice/storage_schema.py` | Store가 연결을 생성한 뒤 스키마 초기화와 이전 메타데이터 변환을 호출합니다. |
| 저장·복원·주간 중복 | `beatrice/storage.py`의 `Store` | 세션과 Drive 어댑터는 SQL을 실행하지 않고 저장소 API를 호출합니다. 주간 DB 복구 SQL도 저장소에서 관리합니다. |
| SVG 문양 렌더링 | `ui/Beatrice.App/EmblemImageSource.cs` | `Load(path, size, color)`로 검증된 로컬 SVG 착색·크기 명시 디코딩을 기록과 하단 이미지에서 재사용합니다. 실패하면 null을 반환합니다. UI 배치와 실패 표시는 호출 화면이 소유합니다. |
| 캐릭터 이미지 | `ui/Beatrice.App/CharacterPortraitView.cs` | 현재 캐릭터의 검증된 로컬 SVG를 로딩·착색하며 기본 이미지와 비동기 전환을 관리합니다. |
| 주간 현황 집계 | `ui/Beatrice.App/WeeklySummary.cs` | `Build(records, koreaNow)`는 이번 주 완료 기록을 캐릭터·던전·난이도로 묶고 일반·귀속 골드를 분리합니다. 네트워크·SQL·WinUI에 의존하지 않습니다. |
| 주간 현황 화면 | `ui/Beatrice.App/WeeklySummaryView.cs` | 승인된 영수증 배치, 미연결 안내, 너비별 표시와 수요일 06시 변경 타이머를 소유합니다. MainWindow는 메뉴와 스냅샷을 연결합니다. |
| 완료 일지 | `ui/Beatrice.App/RecordsView.cs` | 주간 탐색, 읽기 전용 로그 행, 날짜·문장·직업 문양 배치와 주간 변경 타이머를 관리합니다. 스크롤·변경 알림만 콜백으로 전달하며 상세 클릭 콜백은 없습니다. |
| 보상표 화면 | `ui/Beatrice.App/RewardsView.cs` | 난이도·펼침 선택 상태, 보상표 렌더링, 갱신 상태 표시, 너비별 배치를 관리합니다. 갱신 요청은 콜백으로 전달합니다. |
| 엔진 메시지 모델 | `ui/Beatrice.App/EngineMessages.cs` | JSON 해석을 한곳에서 수행합니다. 프로필·기록·갱신 정보는 타입으로 전달하며 입력 JsonDocument가 해제되어도 보관 데이터가 유효합니다. 기록 배열은 변경 시에만 해석합니다. |
| 공통 화면 토큰 | `ui/Beatrice.App/ViewTheme.cs` | 글꼴·리소스·텍스트·색상 생성 함수를 화면 컴포넌트에 제공합니다. 화면 컴포넌트는 MainWindow나 EngineClient를 참조하지 않습니다. |
| 캡처 중단 처리 | 각 추적기의 `capture_interrupted()` | 호출부는 추적기의 내부 카운터를 직접 수정하지 않습니다. 확정 정보와 이미 소비한 완료 배너는 보존하고 연속 관측 증거만 초기화합니다. |
| 평가 박스 계산 | `tools/evaluation_geometry.py` | 세 평가 스크립트가 같은 IoU 구현을 사용합니다. 모델 라이브러리를 import하지 않으며 면적이 0인 경우 0을 반환합니다. |

MainWindow는 창 생명주기·화면 전환·설정과 엔진 연결을, Host는 작업자 및 로그인·Drive·유지보수의 실행 순서를 계속 관리합니다.

## 저장소 API

- `correct_completion(record_id, content_name, matcher, expected_updated_at=...)`: 검토한 OCR 제목을 정확히 재매칭하며 ID·관측·생성 시각과 OCR 원문을 보존한다. 수정 시각 충돌과 주간 중복을 차단하고 체크포인트를 재연결한다.
- `set_gold_reward(record_id, received)`: 이미 저장된 완료에 bool 결과만 연결한다. 미확인에서 확정으로 한 번 갱신하며 같은 결과는 no-op, 반대 결과는 거부한다. 이력·체크포인트·Drive revision을 원자적으로 변경한다.

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

## 캐릭터 정보·아이템 레벨·하단 직업 문양 (2026-10-10)
- Host → CharacterCatalog → 기존 LostArkClient.characters.siblings로 계정의 전체 캐릭터 정보를 가져옵니다. 개별 profile API는 호출하지 않습니다.
- 성공 응답의 모든 캐릭터와 원본 필드·조회 시각을 앱 데이터 `lostark/characters.json`에 저장하고 앱 재실행에도 재사용합니다. API 키와 Drive 기록에는 포함하지 않습니다.
- API 요청은 동시에 하나만 실행하며 중복 이름을 합칩니다. 호출 간격은 최소 0.7초입니다. 인증·연결·호출 제한 오류는 전체 요청을 잠시 보류하고 없는 캐릭터는 24시간 재조회하지 않습니다. 키 변경은 실패 대기를 해제하지만 정상 캐시를 유지합니다.
- CharacterCatalog.decorate는 기록 JSON의 characterInfo를 직업·레벨·문양에 연결합니다. 현재 캐릭터 표시는 캐시를 사용합니다. 기존 기록은 시작 시 캐시로 한 번 보완하고 새 기록은 API 결과 또는 실패 시 캐시로 한 번 확정합니다. Store.set_character_info가 history·gate_states·updatedAt·Drive revision을 함께 갱신하며 확정된 필드는 다시 변경하지 않습니다. 기록 ID·관측·생성 시각·보상은 유지합니다. 주간 현황은 선택 주에서 같은 이름을 합치고 최대 레벨을 표시합니다. RecordsView는 레벨을 새로 표시하지 않으며 문양 표시를 유지합니다.
- CharacterCatalog.character_view(name, catalog.emblem_path)는 현재 캐릭터의 직업과 검증된 로컬 SVG를 profile 메시지의 characterClass/characterEmblem에 전달합니다. Host는 기록이 없어도 현재 캐릭터를 ensure 대상에 포함합니다.
- CharacterPortraitView는 하단 40px 이미지 영역의 SVG 로딩·색상 적용·실패 시 기본 이미지·캐릭터 전환 중 오래된 비동기 응답 폐기를 관리합니다. MainWindow는 profile을 전달하는 연결만 담당합니다. 문양과 미설정 임시 이미지 색상은 흰색(text)을 사용하고 원본 공용 에셋은 변경하지 않습니다. 상태 원형은 별도 UI로 유지합니다. EmblemImageSource가 SvgImageSource의 RasterizePixelWidth/Height를 표시 크기(기록 18px·하단 40px)의 논리 px로 명시해 자동 크기 렌더링에서 확인된 계단형 가장자리를 줄입니다.


## ContentJSON 배열·field_name/name 전환 (2026-10-11)

[세부 규칙과 검증](content-catalog.md). ContentCatalog가 형식 검증·인덱스를 소유하고 ContentMatcher가 이름·별칭을 소유한다. CatalogService, Store, native_presentation은 공개 API를 사용한다. Host는 같은 매칭기 전달만 담당한다. 주간 현황과 보상표에는 name을 전달하며 기존 기록 ID·시각·Drive 스키마는 유지한다. Python 테스트 450개와 .NET 표시·프로토콜·주간 현황 77개, 실제 새 JSON 63개 관문 매칭과 별도 DB의 저장·중복·표시 연결이 통과했다.


## 완료 기록과 캐릭터 확정 경계 — 2026-10-11

RecognitionService는 analyze_character → LiveCoordinator.observe_character → recordingAllowed 확인 → analyze_dungeon 순서를 소유합니다. 미확정이면 던전 모델·OCR·배너를 호출하지 않고 DungeonTracker와 DungeonObserver의 reset 공개 API로 이전 문맥을 비웁니다. LiveCoordinator.update에는 이미 갱신한 identity를 전달해 같은 프레임의 캐릭터 추적을 두 번 하지 않습니다.

StateSession은 확정 캐릭터의 진행 상태를 메모리로 유지합니다. 미확정 관측·배너는 저장하지 않으며 과거 임시 완료를 귀속하지 않습니다. 이전 prepare_pending_run·assign_pending_character 호환 진입점은 소급 동작 없이 반환합니다. 독립된 이전 오프라인 Session/DeferredSession은 현재 실시간 경로에서 호출하지 않습니다.

Store가 스키마 변환 전 SQLite 백업, DB v5 변환, 완료·전송 예약 트랜잭션, 주간 잠금과 별칭 조회를 소유합니다. snapshot_existing은 원본을 읽기 전용으로 열어 WAL 포함 복사본을 만들며 원본을 변환하지 않습니다. Drive 어댑터는 새 JSON v5를 쓰고 v4 및 이전 배열을 읽습니다. 상세 형식·제약·검증 범위는 [완료 기록 계약](63-completion-record-schema.md)을 참고합니다.


보상 매칭 보완 (2026-10-11): ContentMatcher.record는 새 완료 JSON도 받고 같은 형식으로 반환합니다. 저장·표시 name을 OCR 매칭 별칭으로 사용하지 않으며 OCR 원문을 field_name으로 비교합니다. refresh_record_match는 기존 미매칭 완료의 원문·난이도·관문에 정확한 보상만 연결하는 순수 API입니다. Store.refresh_catalog_matches가 이력·체크포인트·전송 예약을 원자적으로 갱신합니다. Host는 시작 시와 공용 갱신 완료 후 해당 API 호출만 담당합니다. 실제 ContentJSON v16의 지평의 성당 3단계 두 관문 매칭과 Python 473개 회귀를 검증했습니다.

## 공용 골드 이미지 (2026-10-11)
- PublicAssetCache.image_path(name, bundle)는 정확한 논리 파일명으로 유일한 이미지를 찾고 파일 무결성을 재확인한 로컬 경로만 반환합니다. 네트워크를 호출하지 않으며 누락·변조·중복은 None입니다.
- CatalogService.currency_images()는 gold.unbound.png와 gold.bound.png를 각각 gold와 boundGold 경로로 제공합니다. Host는 currencyImages 메시지 연결만 수행합니다.
- EngineSnapshot이 선택적인 currencyImages를 복제해 메시지 수명을 보장하고, WeeklySummaryView가 이미지를 금액 왼쪽에 총합 16px·간격 4px, 나머지 14px·간격 2px로 표시합니다. 같은 경로는 BitmapImage를 공유하며 경로 갱신 시 화면을 다시 표시합니다. 이미지 누락·로딩 실패는 금액 텍스트를 유지합니다.

- 주간 현황 금액 폰트는 공통 ViewTheme의 Pretendard를 재사용합니다. 화면별 별도 폰트 생성자 연결은 없습니다.

## 엔진 프로세스 수명 (2026-10-11)

`EngineClient`는 `EngineProcessLifetime`의 UI 소유 Windows Job에 분석 프로세스를 연결합니다. `app_launcher --engine`은 모델 import 전에 `process_lifetime.join_owner_job()`을 호출하여 venv redirector가 Job 연결 전에 생성한 실제 Python도 같은 Job에 참여시킵니다. OBS 자식은 Job을 상속합니다. Job 핸들은 상속하지 않으며 UI가 종료되면 남은 자식들을 종료합니다. 정상 종료는 기존 shutdown·OBS 정리 완료 순서를 유지합니다.

`native_bridge.main`은 이벤트 루프 예외에서도 Host의 shutdown API로 작업자를 중지하고 join한 뒤 instance lock을 해제합니다. 작업자가 캡처를 유지한 채 중복 실행 제한만 풀리는 상황을 방지합니다. 다른 앱이나 설치된 OBS 프로세스를 종료하지 않습니다.

OBS stderr는 ObsCapture의 상태 수신 스트림에서 로그와 오류 메시지로 변환합니다. 파이프 연결 실패 및 예외 종료 검증은 [OBS 잔여 프로세스 수정](66-obs-orphan-process-fix.md)을 참고하세요.

OBS 설정 진단 (2026-10-11): ObsCapture.view()는 캡처 상태와 오류 메시지만 반환합니다. RecognitionService가 변경 시 RecognitionEvents.obs(generation, state)로 전달하고 Worker의 이벤트 어댑터와 Host가 같은 세대의 상태를 snapshot.obs에 연결합니다. 이전 작업자와 세대의 응답은 반영하지 않습니다. EngineSnapshot은 선택적인 obs를 복제하고 MainWindow.ObsSettings.cs가 OBS 설정 화면을 표시합니다. UI는 캡처 모듈 내부 상태를 직접 조회하지 않습니다. 기존 스냅샷에 obs가 없으면 상태 확인 대기를 표시합니다.

설정 메뉴는 클라이언트·OBS·데이터 관리와 로스트아크 API·Google Drive로 나눕니다. 클라이언트 화면은 앱 재실행 버튼만 표시합니다. MainWindow.ObsSettings는 감지 중인 클라이언트 선택과 분석 상태도 표시하며 기존 select 명령과 UpdateClients API를 재사용합니다. 데이터 관리는 기존 공용 데이터 갱신과 기록 전체 삭제 API를 그대로 사용합니다. 완료 일지는 RecordsView가 읽기 전용 Border 행으로 표시하고 상세 클릭 콜백과 상세 창은 제거했습니다. 설정 오버레이는 44px 상단바 아래의 본문만 덮으며 기존 반응형 여백은 본문 기준으로 계산합니다.

Google Drive 설정 (2026-10-11): MainWindow.Drive는 타이틀·안내 문구와 함께 로그인 전에는 Google 공식 흰색 Light 로그인 버튼을, 로그인 후에는 계정 정보·빨간 로그아웃 버튼을 표시합니다. GoogleAccountView가 40px 원형 사진·16px 이름·12px 이메일 표시와 이미지 로딩을 소유합니다. Google OAuth userinfo의 name/picture는 기존 암호화 세션에 함께 저장되고 GoogleAccount.view의 name/picture/email → Host snapshot.google → GoogleAccountView.Update로 연결됩니다. UI가 인증 저장소를 직접 읽지 않습니다. 사진은 HTTPS만 로드하며 누락·오류는 기존 기본 이미지로 표시합니다. 늦게 도착한 이전 사진의 로딩 결과는 반영하지 않습니다. 기존 세션의 필드 누락은 빈 값으로 처리하고 다음 로그인 복원에서 갱신합니다.

로그인 중에는 원본 이미지와 크기를 유지하고 중복 실행을 막습니다. 상태·오류는 버튼 도움말로 전달하며 Drive 권한 연결·수동 저장·불러오기 버튼은 제거했습니다. google_login/google_logout 명령, GoogleAccount의 로그인 복원·토큰 보관, PersonalDrive의 자동 저장은 기존 공개 API를 유지합니다. 복원 확인 연결은 남아 있지만 이 화면에서 수동 복원을 시작하지 않습니다.

최종 보상 범위: GoldRewardDetector는 `scope=final`과 골드 여부를 반환하고 관문 번호를 추정하지 않습니다. GoldRewardSession이 현재 전체 관문 완료와 새 완료 기록의 expectedGates를 확인해 마지막 관문 하나에 연결합니다. WeeklySummary는 미확인 보상을 공용 금액으로 합산하되 저장소의 goldReward를 변경하지 않습니다.

## 앱 아이콘 (2026-10-11)
Assets/beatrice.ico는 실행 파일 ApplicationIcon과 MainWindow의 AppWindow.SetIcon에서 사용합니다. StartupWindow는 AppIconRasterizer.Load(size)를 통해 Assets/beatrice-white.png를 물리 픽셀 크기에 맞춰 읽고 128px 중앙 영역에 합성합니다. AppIconRasterizer는 BitmapDecoder를 통한 premultiplied BGRA 해석과 크기별 캐시를 소유하며, StartupWindow는 배경·둥근 모서리·진행 애니메이션을 소유합니다. MainWindow.Splash는 초기 준비와 화면 전환만 연결합니다. 메인 사이드바의 레이드 분류는 승인된 아치형 SVG와 10px 레이드 라벨을 사용합니다.

상단바는 같은 투명 PNG를 20px로 표시하고 Beatrice 이름과 8px 간격을 사용합니다. 장식 이미지는 접근성 읽기에서 제외합니다. PNG 원본은 output/imagegen/beatrice-transparent-white.png이며 실행 시 output 폴더를 참조하지 않습니다.

앱 재실행 (2026-10-11): 클라이언트 설정의 앱 재실행은 엔진만 초기화하는 restart 명령을 보내지 않습니다. MainWindow.Splash가 중복 요청을 막고 기존 창을 숨긴 뒤 공통 ShutdownApp 흐름을 직접 호출합니다. WinUI Window.Close가 AppWindow.Closing을 통과한다는 가정에 의존하지 않습니다. 공통 종료 흐름이 EngineClient.StopAsync를 수행하여 OBS·작업자 정리 및 종료를 기다린 후 AppRelaunch.Start로 새 프로세스를 실행합니다. AppRelaunch는 실행 파일·설치 루트 인자만 보존하고 이전 화면·데모·캡처 인자는 전달하지 않습니다. 새 프로세스는 일반 시작 흐름의 스플래시를 거쳐 주간 현황으로 이동합니다. BeginSplash도 메인 창을 숨겨 재준비 중 기본 화면이 남지 않도록 합니다.

재실행 검증은 --startup-check --restart-check로 격리된 초기 준비 데이터를 사용하여 네이티브 앱 재실행 버튼을 Invoke합니다. 새 프로세스에는 검증 인자를 전달하지 않으므로 정상 앱으로 시작하며, 기존 PID 종료와 새 PID의 설치 루트 인자만 유지되는 것을 확인했습니다.

스플래시 이미지 진행 (2026-10-11): StartupWindow는 배경 래스터와 AppIconRasterizer의 DPI별 아이콘 픽셀을 별도로 보유합니다. Progress.Value의 0~3 단계를 0~1로 변환하고 기존 280ms 보간값으로 아이콘의 아래부터 원본 흰색을 합성합니다. 하단 바와 track/accent 생성자 의존성은 제거했습니다. MainWindow.Splash는 단계 전달과 전환만 담당합니다.

API 등록 검증 (2026-10-11): LostArkClient.news.events → NewsApi → 고정 공식 호스트의 GET /news/events를 재사용합니다. LostArkRegistration은 후보 키 검증 스레드와 결과 큐를 소유하고 begin/view/poll/stop/settled를 공개합니다. 네트워크 스레드는 저장소를 변경하지 않으며 owner thread의 poll에서만 LostArkApiKey.save를 호출합니다. Host는 명령 lostark_api_verify(기존 save도 동일 검증 경로), snapshot.lostArkApi의 configured/busy/message, lostark_api_saved 결과를 연결합니다. 성공 시 CharacterCatalog.credentials_changed를 호출하고 종료 시 등록 작업을 취소·정리합니다. MainWindow.LostArkApi는 명시적 검증·등록·변경·발급 안내 상태만 표시합니다. ApiKeyRequiredView는 공통 미등록 안내와 등록 진입 버튼을 렌더링하고 MainWindow는 메뉴 전환을 연결합니다. 미검증 입력의 자동 저장은 제거했습니다.

API 미등록 안내 중앙 배치: ApiKeyRequiredView.Render는 본문 StackPanel과 ScrollViewer를 받아 타이틀 아래 가용 높이를 계산합니다. 안내 문구·버튼을 Grid 안에서 가로·세로 중앙에 표시하고, 뷰가 로드·언로드될 때 viewport SizeChanged 연결을 등록·해제합니다. MainWindow는 화면 진입 연결만 유지합니다.

주간 현황 탐색 (2026-10-14): 기존 왼쪽 타이틀·오른쪽 14px muted 날짜 배치를 유지하고 날짜 양옆에 44px 원형 이전 주·다음 주 버튼만 추가합니다. WeekNavigationButton이 공통 버튼 모양·접근성 이름·클릭 연결을 소유하며 각 화면은 자신의 선택 주를 관리합니다. 수요일 06:00부터 다음 수요일 06:00 직전까지 집계하고 이번 주에서는 다음 버튼을 비활성화합니다. 화면 전환·기록 갱신에서 선택을 유지하며, 주가 바뀌면 과거 주의 절대 날짜를 유지합니다. 총합·캐릭터 합계·던전 내역은 선택한 주로 함께 갱신합니다.

## 캐릭터 선택 오탐 방어 (2026-10-14)

initial_login.observe_login은 탐지된 카드 안의 이름 영역을 요구합니다. 카드와 게임 시작 버튼만으로 선택 화면을 선언하지 않습니다. UIRegionDetector.locate_dungeon도 같은 카드·이름 포함 관계를 사용합니다. CharacterTracker는 이미 확정된 캐릭터를 해제할 때 같은 유효 선택 이름(또는 서버 선택 화면)의 3회 연속 관측을 요구합니다. 이름 없는 관측, 다른 이름, 화면 증거 중단, 캡처 중단, 관측 간격 초과는 누적 증거를 초기화합니다. 이미 미확정인 최초 접속 흐름과 비밀번호 가림 이후 기존 선택 대상 보존은 유지합니다.

학습 준비·평가는 tools의 prepare_character_false_positives와 evaluate_character_false_positives가 담당합니다. 런타임에 학습용 좌표·이미지를 사용하지 않습니다. 상세 검증은 [캐릭터 선택 오탐 보완](67-character-selection-false-positives.md)을 참고하세요.

빠른 실제 선택은 유효한 같은 이름 2회에 이어 실제 loginLoading이 관측될 때에도 전환을 인정합니다. 단일 선택 프레임이나 이름 없는 카드·버튼은 이 경로를 사용할 수 없습니다. 이는 빠른 선택에서 세 번째 선택 화면을 놓치는 경우를 위한 독립된 추가 증거입니다.

CharacterVision.read_name은 탐지된 이름 crop의 명암차를 확인해 dim 정규화를 글자 군집 선택 전에 적용합니다. 새로운 모델의 박스가 1픽셀 달라져도 어두운 끝 글자를 잘라 짧은 이름으로 확정하는 일을 방지하며, 이름 추측이나 저장된 캐릭터명 보정은 사용하지 않습니다.

2026-10-14 source 제거: characterInfo에는 className·itemLevel·serverName·fetchedAt만 출력합니다. CharacterRecordService는 Store.pending_character_records와 set_character_info(pending/finalize_pending)를 사용하며 조회 대기 상태는 record_character_pending 테이블에만 보관합니다. remove_character_info_source는 기존 값과 ID·관측·생성 시각을 유지하며 과거 source를 제거합니다. 호환 읽기는 이전 source를 버리고 출력에서는 제거합니다.
