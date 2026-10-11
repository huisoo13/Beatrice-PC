# ContentJSON 배열 구조와 던전 이름 매칭

최종 갱신: 2026-10-11.

## 데이터와 책임

원격 ContentJSON은 던전 배열이다. 각 던전에는 name(저장·표시 이름), field_name(게임 화면 OCR 비교 이름), difficulties가 있다. 난이도에는 name·gates가 있고 관문에는 number·gold·fee·bound_percentage가 있다.

```json
[
  {
    "name": "지평의 성당",
    "field_name": "구원의 종탑",
    "difficulties": [
      {
        "name": "3단계",
        "gates": [
          {"number": 1, "gold": 20000, "fee": 6400, "bound_percentage": 1},
          {"number": 2, "gold": 30000, "fee": 9600, "bound_percentage": 1}
        ]
      }
    ]
  }
]
```

ContentCatalog(content)는 신규 배열과 이전 던전명→난이도→관문 객체를 검증하고 공통 인덱스로 제공한다. public_content.validate_content와 ContentError import는 호환 진입점으로 유지한다. 이전 캐시는 다운로드 실패·오프라인에서도 계속 읽을 수 있으며 정상 갱신 시 새 원본 형식으로 교체된다. 원격 JSON은 수정하지 않는다.

ContentMatcher는 이름 비교와 기록 별칭을 소유한다. Store는 매칭 결과를 사용해 저장·주간 중복 검사만 담당한다. CatalogService.rows는 ContentCatalog.rows로 name 기반 보상표를 제공하고, native_presentation은 매칭기의 공개 API로 기록·하단 표시 데이터를 만든다. Host는 동일 매칭기를 전달해 전체 기록마다 인덱스를 반복 구성하지 않는다. WeeklySummary는 엔진이 전달한 name을 사용하며 JSON 구조를 직접 해석하지 않는다.

## OCR·새 기록

- OCR 던전명은 field_name에만 비교한다. 공백·구두점 정규화와 기존 보수적인 오탈자 보정을 유지한다. 챕터·단계 숫자가 다르면 보정하지 않는다.
- 하나의 field_name에만 대응하면 던전명은 name으로 저장한다. 난이도·관문 보상 매칭의 성공 여부와 이름 변환은 별개다.
- 후보가 없거나 여러 개여서 모호하면 OCR 원문을 그대로 저장한다. name 자체를 별도 OCR 별칭으로 사용하지 않는다.
- ocrOriginal에 원문을 남기고, 정상 보상 연결에는 fieldName·name·난이도·관문·저장 당시 보상·버전을 남긴다. 보류 기록 귀속에서는 최초 매칭 결정을 유지한다.
- 실제 필드 구원의 종탑 → name 지평의 성당이 기록·하단 이름·보상표·주간 현황에 연결된다.

## 기존 기록·주간 중복

기존 기록의 DB 이름, recordID, updatedAt과 저장 시각을 일괄 재작성하지 않는다. 표시할 때 저장된 name, 이전 field_name, 저장된 fieldName과 OCR 원문의 정확한 별칭을 확인해 현재 name으로 표시한다. 같은 필드의 표시 name이 바뀌어도 현재 주의 완료 체크포인트가 새 완료로 중복 저장되지 않는다. 이전 기록과 새 기록은 같은 표시명으로 주간 집계된다.

새 완료 기록의 contentName과 PC.json 내보내기는 name을 사용한다. 기존 ID·시각·이름과 fieldName·OCR 별칭을 보존한다. 후속 [완료 기록 계약](63-completion-record-schema.md)에서 DB v5·Drive JSON v4와 catalogMatch.gateNumber로 전환했다. iOS 소스는 이 저장소에 없으므로 기존 이름의 표시·집계와 ContentJSON 배열 읽기는 iOS에서도 별도 적용이 필요하다.

기존 정상 보상 연결은 fieldName이나 이전 이름으로 현재 보상을 조회한다. 현재 공용 데이터에서 연결이 사라지거나 모호하면 저장 당시 보상을 유지한다. 이전에 unmatched·ambiguous로 저장된 보상 결정을 후대에 자동으로 추측해 덮어쓰지 않는다. 현재 데이터에 직접 연결할 수 있는 이전·Drive 가져오기 기록은 정확한 별칭으로 보상을 조회한다. 주간 현황은 기존 일반/귀속 골드 계산 정책을 유지하며 더보기 fee는 자동 차감하지 않는다.

## 검증

- 전체 Python 테스트 450개 통과. 신규 tests/test_content_catalog.py에서 두 스키마, field_name 전용 비교, 이름/보상 매칭 분리, 모호성, 이전 이름·새 이름 중복, 이름 변경, Drive 내보내기, 기존 보상 연결과 캐시 교체를 확인했다.
- .NET 표시·엔진 프로토콜·주간 현황 검사 77개 통과. 별도 UI 배치 변경 없이 엔진의 dungeon 라벨을 name으로 통일했다.
- 실제 새 Drive JSON: 던전 10개·난이도 30개·관문 63개 조회. 63개 전체 field_name→name·난이도·관문 보상 매칭 통과.
- 실제 CatalogService + 별도 테스트 DB에서 구원의 종탑→지평의 성당 저장, 주간 표시용 dungeon 라벨과 20,000 골드 연결, 재관측 중복 차단, 미등록 OCR 유지와 테스트 기록 내보내기 제외를 확인했다.
- 기존 EmblemJSON·Drive PNG 2개·CDN SVG 38개 캐시 갱신·재사용도 통과했다. 운영 기록이나 개인 Drive 파일은 변경하지 않았다.

검증 캐시는 outputs/content-schema-review와 outputs/public-content-check에 보관하며 Git에서 제외한다.

## 원본 표기 수정 확인

2026-10-11 원격 JSON을 다시 받아 3막의 name과 field_name이 모두 `3막: 칠흑, 폭풍의 밤`으로 수정된 것을 확인했다. 새 기록과 보상표는 수정된 name을 사용하며, 이전 `퐁풍의 밤` OCR도 기존 오탈자 보정으로 현재 필드에 연결된다. 별도 메모리 DB에서 이전 표기의 완료 기록이 수정된 표기의 재관측을 중복으로 차단하고, 기존 기록의 ID·시각·본문은 그대로 유지되는 것을 확인했다.

기존 기록 표시는 정확한 별칭만 사용하므로 name과 field_name을 함께 바꿔 이전 별칭이 사라진 경우 기존 `퐁풍의 밤` 표기를 유지한다. 이 경우 표시 보정이나 데이터 이관은 별도 정책이 필요하며, 원본 갱신만으로 기록을 재작성하지 않는다.


2026-10-11 후속 보완: 새 완료 JSON의 ocrOriginal.contentName을 field_name으로 비교합니다. ContentMatcher.refresh_record_match와 Store.refresh_catalog_matches는 기존 미매칭 기록에 정확히 확인한 보상을 연결합니다. 공용 name인 contentName은 저장·표시용이며 화면 이름의 인식 별칭으로 사용하지 않습니다. 기록 ID·관측 시각·생성 시각은 유지하고 updatedAt과 Drive 전송 예약만 갱신합니다. [완료 기록 계약과 실제 지평의 성당 JSON](63-completion-record-schema.md)을 참고합니다.
