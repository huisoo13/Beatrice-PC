# 모듈 경계 정리 (2026-10-10)

앱 제어, 화면 표시, SQLite 저장, 캡처 중단 처리, 오프라인 평가 계산의 책임을 분리했습니다.
기존 JSON 통신 형식, 완료 판정, 수요일 오전 6시 주간 구분, Drive 기록 형식은 유지합니다.

## 구성

| 역할 | 모듈 | 호출부의 책임 |
| --- | --- | --- |
| 계정 캐릭터 캐시 | `beatrice/character_catalog.py`의 `CharacterCatalog` | `ensure(names)`는 저장되지 않은 캐릭터의 계정 목록을 비동기로 조회합니다. `poll()`이 전체 응답을 원자적으로 저장하고 `decorate(records, emblem_path)`가 캐시와 공용 엠블럼을 연결합니다. Host는 호출·종료 순서만 담당합니다. SQL이나 UI에 의존하지 않습니다. |
| 공용 던전 스키마·보상 인덱스 | `beatrice/content_catalog.py`의 `ContentCatalog` | 신규 배열과 이전 객체를 검증하고 보상표 rows를 제공한다. HTTP·SQL·UI에 의존하지 않는다. |
| 던전 이름·기록 별칭 | `beatrice/content_match.py`의 `ContentMatcher` | OCR은 field_name에 비교해 name을 제공한다. Store는 record_candidates로 중복을 검사하고 native_presentation은 display_record_context와 record_detail로 현재 이름·보상을 표시한다. |
| 공용 데이터 갱신 | `beatrice/catalog_service.py`의 `CatalogService` | Host는 시작 준비·명령 허용·종료 시점을 결정합니다. 서비스는 네트워크 작업, 취소, 캐시, 매칭기, 갱신 주기와 수동 갱신 제한을 관리합니다. |
| 화면용 데이터 변환 | `beatrice/native_presentation.py` | 기록·캐릭터·던전 표시 데이터를 생성합니다. Host·작업자·UI 프레임워크에 의존하지 않습니다. 기존 native_bridge의 표시 함수 import는 유지합니다. |
| 스키마·이전 데이터 변환 | `beatrice/storage_schema.py` | Store가 연결을 생성한 뒤 스키마 초기화와 이전 메타데이터 변환을 호출합니다. |
| 저장·복원·보류 기록 귀속 | `beatrice/storage.py`의 `Store` | 세션과 Drive 어댑터는 SQL을 실행하지 않고 저장소 API를 호출합니다. 주간 DB 복구 SQL도 저장소에서 관리합니다. |
| SVG 문양 렌더링 | `ui/Beatrice.App/EmblemImageSource.cs` | `Load(path, size, color)`로 검증된 로컬 SVG 착색·크기 명시 디코딩을 기록과 하단 이미지에서 재사용합니다. 실패하면 null을 반환합니다. UI 배치와 실패 표시는 호출 화면이 소유합니다. |
| 캐릭터 이미지 | `ui/Beatrice.App/CharacterPortraitView.cs` | 현재 캐릭터의 검증된 로컬 SVG를 로딩·착색하며 기본 이미지와 비동기 전환을 관리합니다. |
| 기록 화면 | `ui/Beatrice.App/RecordsView.cs` | 주간 탐색, 기록 렌더링, 날짜·문장 배치, 캐시 아이템 레벨과 주간 변경 타이머를 관리합니다. 상세 보기와 스크롤·변경 알림은 콜백으로 전달합니다. |
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

## 캐릭터 정보·아이템 레벨·하단 직업 문양 (2026-10-10)
- Host → CharacterCatalog → 기존 LostArkClient.characters.siblings로 계정의 전체 캐릭터 정보를 가져옵니다. 개별 profile API는 호출하지 않습니다.
- 성공 응답의 모든 캐릭터와 원본 필드·조회 시각을 앱 데이터 `lostark/characters.json`에 저장하고 앱 재실행에도 재사용합니다. API 키와 Drive 기록에는 포함하지 않습니다.
- API 요청은 동시에 하나만 실행하며 중복 이름을 합칩니다. 호출 간격은 최소 0.7초입니다. 인증·연결·호출 제한 오류는 전체 요청을 잠시 보류하고 없는 캐릭터는 24시간 재조회하지 않습니다. 키 변경은 실패 대기를 해제하지만 정상 캐시를 유지합니다.
- CharacterCatalog.decorate는 캐시의 ItemAvgLevel을 기록의 itemLevel로 전달합니다. 잘못된 값은 생략하며 레벨은 클리어 당시 값이 아닌 캐시 조회 시점 값입니다. RecordsView는 아이템 레벨을 표시하지 않으며 API 캐시와 메시지의 레벨 값은 유지합니다. 캐릭터명 앞에는 캐릭터명과 같은 characterAccent 색상의 18px 직업 문양을 InlineUIContainer로 넣고 이름의 글자 중심에 맞춥니다. 문양과 캐릭터명 사이 간격은 2px이며 로딩 실패 시 문양만 생략합니다.
- CharacterCatalog.character_view(name, catalog.emblem_path)는 현재 캐릭터의 직업과 검증된 로컬 SVG를 profile 메시지의 characterClass/characterEmblem에 전달합니다. Host는 기록이 없어도 현재 캐릭터를 ensure 대상에 포함합니다.
- CharacterPortraitView는 하단 40px 이미지 영역의 SVG 로딩·색상 적용·실패 시 기본 이미지·캐릭터 전환 중 오래된 비동기 응답 폐기를 관리합니다. MainWindow는 profile을 전달하는 연결만 담당합니다. 문양과 미설정 임시 이미지 색상은 흰색(text)을 사용하고 원본 공용 에셋은 변경하지 않습니다. 상태 원형은 별도 UI로 유지합니다. EmblemImageSource가 SvgImageSource의 RasterizePixelWidth/Height를 표시 크기(기록 18px·하단 40px)의 논리 px로 명시해 자동 크기 렌더링에서 확인된 계단형 가장자리를 줄입니다.


## ContentJSON 배열·field_name/name 전환 (2026-10-11)

[세부 규칙과 검증](content-catalog.md). ContentCatalog가 형식 검증·인덱스를 소유하고 ContentMatcher가 이름·별칭을 소유한다. CatalogService, Store, native_presentation은 공개 API를 사용한다. Host는 같은 매칭기 전달만 담당한다. 주간 현황과 보상표에는 name을 전달하며 기존 기록 ID·시각·Drive 스키마는 유지한다. Python 테스트 450개와 .NET 표시·프로토콜·주간 현황 77개, 실제 새 JSON 63개 관문 매칭과 별도 DB의 저장·중복·표시 연결이 통과했다.
