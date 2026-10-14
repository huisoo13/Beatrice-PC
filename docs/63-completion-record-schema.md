# 완료 기록 형식과 캐릭터 확정 이후 탐지

최종 갱신: 2026-10-14. 이전 저장·Drive 문서보다 이 계약을 우선합니다.

## 탐지와 기록 정책

- OBS와 캐릭터 YOLO·OCR은 계속 실행합니다. 캐릭터 미확정이면 던전 YOLO·OCR, 관문과 완료 배너 탐지를 실행하지 않습니다.
- 캐릭터가 던전 안에서 확정돼도 해당 프레임부터 탐지를 시작합니다. 이전 미확정 화면은 소급 저장하지 않습니다. 이미 보이는 완료 아이콘은 확정 이후 새 반복 관측을 거쳐 저장합니다.
- 전환·선택 화면으로 캐릭터 확정이 해제되면 던전 문맥·배너 후보·관문 추적을 비웁니다. 표시용 던전 문맥도 지웁니다.
- 전체 관문 상태의 메모리 추적은 유지하며 완료 행만 DB에 저장합니다. N관문 돌파·던전 클리어 배너는 관문이 있는 던전에서는 재확인 요청으로 사용합니다. 관문 없는 콘텐츠는 기존 배너 확인 경로를 사용합니다.

## 저장 필드

2026-10-14: `characterInfo`를 추가하고 Drive 출력은 v5로 전환했습니다. v4 문서와 이전 배열은 계속 읽습니다. 이전 앱은 v5를 지원하지 않을 수 있으므로 공유 앱도 새 계약에 맞춰야 합니다. DB 버전은 기존 v5를 유지하며 선택 JSON 필드만 확장합니다.

```json
{
 "characterInfo": {
  "className": "바드",
  "itemLevel": "1,774.16",
  "serverName": "아만",
  "fetchedAt": "2026-10-14T07:00:00+00:00"
 }
}
```

알 수 없는 값은 null입니다. characterInfo에는 className·itemLevel·serverName·fetchedAt만 저장합니다. source는 제거했으며 이전 파일에서 읽으면 무시하고 새 출력에는 포함하지 않습니다. fetchedAt은 캐시/API 조회 시각이며 완료 시각으로 간주하지 않습니다. API 원문 전체·키·PC 로컬 아이콘 경로는 넣지 않습니다. 아이콘은 저장된 className과 검증된 로컬 에셋을 연결합니다.

기존 누락 필드는 현재 캐시로 한 번 보완합니다. 저장된 필드는 덮어쓰지 않습니다. 새 완료는 먼저 안전하게 저장하고 기존 캐시 정보를 임시로 표시하며 내부 DB의 조회 대기 표식으로 API를 기다립니다. API 성공 또는 실패 결과가 오면 이번 새 기록만 한 번 확정하며 이후에는 유지합니다. 조회 대기 상태는 record_character_pending 테이블에 기록 ID로 보관하므로 로컬 앱 재실행 후 조회를 이어갑니다. 이 상태는 기록 JSON이나 Drive에 노출하지 않습니다. 키가 없으면 캐시 또는 빈 값으로 즉시 확정합니다. API 조회 시점에 캐릭터 정보가 업데이트되지 않았다면 반환된 값을 저장하며 실제 처치 순간의 장비 상태를 보장하지 않습니다.

Store.set_character_info(pending=True/finalize_pending=True), pending_character_records, remove_character_info_source는 공개 저장 API입니다. source 제거는 직업·레벨·서버·조회 시각을 보존하며 과거 대기 표식은 내부 테이블로 옮깁니다. history와 gate_states를 한 트랜잭션에서 갱신하며 recordId·observedAt·createdAt·기존 보상은 유지합니다. 필드 추가/확정은 실제 변경이므로 updatedAt을 증가시키고 실제 기록의 Drive revision을 올립니다. 이미 확정된 필드는 다시 갱신하지 않습니다. 신규 조회·저장 감지는 CharacterRecordService가 담당하고 Host는 sync와 표시 연결만 수행합니다. 주간 현황은 선택 주의 같은 캐릭터명을 합쳐 최고 레벨을 표시하며 완료 일지는 각 기록의 고정 정보를 사용합니다.

