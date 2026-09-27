# WMI 프로세스 이벤트 방식 검토 기록

2026-09-27. **이 방식은 현재 실행 경로에서 제외했다.** 현재 구현은 [주기적 프로세스 확인](35-client-auto-detection.md)을 사용한다.

## 구현했던 방식

- 모델 초기화 후 `Win32_ProcessStartTrace`, `Win32_ProcessStopTrace`를 `ProcessName = 'LOSTARK.exe'` 조건으로 임시 구독했다.
- 구독 직후 Toolhelp 프로세스 스냅샷을 조회했다. 조회 도중 시작된 프로세스도 이벤트 큐로 확인하기 위해 구독을 먼저 했다.
- 별도 스레드에서 `SWbemEventSource.NextEvent(200)`으로 대기했다. 타임아웃은 종료 요청 확인용이며 프로세스 목록 폴링은 아니었다.
- 이벤트 수신 시 현재 프로세스 목록을 조회하여 PID를 갱신했다. 게임 창이 없으면 해당 PID의 창 생성을 별도로 확인했다.
- `comtypes==1.4.16`을 사용했다. 새로고침 시 구독 해제와 감시 스레드 종료 후 새로운 구독을 생성했다. 영구 WMI 구독이나 시스템 권한 변경은 하지 않았다.

## 권한과 배포 판단

현재 PC(Windows 10 Home 22H2, 빌드 19045.7725)에서는 일반 실행의 이벤트 구독이 접근 거부되었고 관리자 실행에서는 성공했다. Windows 11에서 직접 검증하지 않았다. 이벤트 지원 여부와 구독 권한은 별개이며 Windows 버전만으로 관리자 실행 필요 여부를 단정하지 않는다.

관리자 실행을 요구하면 보통 앱을 새로 실행할 때 UAC 승인이 필요하다. 앱 내부 새로고침에는 추가 승인이 필요하지 않다. 배포 편의성과 구현 단순성을 위해 일반 권한의 1초 간격 조회 방식으로 전환했다. CPU·메모리 비교 수치는 측정하지 않았으며 이벤트가 항상 더 가볍다고 주장하지 않는다.

이벤트 및 스냅샷 조회는 실행 정보만 읽는다. 게임 메모리 접근·수정, DLL 주입, 게임 함수 후킹을 하지 않는다. 이 사실이 게임 보안 프로그램의 허용이나 제재 안전성을 보장하지는 않는다.

## 검증과 오류 수정

관리자 권한에서 테스트 프로세스의 실제 이벤트 수신, 대기 타임아웃, 해제 후 재구독을 확인했다. 해당 검증 당시 LOSTARK는 실행되어 있지 않았다.

구독 실패 예외의 traceback에 COM 객체가 남은 상태에서 CoUninitialize를 호출하여 메모리 접근 오류가 발생했다. 객체·예외 참조가 먼저 해제되고 마지막에 감시 스레드의 COM 환경이 종료되도록 수정했다. 수정 후 일반·관리자 권한에서 각각 실제 모델 로딩과 스플래시→메인 화면 3회 반복, 정상 종료 및 감시 스레드 정리를 확인했다.

향후 재도입한다면 구독 전후 실행 경합, 권한 거부, 구독 연결 해제, 새로고침 중 이벤트 전달, COM 객체 해제 순서, Windows 10/11별 실제 권한을 다시 검증해야 한다.

## 공식 참고 문서

- [Win32_ProcessStartTrace: Vista 이상 지원](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/krnlprov/win32-processstarttrace)
- [WMI 이벤트 접근 보안](https://learn.microsoft.com/en-us/windows/win32/wmisdk/securing-wmi-events)
- [NextEvent와 대기 타임아웃](https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemeventsource-nextevent)
- [프로세스 스냅샷 API](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)
