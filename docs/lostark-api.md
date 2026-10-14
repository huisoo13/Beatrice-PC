# 로스트아크 API 모듈

2026-10-11 기준. 앱에 저장한 키로 사용할 수 있는 Python 서비스 모듈입니다. UI, Qt, 모델 라이브러리에 의존하지 않으며 Python 표준 라이브러리만 사용합니다.

## 빠른 사용

프로젝트 루트에서 실행합니다. 앱 설정에서 API 키를 입력하고 검증해 등록하세요. LostArkRegistration은 후보 키로 뉴스 API를 백그라운드 호출하고 정상 목록 응답을 받은 경우에만 LostArkApiKey.save로 암호화 저장합니다. 실패·취소·앱 종료에는 기존 키를 유지합니다. 입력 필드의 포커스 이동이나 설정 닫기로 자동 저장하지 않습니다.

```python
from beatrice.lostark import LostArkClient

api = LostArkClient.from_saved_key()
profile = api.characters.profile("후이수")
if profile is not None:
    print(profile.get("CharacterName"))
    print(profile.get("ItemAvgLevel"))

equipment = api.armory.equipment("후이수")
gems = api.armory.gems("후이수")
account_characters = api.characters.siblings("후이수")
events = api.news.events()
```

`from_saved_key(directory=None, timeout=15)`의 경로 우선순위는 명시한 `directory` → `BEATRICE_DATA_DIR` → `%LOCALAPPDATA%/BeatricePC`입니다. LOCALAPPDATA가 없으면 사용자 홈 아래 BeatricePC를 사용합니다. `lostark-api-key.bin`을 기존 `LostArkApiKey`로 복호화하며, Windows 사용자 계정에 연결된 DPAPI를 사용합니다. 매 요청에 키를 다시 읽어 앱에서 키를 변경하거나 초기화한 결과를 반영합니다. 클라이언트 생성만으로 네트워크 요청을 보내지는 않습니다.

서버 등의 별도 실행 환경에서는 `LostArkClient(key=token)` 또는 `LostArkClient(key_provider=load_token)`도 사용할 수 있습니다. token은 코드나 문서에 직접 적지 않고 실행 환경에서 전달합니다. 원본 토큰과 `bearer 토큰` 형식을 모두 지원합니다.

## 구현된 조회 API

캐릭터·전투정보 메서드는 캐릭터명 `name: str` 하나를 받습니다. 앞뒤 공백은 제거하고 UTF-8 URL 인코딩합니다. 표의 `{name}`은 인코딩된 이름입니다. 뉴스 events는 인자가 없습니다. 모든 호출은 GET입니다.

| 호출 | 공식 경로 | 반환 JSON 형태 |
|---|---|---|
| `api.news.events()` | `/news/events` | 진행 중인 이벤트 list |
| `api.characters.profile(name)` | `/armories/characters/{name}/profiles` | 기본 정보 dict 또는 None |
| `api.characters.siblings(name)` | `/characters/{name}/siblings` | 동일 계정 캐릭터 list 또는 None |
| `api.armory.full(name)` | `/armories/characters/{name}` | 전투정보 전체 dict 또는 None |
| `api.armory.equipment(name)` | `/armories/characters/{name}/equipment` | 장비 list 또는 None |
| `api.armory.avatars(name)` | `/armories/characters/{name}/avatars` | 아바타 list 또는 None |
| `api.armory.combat_skills(name)` | `/armories/characters/{name}/combat-skills` | 스킬 list 또는 None |
| `api.armory.engravings(name)` | `/armories/characters/{name}/engravings` | 각인 dict 또는 None |
| `api.armory.cards(name)` | `/armories/characters/{name}/cards` | 카드 dict 또는 None |
| `api.armory.gems(name)` | `/armories/characters/{name}/gems` | 보석 dict 또는 None |
| `api.armory.colosseums(name)` | `/armories/characters/{name}/colosseums` | 증명의 전장 dict 또는 None |
| `api.armory.collectibles(name)` | `/armories/characters/{name}/collectibles` | 수집품 list 또는 None |
| `api.armory.ark_passive(name)` | `/armories/characters/{name}/arkpassive` | 아크 패시브 dict 또는 None |
| `api.armory.ark_grid(name)` | `/armories/characters/{name}/arkgrid` | 아크 그리드 dict 또는 None |

