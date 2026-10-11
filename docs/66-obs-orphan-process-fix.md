# OBS 재연결 실패와 잔여 프로세스 정리 (2026-10-11)

## 확인한 증상

16:08~16:10 실행에서 YOLO/OCR 및 내장 OBS 초기화는 성공했으나 `init_pipe: failed to start pipe`가 반복되었다. 같은 시점에 14:38:35/41 실행의 Python 프로세스 체인 52124 → 52532 → 31540 → 18712가 남아 있었다. 16:57 기록에도 이전 엔진에서 누적된 sequence 167076 프레임이 들어왔다. 설치된 OBS Studio는 사용하지 않았다.

15:38 기록 갱신 예외가 남아 있었고, native_bridge의 이벤트 루프 예외 경로가 instance lock만 해제하고 작업자를 중지하지 않는 결함을 확인했다. 비정상 종료 후 기존 캡처가 살아 있어 새 실행의 게임 연결 파이프와 충돌할 수 있는 경로다. OBS 원문 오류는 Windows 오류 번호를 포함하지 않아 당시 파이프 서버 소유 PID를 직접 확정하지는 못했다.

## 수정

- native_bridge는 예외에서도 Host shutdown API를 호출하고 분석 작업자 종료를 기다린 뒤 저장소와 instance lock을 정리한다.
- EngineProcessLifetime은 UI 소유 Windows Job에 분석 프로세스와 OBS 자식을 묶는다. 정상 종료는 기존 정리를 기다리고 UI 강제 종료 시 Job이 잔여 프로세스를 종료한다.
- process_lifetime.join_owner_job은 모델 import 전에 실제 Python을 같은 Job에 연결한다. venv redirector가 먼저 생성한 Python도 빠지지 않도록 한다. Job 핸들은 상속하지 않는다.
- OBS stderr를 상태 수신 스트림으로 전달해 원문 로그를 보존하고 파이프 생성 실패를 화면에 표시한다. 새 실행 로그에는 엔진 PID·부모 PID·공유 메모리 식별자를 기록한다.

## 검증

- 타이머 예외를 실제 별도 Python 프로세스에서 발생시켜 작업자 중지와 instance lock 해제를 검증했다.
- 실제 venv Python이 Job에 참여한 뒤 생성한 자식이 Job 종료 시 함께 종료되는 것을 검증했다.
- 실제 앱 내장 libobs에서 정상 화면·스플래시 종료 모두 자식 종료 코드 0, 캡처 자원 해제, 상태 스레드와 감시자 종료를 확인했다. 게임이나 네트워크에 연결하지 않는 격리 검증이다.
- Python 499개, .NET 90개 검증 통과. WinUI Release publish 성공. 기존 NU1900 네트워크 경고 외 빌드 오류 없음.

## 기존 실행의 정리 한계

수정 전 관리자 권한 실행의 잔여 PID 52124, 52532, 31540, 18712 종료를 시도했으나 Windows 접근 거부가 발생했다. 새 Job은 이미 실행 중인 이전 프로세스에 소급 적용되지 않는다. 관리자 작업 관리자에서 해당 PID를 확인·종료하거나 Windows를 재시작한 뒤 수정 앱을 실행해야 한다. 현재 세션에서는 게임 재연결을 최종 검증하지 못했다.

## 실제 게임 재검증

사용자가 이전 잔여 PID를 종료한 뒤 수정 앱의 정상 시작과 종료를 확인했다. 이후 프로세스 목록에서 BeatricePC, Python 분석·OBS 엔진, inject-helper32/64가 모두 없는 것을 확인했다. 최신 OBS 로그에서도 shared texture capture successful 이후 capture stopped 및 소스 해제가 기록됐다. 기존 실행 정리 이후 실제 게임 연결부터 정상 종료까지 재검증 완료. 최종 단일 실행 패키지 자체의 실행 검증은 별도다.
