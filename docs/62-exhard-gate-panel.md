# EX 하드 단일 관문 영역 탐지 보강

2026-10-08. `3막: 칠흑, 폭풍의 밤 / EX 하드`의 단일 관문을 던전 요소 YOLO 추가 학습으로 보강했다.

## 누락 원인

21:40~22:05의 EX 하드 관측 2,216회에서 던전명·난이도는 읽었지만 최종 관문 목록은 비어 있었다. 22:05 완료 화면을 재생하면 개별 완료 아이콘은 약 97.5%로 검출됐으나 `gate_panel`은 기준 70%에 미달했다. `detected_gates`는 전체 관문 영역과 그 안에 포함된 개별 아이콘을 함께 요구하므로 아이콘을 제외했다. 관문 수가 확정되지 않아 완료 문맥과 배너 분석도 시작되지 않았다.

## 학습과 적용

- 기존 요소 학습 72장과 EX 하드 실제 패널 17장(진행 중 14장·완료 3장)을 합친 89장으로 학습했다. 관문 전체 영역·이름·난이도·개별 아이콘을 시각적으로 검토했다.
- 최초 12장을 추가해 18 epoch 학습한 뒤 진행 중의 유사 장면 5장을 더해 8+6 epoch 보강했다. 첫 후보에서는 미학습 샘플 1장이 실패해 활성화하지 않았다.
- 입력 512, CPU, freeze 10, batch/nominal batch 2, AdamW를 사용했다. 학습률은 순서대로 0.0003·0.0002·0.0001이며 후속 학습은 warmup 없이 실행했다.
- `models/dungeon-elements.pt`와 설정의 학습 이력·SHA-256만 교체했다. 7개 클래스, 관문 영역 기준 0.7 및 다른 클래스 기준, OCR 판단·완료 저장 규칙은 유지했다.
- 캐릭터명·던전 부모 패널·완료 연출 모델은 변경 전후 해시가 동일하다. 좌표는 학습 라벨에만 있으며 실행 경로에 고정 좌표나 EX 하드 이름 예외를 추가하지 않았다.
- 활성 모델 SHA-256: `00a6b58fb40caff4a0582040ca75e60ff95e3eb8976350854be3afc9dd1f75b7`.

학습 라벨은 `data/annotations/dungeon-elements-exhard-1008.json`, 강화 라벨은 `data/annotations/dungeon-elements-exhard-reinforced-1008.json`이다. 모델·원본 이미지·데이터셋·검사 결과는 기존 정책대로 로컬에 보존한다. 교체 전 모델과 설정은 `outputs/exhard-review-1008/baseline-dungeon-elements.*`에 백업했다.

## 검증

| 검사 | 결과 |
|---|---|
| 기존 요소 72장 | 이전 72/72 → 신규 72/72, 퇴행 0 |
| EX 하드 실제 전체 화면 29장 | 이전 0/29 → 신규 29/29 |
| 위 검사 중 학습에 넣지 않은 같은 세션 12장 | 신규 12/12 |
| 마지막 완료 화면 관문 영역 | 88.0%, 완료 관문 1개 인식 |
| 최종 EX 하드 실제 OCR·저장 재생 21장 | 메모리 DB에 EX 하드 1관문 완료 저장 |
| 벨가르딘 실제 OCR·저장 재생 40장 | 1·2관문 완료 유지 |
| 종탑 실제 OCR 재생 6장 | 6/6 통과, 검은 화면은 음성 처리 |
| 전체 Python 회귀 테스트 | 342개 통과 |

학습에 넣지 않은 12장도 같은 플레이에서 가져왔으며 모델 선택 과정에 사용했다. 독립 세션의 정확도 측정은 아니다. 실제 OCR·저장은 메모리 DB로 검사했으며 사용자 기록 DB나 Drive를 변경하지 않았다.

검사 도구는 `tools/prepare_exhard_elements.py`, `tools/evaluate_exhard_elements.py`, `tools/replay_exhard_completion.py`다. 최종 JSON과 로그는 `outputs/exhard-review-1008/`의 `element-comparison-final.json`, `completion-replay-final.json`, `belgardin-replay-final.json`, `tower-replay-final.json`, `tests-final.log`에 남겼다. 교체 후 비교를 다시 실행할 때는 `--baseline-weights outputs/exhard-review-1008/baseline-dungeon-elements.pt`를 지정한다.

앱을 완전히 종료하고 재실행해야 새 요소 모델을 불러온다. 2026-10-09 사용자가 실제 게임 테스트 완료를 보고했다. 후속 완료 판단 변경과 검증 범위는 [완료 배너 재확인](63-completion-gate-recheck.md)을 참고한다.