공식 JSON을 변환 없이 반환하므로 신규 필드도 유지합니다. 표는 정상 응답의 예상 형태이며 클라이언트가 스키마를 강제하지는 않습니다. JSON null과 HTTP 204는 None입니다. 없는 캐릭터나 비어 있는 정보도 None일 수 있으므로 결과를 확인한 뒤 접근하세요. HTTP 404는 별도의 오류입니다.

기본 정보 예: `CharacterName`, `ServerName`, `CharacterClassName`, `CharacterLevel`, `ItemAvgLevel`, `ExpeditionLevel`, `GuildName`, `CombatPower`. 선택 필드는 `.get()`으로 읽으세요. 공식 변경 이력에 따라 `ItemMaxLevel`은 제거된 필드이므로 사용하지 않습니다. 전체 조회에서 필요한 항목을 한 번에 가져오면 개별 API의 반복 호출을 줄일 수 있습니다.

## 공통 요청과 기능 확장

```python
# 아직 전용 그룹을 구현하지 않은 API도 공통 통신을 재사용할 수 있습니다.
notices = api.request("GET", "/news/notices", params={"type": "공지"})

# POST는 JSON body를 지원합니다. 정확한 검색 필드는 공식 문서에서 확인하세요.
# result = api.request("POST", "/auctions/items", body=search_options)
```

`request(method, path, *, params=None, body=None)`은 공식 호스트에만 GET/POST 요청을 보냅니다. `params`는 쿼리 문자열, `body`는 JSON 직렬화 가능한 값입니다. GET body는 허용하지 않습니다. `path`에는 URL 전체가 아닌 인코딩된 상대 경로를 사용하고 쿼리는 params로 전달하세요. 인증 헤더, 한글 쿼리, JSON body, 응답 JSON, timeout과 오류 처리를 공유합니다. 인증이 포함된 요청의 리디렉션은 허용하지 않습니다.

추가 기능은 아래 그룹 파일에 얇은 메서드를 만들고 `LostArkClient`에서 연결하면 됩니다. 현재 전용 그룹은 characters와 armory만 구현했습니다.

| 확장 예정 그룹 | 공식 API 범위 |
|---|---|
| `news.py` | 공지, 이벤트, 알림 |
| `game_contents.py` | 콘텐츠 캘린더 |
| `markets.py` | 검색 옵션, 거래소 아이템 검색·상세, 최근 거래 |
| `auctions.py` | 검색 옵션, 경매장 아이템 검색 |

신규 메서드는 공식 경로·필수 인자·반환 형식을 이 문서에 추가하고 요청 매핑 테스트를 함께 추가합니다. 제거된 길드 순위, 도전 어비스 던전, 도전 가디언 토벌 API는 다시 추가하지 않습니다.

## 오류와 호출 제한

```python
from beatrice.lostark import (
    LostArkAuthError, LostArkRateLimitError, LostArkMaintenanceError, LostArkError,
)

try:
    profile = api.characters.profile("후이수")
except LostArkAuthError as error:
    print(str(error))  # 키 등록·변경 안내에 사용
except LostArkRateLimitError as error:
    print("다음 조회까지 대기할 초:", error.retry_after)
except LostArkMaintenanceError as error:
    print("점검·서비스 중단. 캐시를 유지하고 나중에 조회:", error.retry_after)
except LostArkError as error:
    print(str(error), error.status)
```