| 필드 | 의미 |
| --- | --- |
| recordId | 완료별 ID. 신규는 br2 UUID, 기존 br1 ID는 보존 |
| characterName | 확정 캐릭터명. 미확정 행은 저장하지 않음 |
| characterInfo | 선택 필드. 당시 확정한 캐릭터 직업·레벨·서버·API 조회 시각 |
| contentName | 공용 데이터 name 또는 매칭되지 않은 OCR 이름 |
| difficulty | 확정 난이도 |
| gateNumber | 1~8; 관문 없는 콘텐츠 전체 완료는 0 |
| expectedGates | 확인한 전체 관문 수. 과거 미상 또는 관문 없는 콘텐츠는 0 |
| isTest | 테스트 구분. true는 실제 UI·주간 집계·Drive 내보내기에서 제외 |
| observedAt | 반복 관측으로 완료를 확정한 프레임 시각. 실제 처치 시각을 뜻하지 않음 |
| createdAt | 해당 기록 최초 DB 생성 시각 |
| updatedAt | 생성 또는 실제 수정 시각. 동일 완료 재관측에서는 바뀌지 않음 |
| ocrOriginal | 저장 당시 OCR 이름·난이도·관문 번호; 있는 경우 보존 |
| catalogMatch | 저장 당시 매칭과 보상·버전; 있는 경우 보존 |
| goldReward | 선택 bool: true 획득, false 미획득. null 또는 필드 없음은 미확인 |

골드 여부는 완료 후 보상표의 관문 번호와 현재 완료 아이콘을 반복 확인하여 연결합니다. `goldReward`는 선택 필드이며 DB v5는 유지합니다. 현재 Drive 출력은 characterInfo 추가로 JSON v5입니다. 이전 기록은 그대로 읽으며 누락된 여부를 추정하거나 일괄 생성하지 않습니다. 구버전 PC의 엄격한 JSON 검증기는 새 필드를 읽지 못하므로 이 작업 이후 앱을 재시작해야 합니다. iOS는 추후 새 선택 필드를 지원해야 합니다. 주간 합계는 true 또는 미확인이고 공용 금액이 연결된 기록을 합산하고 false는 0으로 처리합니다. 미확인 상태는 저장 데이터에 유지하며 금액 미연결만 누락 건수로 표시합니다. 상세 정책은 [골드 보상 인식](65-gold-reward-recognition.md)을 참고합니다.

시간은 UTC ISO 문자열입니다. 관측·생성 시각을 알 수 없는 이전 Drive 기록은 observedAt·createdAt을 null로 둡니다. 이전 updatedAt이 없으면 기존 UNKNOWN_UPDATED_AT(1970년)을 유지합니다. 복원 시각을 완료 시각으로 만들지 않습니다. UI는 날짜 미상 기록을 별도로 보여주며, 관측 시각 미상은 현재 주 완료를 막지 않습니다.

characterKey·dungeonName·gate·gateName·state·completionScope·evidenceType·timeBasis·confirmedAt·savedAt·completedAt·recordType과 이전 recordID 철자를 영속 JSON에서 제거했습니다. YOLO/OCR 관측·진단의 dungeonName·state 등은 인식 도메인의 임시 데이터이며 DB나 Drive에 저장하는 완료 계약과 구분합니다.

## 중복 방지

캐릭터명 + 별칭을 해석한 콘텐츠 이름 + 관문 번호 + observedAt의 한국 시간 주차를 사용합니다. 주차는 수요일 06시부터 다음 수요일 06시까지입니다. 난이도는 완료 잠금에 포함하지 않습니다. 같은 관문을 다른 난이도로 다시 관측해도 같은 주에 두 번 저장하지 않습니다.

