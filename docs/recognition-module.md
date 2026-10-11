# 실시간 인식 모듈

2026-10-10

`beatrice.recognition`에서 OBS 실행·연결·새 프레임 처리와 YOLO/OCR 인식을 호출한다. 동일 앱 프로세스의 백그라운드 스레드에서 실행하며, 기존 앱 내장 OBS 보조 프로세스만 사용한다.

## 구성

| 구성 | 책임 |
|---|---|
| `RecognitionPipeline` | 모델 준비, 한 프레임의 캐릭터·던전·관문·완료 표시 인식 |
| `FrameRecognition` | 캐릭터·던전·관문 원시 관측과 분석 시각 |
| `RecognitionService` | OBS 준비·클라이언트 연결·실시간 루프·진단·종료 처리 |
| `RecognitionEvents` | 준비 진행, 결과, 오류, 연결 상태를 전달하는 일반 Python 콜백 |
| `engine_worker.Worker` | 서비스 실행을 Python 스레드·콜백에 연결하는 어댑터 |

파이프라인은 UI·OBS·SQLite·Google Drive를 호출하지 않는다. 서비스는 기존 `DungeonTracker`, `LiveCoordinator`, SQLite 세션에 관측을 전달하여 완료 판단·저장 정책을 유지한다. Google Drive와 외부 API는 인식 모듈의 의존성이 아니다. 기본 인식 모듈 import는 Qt·YOLO·Paddle·OpenCV 모델을 로드하지 않으며 실제 준비 시 로드한다.

## 앱 없이 서비스 호출

```python
from pathlib import Path
from threading import Thread
from beatrice.recognition import RecognitionEvents, RecognitionService

root = Path("C:/path/to/Beatrice-PC")  # 기존 모델·설정이 있는 앱 루트
service = RecognitionService(
    root, Path("C:/path/to/app-data"),
    RecognitionEvents(
        progress=print,
        ready=lambda clients: print("연결 가능한 클라이언트:", clients),
        observation=lambda state: print(state["recordingStatus"]),
        status=lambda generation, message: print(message),
        failed=print,
    ),
)
thread = Thread(target=service.run, name="recognition")
thread.start()
# 종료 시:
service.stop()
thread.join()
```

콜백은 실행 서비스 스레드 또는 프로세스 감시 스레드에서 호출된다. UI를 갱신할 때는 해당 UI의 스레드 전달 방식을 사용한다. 기존 앱 어댑터는 Python 스레드에서 발생한 콜백을 `EventLoop`의 큐로 전달한다. 앱 브리지와 Store는 루프 소유 스레드에서만 처리한다. 무거운 작업이나 예외를 콜백에 넣지 않는다.

`select(generation, client)`는 기존 Client를 선택하고, `select(generation, None)`는 연결을 해제한다. 세대 번호는 증가시킨다. `requested()`는 현재 선택을 돌려준다. 실행은 서비스 인스턴스당 하나의 스레드에서 수행하며 종료 후 재시작은 새 인스턴스를 만든다. `stop()`은 OBS 준비 대기·프레임 대기·실행 루프를 중단한다. 이미 실행 중인 모델 로딩·동기 추론은 반환 후 중단 요청이 반영된다.

## 캡처 없이 한 프레임 분석

```python
import time
from beatrice.recognition import RecognitionPipeline

pipeline = RecognitionPipeline(root, progress=print)
pipeline.prepare()
result = pipeline.analyze(
    frame, time.monotonic(),  # OpenCV BGR 배열
    confirmed_name='확정된캐릭터명',
    completion_enabled=False,
)
print(result.character, result.dungeon, result.gates)
```

`confirmed_name=None`이면 캐릭터만 분석하며 던전·관문·배너는 분석하지 않습니다. 실시간 서비스는 `analyze_character(frame, seconds, confirmed_name)`의 `(regions, identity, detected_at, character_at)`를 캐릭터 추적기에 먼저 전달한 뒤, 확정된 경우만 `analyze_dungeon(frame, regions, identity, seconds, completion_enabled, still_current)`를 호출합니다. 이 API는 `(dungeon, gates)` 또는 이전 선택이 된 경우 `None`을 반환합니다.

`completion_enabled`는 상위 로직에서 현재 던전 문맥을 확정했을 때만 켠다. `still_current` 콜백으로 클라이언트 변경 여부를 검사할 수 있다. 분석 중 선택이 바뀌면 `None`을 반환하여 이전 클라이언트의 관측을 저장하지 않는다. 분석 결과 자체가 완료 기록은 아니며 기존 반복 확인·문맥 검증 경로를 거쳐야 한다.

## 유지한 동작과 검증

