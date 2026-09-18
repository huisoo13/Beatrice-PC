# 캐릭터 미확정 이벤트의 임시 저장과 사후 확정

캐릭터 확정 상태의 관문 완료는 바로 저장한다. 캐릭터 미확정 상태에서도 관문 상태를 분석하고, 완료 전환을 확인하면 SQLite의 pending_events에 저장한다. 이후 같은 변경 구간에서 현재 이름을 확인하면 events와 outbox에 확정 기록을 쓰고 임시 기록을 처리 완료로 표시한다. 이 세 작업은 하나의 트랜잭션이다. 임시 기록은 감사·문제 확인을 위해 삭제하지 않으며, 미확정 기록은 업로드하지 않는다.

Swift에 비유하면 `PendingEvent`와 `ConfirmedEvent`라는 두 모델을 영속 저장하는 구조다. 이름 확인은 이벤트 발생 시각을 바꾸는 작업이 아니라 PendingEvent에 소유자를 연결하는 작업이다. observedAt(처음 완료를 관측한 절대시각), confirmedAt(연속 관측으로 완료를 확인한 절대시각), savedAt(처음 보관한 시각)을 유지하고 identityConfirmedAt을 추가한다. 이름 확인 시각으로 완료 시각을 덮어쓰지 않는다.

## 코드 연결

- beatrice/deferred_session.py: 기존 RecordingSession을 확장한 DeferredRecordingSession. 확정 상태는 기존 저장 경로를 사용하고 미확정 상태는 임시 저장 경로를 사용한다.
- beatrice/storage.py: 기존 DB를 버전 2로 확장한다. pending_segments와 pending_events를 추가하며 기존 events와 outbox는 유지한다.
- beatrice/character.py: 새 변경 확인창마다 구간을 나누되, 같은 확인창의 연속 프레임에서는 구간을 반복 생성하지 않는다. 일반 메뉴와 같은 이름이 3회 연속 확인되면 취소 후 기록을 재개한다. Bridge는 이름 확정 직전에 구간을 초기화하지 않고 해당 구간의 임시 이벤트를 확정한다.
- beatrice/character_vision.py: 현재 3440×1440 범위에서 일반 메뉴 영역의 배치를 OpenCV 참조 이미지와 비교한다. 이름은 기존 YOLO26n과 OCR로 읽는다. 이 단계에서는 추가 모델 학습 대신 단순한 배치 비교를 사용했다. UI 배율·해상도·게임 UI 변경에 대한 일반화는 검증하지 않았다.

새 저장 경로의 호출 예:

```python
from beatrice.deferred_session import DeferredRecordingSession

session = DeferredRecordingSession(store)
# 현재 레이드 진행 정보는 별도 판단 결과로 전달한다.
run = dict(session_id="현재 진행의 고유 ID", expected_gates=2,
           time_basis="live_capture", is_test=False, source_id=None)
session.prepare_pending_run(**run)
# 캡처 시점의 시간대 포함 datetime과 당시 token을 사용한다.
result = session.observe(captured_token, captured_at, gate_boxes)
# 같은 구간의 ESC 메뉴 이름이 안정화된 뒤 Bridge가 호출한다.
session.confirm_character(character_key=verified_key,
                          character_name=verified_name, **run)
```

캐릭터 변경 후 이전 캐릭터의 레이드 진행 ID를 자동 재사용하지 않는다. 보류 구간의 진행 ID·관문 수·시각 기준은 prepare_pending_run으로 지정한다. 이 정보 없이 들어온 관문 관측은 pending_run_context_required를 반환한다. 던전 문맥 자동 인식과 Windows 실시간 입력 연결은 기존 미완료 단계이며 이번 변경으로 완성된 것은 아니다. 현재 예제 명령에서는 진행 정보를 인자로 전달한다.

다음 변경 전에 이름을 읽지 못한 경우 이전 구간의 이벤트는 미확정으로 남는다. 다음 캐릭터에게 배정하지 않는다. 앱 재시작 후에도 임시 이벤트는 DB에 남지만, 중단 중 캐릭터 변경 여부를 알 수 없으므로 이전 구간을 새로 읽은 이름에 자동 연결하지 않는다. Store.pending_records()로 확인할 수 있으며 이후 복구 UI/근거 기반 연결이 필요하다. 살아 있는 같은 구간의 사후 확정은 자동으로 동작한다.

## 실행한 검증

총 36개 테스트가 통과했다. 확정 상태 바로 저장, 임시 저장 후 확정, 원래 시각 유지, 동일 캐릭터·진행·관문 중복 방지, 변경 구간 간 격리, 재시작 후 임시 기록 보존, DB 버전 1 데이터 유지, 임시 저장 실패 및 확정 트랜잭션 실패 후 재시도를 확인했다.

새 영상 `Lost Ark 2026.09.17 - 11.25.37.01.mp4`를 다시 86회 분석했다:

| 영상 위치 | 실제 인식 상태 |
| --- | --- |
| 2.516초 | 후이수 확정 |
| 6.015초 | 변경 시도, 보류 시작 |
| 12.014초 | 취소 후 일반 메뉴의 후이수 재확정·재개 |
| 18.012초 | 다음 변경 시도, 새 보류 구간 |
| 38.007초 | 테베체 확정·재개 |

결과: outputs/character-recognition/followup0917-resume.json. 이 영상에는 관문 완료가 없으므로 임시 이벤트 확정까지 실제 게임 영상 하나로 확인한 것은 아니다.

별도로 기존 video002의 실제 관문 탐지 결과에 테스트 이름과 테스트 녹화 시작 시각을 넣었다. 10.216초의 완료 이벤트를 임시 저장하고, 이름 확인을 20초로 지연 주입해 1건을 확정했다. 한국 시각 2026-09-17 10:00:10.215767의 완료 시각이 유지되며 DB에는 UTC로 저장된다. 재실행 시 추가 확정 기록은 0건이었다. 테스트 기록은 test_only로 업로드에서 제외된다.

```bash
.venv-ml/bin/python -m unittest discover -s tests -v
.venv-ml/bin/python tools/store_video_events.py outputs/video002/observations.json \
  --db outputs/deferred-demo.sqlite \
  --character-key test:deferred-A --character-name 테스트캐릭터 \
  --session-id deferred-demo --expected-gates 2 \
  --recording-start '2026-09-17T10:00:00+09:00' \
  --test-data --identity-confirmed-at 20
```

identity-confirmed-at은 테스트용 이름 확정 시점 주입 옵션이며 실제 OCR 결과를 뜻하지 않는다. 분석 결과는 outputs/deferred-demo.json, 재실행 결과는 outputs/deferred-demo-repeat.json에 저장했다. 현재 보관하는 이벤트 증거는 관문 박스·상태·신뢰도이며 원본 이미지 자동 보관은 추가하지 않았다.