| 오류 | 의미 |
|---|---|
| `LostArkAuthError` | 키 없음·복호화 실패·잘못된 형식·HTTP 401/403 |
| `LostArkRateLimitError` | HTTP 429 또는 이 클라이언트가 알고 있는 잔여 횟수 소진. `retry_after`는 재시도까지의 초 |
| `LostArkNotFoundError` | HTTP 404 |
| `LostArkNetworkError` | 연결·타임아웃·응답 스트림 통신 실패 |
| `LostArkMaintenanceError` | HTTP 503: 점검 또는 일시적인 서비스 중단. `retry_after`는 재시도까지의 초 |
| `LostArkResponseError` | 다른 HTTP 오류 또는 정상 상태 코드에서 JSON 해석 실패 |
| `ValueError` | 잘못된 캐릭터명, 경로, 메서드, timeout 등 호출 인자 오류 |

API 오류들은 `LostArkError`를 상속하고 `status`에 HTTP 상태 코드를 제공합니다. 로컬 오류는 status가 None입니다. 오류 메시지에 키나 서버의 원문 오류 본문을 포함하지 않습니다.

2026-10-11: 공식 [점검 중 요청 안내](https://developer-lostark.game.onstove.com/usage-guide)에 따라 HTTP 503을 `LostArkMaintenanceError`로 분류합니다. 503은 일시적인 서비스 중단에도 사용되므로 점검 확정으로 단정하지 않습니다. 500/502/504는 기존 응답 오류로 유지합니다. HTML 점검 페이지의 본문을 파싱하거나 출력하지 않습니다.

클라이언트는 503 이후 최소 300초 동안 모든 엔드포인트의 추가 전송을 보류합니다. Retry-After의 초 또는 HTTP 날짜가 더 긴 대기를 지정하면 그 시간을 따릅니다. 없거나 잘못된 헤더는 300초로 처리합니다. 대기 중에도 동일한 전용 오류를 전달하며 자동 sleep·재시도는 없습니다. `CharacterCatalog`는 `maintenance` 케이스로 전체 캐릭터 조회를 보류하고 정상 캐시와 기존 표시를 유지합니다. 캐시가 없는 캐릭터의 정보는 비어 있으며, 대기 만료 후 필요할 때 재조회합니다. 해당 캐릭터의 재시도 시각은 저장하지만 클라이언트와 전체 조회 보류 상태는 프로세스 내 상태입니다. 키 등록 검증은 기존 키를 유지하고 점검·서비스 중단 안내를 표시하며 사용자가 다시 검증합니다.

공식 제한은 클라이언트당 분당 100회입니다. 최근 응답의 `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`은 `api.rate_limit.limit`, `.remaining`, `.reset_at`에서 확인합니다. reset_at은 Unix 초입니다. 429의 숫자 Retry-After와 reset_at을 참고하며, 대기 시점을 알 수 없으면 60초로 처리합니다. 남은 횟수가 0이면 해당 시점까지 추가 전송을 막습니다. 자동 sleep이나 자동 재시도는 하지 않습니다. 앱의 작업자/스케줄러에서 재호출 시점을 결정하세요.

클라이언트 한 인스턴스의 요청은 lock으로 순차 처리합니다. 이 로컬 제한 상태는 인스턴스별이며, 여러 인스턴스나 다른 프로그램이 같은 키를 사용하면 서버 한도를 공유합니다. 같은 앱에서는 인스턴스 하나를 재사용하세요. 타임아웃 기본값은 네트워크 작업당 15초이며 전체 작업 시간 보장은 아닙니다.

## 앱에서 사용

이 모듈은 동기식입니다. WinUI 브리지나 작업자 스레드에서 호출하고 UI 스레드에는 결과를 전달합니다. 캐릭터 변경 등 필요한 시점에 조회하며, 프레임마다 요청하지 않습니다. 현재 모듈은 저장·캐시·DB 갱신·화면 표시를 수행하지 않습니다. 해당 기능을 붙일 때 필요한 필드만 앱 상태에 반영하세요.

## 검증

```powershell
.\.venv-win\Scripts\python.exe -B -m unittest discover -s tests -p 'test_lostark*.py'
```

테스트는 가짜 HTTP 응답과 임시 DPAPI 키를 사용합니다. 실제 계정 키나 네트워크를 요구하지 않습니다. 실제 조회 확인은 별도로 저장된 키로 실행하며 키 값을 출력하지 않습니다.

2026-10-10 검증: 관련 테스트 23개 통과. 저장된 키로 `후이수` 기본 정보·동일 계정 캐릭터·전체 전투정보·아크 그리드 조회에 성공했습니다. 아만/바드/아이템 레벨 1,774.16, 동일 계정 캐릭터 13개를 확인했습니다. 이 값은 검증 당시 결과이며 실시간 데이터로 고정하지 않습니다.

## 공식 출처

- [개발자 포털](https://developer-lostark.game.onstove.com/)
- [시작 안내: 인증·호출 제한·응답 헤더](https://developer-lostark.game.onstove.com/getting-started)
- [API 변경 이력](https://developer-lostark.game.onstove.com/changelog)

공식 문서의 응답 필드와 경로가 바뀌면 최신 명세를 우선합니다. 위 구조와 사용법은 이 저장소의 구현 기준입니다.

## 관문 기록의 캐릭터 캐시

앱은 `CharacterCatalog`(`beatrice/character_catalog.py`)를 통해 `characters.siblings(name)` 응답의 모든 캐릭터 정보를 저장합니다. 캐릭터명별 `profile`(원본 응답 필드)과 `fetchedAt`을 `%LOCALAPPDATA%/BeatricePC/lostark/characters.json`에 보관하며 `BEATRICE_DATA_DIR`가 있으면 해당 경로를 사용합니다. 2026-10-14부터 좌측 표시 이름 변경과 새 완료 기록 저장에는 캐시가 있어도 해당 이름으로 재조회합니다. 반복 화면 갱신·주간 이동·기존 기록 수정은 재조회 원인이 아닙니다. 빠르게 연속 발생한 동일 이름 요청은 합치고, 조회 시작 후 생긴 저장 요청은 다음 조회에서 처리합니다.

CharacterRecordService는 Store.set_character_info로 기존 기록의 누락 필드를 현재 캐시로 한 번 보완하고 새 기록은 내부 DB에 조회 대기 상태를 기록합니다. 새 조회 완료 시 그 새 기록만 API 결과 또는 실패 시 캐시·빈 값으로 한 번 확정합니다. characterInfo는 className·itemLevel·serverName·fetchedAt만 포함합니다. source는 제거하고 과거 파일에서 읽을 때도 새 출력에서 제외합니다. 확정된 기록은 이후 캐시 갱신으로 변경하지 않습니다. 조회 대기 표식은 기록 JSON과 별도인 record_character_pending 테이블에 보존해 앱 재실행 후 이어서 확정합니다. API 키가 없으면 캐시 또는 빈 값으로 즉시 확정합니다. 점검·인증·네트워크 실패 후 현재 캐릭터 재시도는 기존 대기 정책을 따릅니다. 현재 캐릭터는 캐시, 완료 일지와 주간 현황은 기록의 characterInfo를 사용합니다.

`ensure(names)`는 이름을 중복 제거하고 비동기 조회를 시작하며 `poll()`이 응답을 저장합니다. `decorate(records, catalog.emblem_path)`는 캐릭터의 직업·검증된 공용 SVG·ItemAvgLevel을 표시 데이터에 추가합니다. 관문 기록에서는 아이템 레벨 표시를 생략하지만 캐시 원본 필드는 유지하며, `character_view(name, catalog.emblem_path)`는 현재 캐릭터의 하단 이미지용 직업 문양을 제공합니다. 현재 캐릭터는 기록이 없어도 조회 대상에 포함합니다. `credentials_changed()`는 키 변경 시 실패 대기를 해제하고 진행 중 응답을 폐기합니다. `stop()`과 `settled`로 종료를 관리합니다. API 키 초기화는 캐릭터 캐시를 지우지 않습니다.

직업은 정확히 일치하는 공용 엠블럼을 사용합니다. 문양이 없거나 API 키·네트워크가 준비되지 않아도 기록 목록은 정상 표시됩니다. 저장된 정보의 자동 TTL 갱신은 수행하지 않으므로 기존 캐릭터의 서버·아이템 레벨 등은 최초 조회 시점 값입니다.
