# Beatrice PC

2026-09-23 최신: [전체 관문 현재 상태 저장과 완료 지연 보완](docs/28-whole-gate-state.md). 모든 관문의 최초 상태를 저장하고 전체 배열 변경을 함께 갱신합니다. 완료는 초기화 전까지 고정하며 관문별 현재 행 하나만 유지합니다. 관문 모델도 보완 학습했습니다. 앱을 완전히 재시작해야 적용됩니다.

앞선 수정: [전투·완료 화면의 관문 기록 보완](docs/27-gate-completion-recovery.md).

앞선 수정: [매칭 모드 던전 탐지 보완](docs/26-dungeon-matching-model.md).

2026-09-22 최신: [캐릭터·던전 모델 분리, OCR 속도 개선과 던전 정보 10초 유지](docs/25-role-models-and-stable-context.md)를 활성화했습니다. 앱을 완전히 재시작하면 `캐릭터·던전 분리 탐지`로 실행됩니다. 실제 실패 사례의 앞선 수정은 [진단 기록 재생 결과](docs/24-live-recognition-fixes.md)에 있습니다.

로스트아크 화면에서 관문 상태를 읽고 캐릭터별 완료 기록을 로컬에 저장하는 Windows 앱을 단계적으로 개발합니다. 현재 Windows 실게임 환경에서 인식 동작을 확인하고 있으며, 다양한 화면과 전환 경로는 계속 검증합니다.

현재 저장 정책·실게임 확인·로그 위치는 [전체 관문 현재 상태](docs/28-whole-gate-state.md), 인식 구조는 [역할별 모델과 확정 정보 유지](docs/25-role-models-and-stable-context.md)를 확인합니다. [YOLO·OCR 통합 정리](docs/21-yolo-ocr-current.md)와 이전 단계별 문서는 작성 당시 구현 기록입니다.

이전 전환 단계: [던전 패널 YOLO 전환 준비](docs/22-dungeon-panel-yolo.md).

이전 통합 구성: [캐릭터·전환·던전·관문 통합 YOLO](docs/23-integrated-ui-yolo.md). 현재는 캐릭터 5클래스 모델과 던전 2클래스 모델로 분리했으며 관문 상태 모델은 유지합니다. 현재 해상도(3440×1440)의 기록 재생을 검증했고 다른 해상도 검증은 남아 있습니다. 모델 파일은 로컬에 있으며 Git에 포함되지 않습니다.

최신 OCR: 던전명은 목록 제한 없이 읽고, 실시간 표시는 관문 UI와 난이도 표기를 함께 확인합니다. 난이도/모드 표기는 노말·하드·헬·익스트림·싱글 모드·매칭 모드를 지원합니다. 긴 제목은 넓은 영역에서 공백을 포함한 글자 줄을 추려 읽습니다. 캐릭터명은 PaddleOCR로 레벨을 포함한 줄을 읽고 레벨만 제거합니다. 변경 팝업만 열거나 취소하면 기존 캐릭터를 유지합니다. 팝업 직후 오른쪽 아래 로딩 아이콘과 대기 문구를 함께 관측하면 재확인 상태로 전환하며, 로딩 중 기존 초상화는 재확정하지 않습니다. 맵 이동과 캡처 중단만으로 캐릭터를 초기화하지 않습니다. 실제 미학습 이름과 다양한 전환 경로는 추가 검증이 필요합니다. [기존 검증 기록](docs/19-dungeon-ocr.md).

최신 변경: [캐릭터 미확정 이벤트의 SQLite 임시 저장과 사후 확정](docs/18-deferred-events.md).

## 현재 구현

- YOLO26n 관문 아이콘 탐지, 상태별 개수와 표시 이미지 출력
- 녹화 영상의 연속 관측 안정화, 완료 이벤트 판단
- 실시간 전체 관문 상태의 원자적 저장, 캐릭터·던전·관문별 단일 행 유지와 완료 상태 고정
- 별도 YOLO26n 캐릭터 이름 영역 탐지, PaddleOCR 이름 읽기, 변경 중 기록 보류와 저장 모듈 연결

미등록 던전·다른 화면 환경과 캐릭터 전환의 모든 경로 검증, Google Drive 동기화는 남아 있습니다. 실시간 분석과 앱 UI는 연결되어 있으며 현재 해상도의 사용자 테스트에서 정상 동작하는 것으로 확인했습니다. 초기 문서는 작성 당시 단계의 기록입니다.

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

| 역할 | 코드 / 안내 | iOS 개발에 빗대면 |
| --- | --- | --- |
| Windows 캡처 | beatrice/capture.py, [환경 준비](docs/02-windows-setup.md) | 영상 입력 어댑터 |
| 관문 탐지 | tools/yolo_first.py, [학습·추론](docs/09-first-training.md) | 이미지 분석 서비스 |
| 관문 상태 | beatrice/gates.py | 연속 관측을 처리하는 상태 객체 |
| 이벤트 저장 | beatrice/session.py, beatrice/storage.py, [저장 안내](docs/12-local-storage.md) | 모델 계층과 영속 저장소 |
| 캐릭터 인식 | beatrice/character_vision.py, beatrice/character.py, [연결 안내](docs/16-character-recognition.md) | 문자열 인식과 현재 사용자 상태 |

분석 입력은 BGR 이미지 배열입니다. 한 프레임의 관측과 최종 이벤트는 구분합니다. 실제 이벤트에는 시간대가 포함된 절대 시각을 저장하며, 영상 검증 JSON의 videoSeconds는 영상 안의 위치를 뜻합니다. 학습 이미지 재현 결과를 새로운 영상에 대한 정확도로 해석하지 않습니다.