기존 공용 name, field_name, 저장된 fieldName과 OCR 원문을 확인하므로 표시 이름이나 캐시가 바뀌어도 중복을 막습니다. 갱신 시각이 다음 주로 넘어가도 observedAt이 같으면 기존 주의 완료입니다. 신규 완료 저장은 SQLite 쓰기 잠금을 먼저 잡아 두 연결의 동시 관측이 두 ID를 만들지 않게 합니다.

Drive에서는 먼저 같은 recordId의 updatedAt을 비교합니다. 같은 수정 시각에 내용이 다르면 복원을 거부합니다. ID가 달라도 같은 주·캐릭터·콘텐츠·관문이면 최초 observedAt의 기록 하나를 유지합니다. 수정 시각이 늦다는 이유로 처음 관측한 시각을 교체하지 않습니다. 관측 시각이 없으면 주차를 추정하지 않고 ID 기준으로만 비교합니다. 공용 이름 별칭은 Store 복원 API에서도 확인합니다.

## DB와 Drive 변환

DB v5는 완료 JSON과 gateNumber=0을 허용하는 제약으로 교체합니다. 변환 전 같은 디렉터리에 `records.sqlite3.pre-v5-<UTC시각>.bak` SQLite 백업을 만들고 WAL까지 포함합니다. 백업 실패 시 변환하지 않습니다. 기존 완료 ID·알려진 시각·보상을 유지하며 전체 수를 모르면 0입니다. 이전 미완료·캐릭터 미확정 체크포인트는 새 완료 테이블로 옮기지 않습니다. 원본은 백업에 남습니다.

Drive는 `{"schemaVersion":5,"records":[...]}` 문서를 사용합니다. 이전 5개/7개 필드 배열은 읽어서 완료만 변환합니다. 새 기록의 모든 필드·메타데이터를 전달합니다. 이전 PC.json 교체 전 파일 원본 bytes를 로컬에 백업하며 PATCH 후 재다운로드를 비교합니다. DB 변환 후 실제 기록이 있으면 새 형식 업로드를 한 번 예약합니다. iOS.json과 iOS 구현은 변경하지 않습니다.

## JSON 예시

다음은 지평의 성당 3단계의 구조 예시입니다. 샘플 캐릭터·ID·시각을 사용하고, 보상은 실제 공용 ContentJSON v16에서 확인한 값입니다. OCR 원문의 contentName을 공용 field_name과 비교한 뒤 공용 name을 저장·표시합니다.

```json
{
  "schemaVersion": 5,
  "records": [
    {
      "recordId": "br2_00000000000000000000000000000001",
      "characterName": "샘플캐릭터",
      "contentName": "지평의 성당",
      "difficulty": "3단계",
      "gateNumber": 1,
      "expectedGates": 2,
      "isTest": false,
      "observedAt": "2026-10-11T04:00:00.000Z",
      "createdAt": "2026-10-11T04:00:00.100Z",
      "updatedAt": "2026-10-11T04:00:00.100Z",
      "ocrOriginal": {
        "difficulty": "3단계",
        "contentName": "구원의 종탑",
        "gateNumber": 1
      },
      "catalogMatch": {
        "status": "matched",
        "fieldName": "구원의 종탑",
        "difficulty": "3단계",
        "version": {
          "id": "1wS_eCrFJrOMdrEH4M-DNoslT1rL8MMOd",
          "version": "16",
          "md5Checksum": "459f9157cb5dd6b4cf2243b52d243863"
        },
        "values": {
          "gold": 20000,
          "fee": 6400,
          "bound_percentage": 1
        },
        "contentName": "지평의 성당",
        "gateNumber": 1
      }
    },
    {
      "recordId": "br2_00000000000000000000000000000002",
      "characterName": "샘플캐릭터",
      "contentName": "지평의 성당",
      "difficulty": "3단계",
      "gateNumber": 2,
      "expectedGates": 2,
      "isTest": false,
      "observedAt": "2026-10-11T04:00:00.000Z",
      "createdAt": "2026-10-11T04:00:00.100Z",
      "updatedAt": "2026-10-11T04:00:00.100Z",
      "ocrOriginal": {
        "difficulty": "3단계",
        "contentName": "구원의 종탑",
        "gateNumber": 2
      },
      "catalogMatch": {
        "status": "matched",
        "fieldName": "구원의 종탑",
        "difficulty": "3단계",
        "version": {
          "id": "1wS_eCrFJrOMdrEH4M-DNoslT1rL8MMOd",
          "version": "16",
          "md5Checksum": "459f9157cb5dd6b4cf2243b52d243863"
        },
        "values": {
          "gold": 30000,
          "fee": 9600,
          "bound_percentage": 1
        },
        "contentName": "지평의 성당",
        "gateNumber": 2
      }
    }
  ]
}
```