- 스플래시의 모델·OCR 준비 → 내장 OBS 준비 → 클라이언트 연결 순서와 자동 분석.
- 콜백의 기존 결과 형식, 세대 번호, 분석 시간, 캐릭터·던전 진단.
- 짧은 OBS 대기에서는 후보 유지, 실제 캡처 중단에서는 연속 확인 후보 초기화.
- 관문 배너 재확인, 완료 아이콘 반복 확인, 중복 방지. 기록 형식은 [완료 JSON v4](63-completion-record-schema.md)로 갱신했습니다.
- 종료·준비 취소·OBS 오류에서 캡처·DB 자원 정리. 캡처 정리가 실패해도 DB와 감시 스레드 정리를 수행.
- 모듈 경계 테스트 10개: UI·모델의 지연 로딩, 메뉴 중 완료 분석 차단, 분석 중 선택 변경 폐기, 준비 취소·실패, UI 없이 실제 SQLite 완료 저장, 종료 정리.
- 전체 Python 테스트 400개 통과. 모델 출력 모의 입력과 실제 완료 판단·DB를 연결한 통합 검증이며 이번 작업에서 실제 게임 캡처를 새로 실행하지 않았다.

모델 가중치·클래스·신뢰도 기준과 제목 확인 실패 시 관문 결과를 제외하는 기존 정책은 변경하지 않았다. 앱을 완전히 종료하고 다시 실행하면 분리된 모듈이 사용된다.

## Qt 의존성 완전 제거

인식 작업자는 `threading.Thread`로 실행하고, `Event`는 일반 Python 콜백 등록·전달만 담당한다. `native_bridge.Host`는 작업자 콜백을 `queue.Queue`를 사용하는 `EventLoop`로 넘겨 UI 프로토콜과 SQLite 접근을 한 스레드에 유지한다. 50ms 명령 처리와 1초 상태 갱신 타이머도 이 루프가 처리한다. 재시작된 이전 작업자의 대기 콜백은 폐기한다.

중복 실행 방지는 `InstanceLock`이 담당한다. Windows에서는 `msvcrt`의 OS 파일 잠금을 사용하며 정상 종료·강제 프로세스 종료 후 해제된다. Windows의 종료 직후 해제 지연을 고려해 최대 250ms 동안 짧게 재시도한다. 잠금 파일이 남아 있는 것 자체는 실행 중을 뜻하지 않는다.

PySide6-Essentials 요구사항과 Qt 플러그인 필수 배포 목록을 제거했다. 빌드는 이전에 다운로드된 PySide6·Shiboken 휠도 제외하며, VC 런타임은 내장 Python·수치 라이브러리·WinUI 배포 파일 또는 `build/vc-runtime`에서 확보한다. 누락 시 빌드가 명시적으로 실패하며 Qt 휠에 의존하지 않는다. 패키지 검증은 PySide6·Shiboken 파일이 있으면 실패한다. 이 작업에서 새 배포 EXE를 빌드하지는 않았다.

추가 검증:

- 실제 UTF-8 파이프 프로토콜에서 재시작·기록 삭제·Drive 복원·부모 입력 EOF 종료 통과.
- 백그라운드 콜백 순서와 루프 소유 스레드 실행, 타이머 취소, 실패 후 종료 알림, 이전 작업자 콜백 폐기 통과.
- 별도 프로세스의 잠금 경쟁 차단, 정상 해제와 강제 종료 후 재취득 통과.
- `native_bridge` import에 PySide6·Shiboken 로드 없음.
- 게임과 네트워크에 연결하지 않는 격리 데이터로 실제 앱 내장 OBS 실행·종료 검증. `tools/probe_app_shutdown.py --mode main`과 `--mode splash` 모두 통과했다. 두 검사에서 OBS 자식 exitCode 0, 작업자·프로세스 감시·OBS 상태 스레드 종료, 캡처 자원 해제를 확인했다. 인식 모델은 이 종료 검사에서 모의 객체를 사용했다.
- 검사 결과: `outputs/embedded-obs-probe/shutdown-main.json`, `shutdown-splash.json`.

로컬 개발 가상환경에 이미 설치된 PySide6 패키지는 제거하지 않았으며, 실행 코드·요구사항·향후 배포에는 사용하지 않는다. 과거 문서의 Qt 설명은 당시 구현 이력이다.


2026-10-11 변경: 캐릭터 미확정 상태의 던전 분석과 소급 기록을 제거했습니다. 캐릭터가 던전 안에서 확정돼도 해당 프레임부터 던전 관측을 시작하며, 완료 아이콘은 새 반복 확인을 거쳐 저장합니다. OBS 캡처와 캐릭터 모델은 계속 실행됩니다. 새로운 완료·Drive 계약과 검증 결과는 [완료 기록 정리](63-completion-record-schema.md)에 있습니다.