matched인 catalogMatch는 status·contentName·difficulty·gateNumber·version·values와 선택 fieldName을 포함합니다. version에는 확보한 id·version·md5Checksum을, values에는 실제 gold·fee·bound_percentage를 넣습니다. unmatched·ambiguous에는 status만 넣습니다. 이전 자료에 없는 메타데이터를 임의로 채우지 않습니다.

## 모듈 경계와 검증

completion_record가 완료 계약 검증·이전 변환·주차·중복 규칙을 소유합니다. storage_schema는 DB 제약과 변환, Store는 백업·영속 기록·업로드 예약·트랜잭션을 소유합니다. ContentMatcher는 이름과 보상 매칭을, native_presentation은 화면용 변환을 맡습니다. RecognitionService는 캐릭터 확정 여부에 따른 분석 순서를 연결합니다.

Python 전체 회귀 466개와 .NET 화면 표시·프로토콜·주간 집계 77개를 통과했습니다. Python에는 새 완료 계약 테스트 16개와 실제 SQLite·스레드 경쟁·WAL 백업·Drive 모의 왕복·실시간 서비스 연결이 포함됩니다. 운영 DB나 실제 게임·Google 서버를 이번 검증에서 실행하지 않았습니다. 앱을 완전히 종료하고 다시 실행하면 변환과 새 탐지 정책이 적용됩니다. 기존 iOS 앱의 새 PC.json 읽기는 후속 구현이 필요합니다.


## field_name 보상 매칭 보완 — 2026-10-11

새 JSON 입력에서도 ocrOriginal.contentName을 공용 field_name과 비교합니다. 저장·표시용 contentName(name)을 화면 이름의 매칭 별칭으로 사용하지 않습니다. 이전 자료에 원문이 없으면 저장된 catalogMatch.fieldName, 이후 contentName 순서로 화면 이름을 찾되 field_name과 정확히 일치해야 합니다.

ContentMatcher.refresh_record_match는 미매칭·복수 후보·매칭 정보가 없는 완료에만 정확하고 유일한 field_name·난이도·관문 보상을 연결합니다. 원문 오타나 공용 field_name 중복은 추정해서 연결하지 않습니다. 이미 matched인 기록은 기존 매칭을 보존합니다. Store.refresh_catalog_matches가 이 변경을 이력·체크포인트에 한 트랜잭션으로 반영하고 실제 기록이면 Drive 전송을 한 번 예약합니다. ID·observedAt·createdAt·expectedGates·OCR 원문은 보존하며 updatedAt만 실제 변경 시 갱신합니다. 다음 호출에서 변경이 없으면 전송을 추가 예약하지 않습니다.

Host는 시작 시 보관된 공용 데이터와 공용 갱신 완료 후 이 공개 API를 연결합니다. 표시 함수에서 SQL을 실행하거나 기록을 수정하지 않습니다. 재시작 또는 공용 갱신 후 기존 미매칭 기록에도 반영됩니다. 지평의 성당 3단계 1·2관문을 실제 공개 ContentJSON v16으로 매칭하고 새 JSON을 검증했습니다. 전체 Python 473개 테스트를 통과했습니다.
