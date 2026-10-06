# OBS 단일 캡처 정리

2026-10-06. 데스크톱 분석과 CLI 이미지 수집은 앱에 포함된 OBS 게임 캡처만 사용한다.

## 제거한 항목

| 범위 | 제거 내용 |
| --- | --- |
| DXGI 모니터 캡처 | `beatrice/capture.py`의 DXCAM 어댑터, 모니터 목록 명령과 장치·출력·지연 옵션 |
| Windows Graphics Capture | `beatrice/windows_capture.py`의 WGC 캡처 클래스, 프레임 콜백·좌표 변환·테두리 설정·재연결 처리 |
| 방식 선택 | 데스크톱 캡처 방식 메뉴·전환 분기·작업자 backend 상태, `config/capture.json` |
| 설치 의존성 | `requirements-capture.txt`, Windows 패키징 목록의 `dxcam`·`windows-capture`, 프로젝트 `.venv-win`의 해당 두 패키지 |
| 이전 검증 도구 | `tests/test_windows_capture.py`, 방식 전환 전용 테스트, `tools/probe_window_capture.py` |
| 이전 안내·산출물 | `docs/49-background-window-capture.md`, README와 기존 문서의 이전 방식 안내·참조, `outputs/window-capture-probe`, 삭제한 모듈의 Python 캐시 |

## 유지·변경한 기능

- 게임 프로세스·창 탐색, 실행 여부, 포커스·최소화 상태 조회는 `beatrice/game_window.py`로 분리했다. OBS가 대상을 식별하는 데 필요한 Windows API이며 별도 화면 캡처 구현은 없다.
- 데스크톱 작업자는 `ObsCapture`만 생성한다. 시작과 정지, 캐릭터·던전 분석, 완료 기록 연결을 유지한다.
- CLI `clients`로 게임 창을 조회하고 `capture --pid ... --timeout ...`로 OBS 프레임을 수집한다. PNG와 창 식별·프레임 수신 정보 JSON을 저장한다. 대상이 여러 개면 명시적으로 선택해야 하며 실패·시간 초과에도 내부 엔진을 종료한다.
- 환경 진단은 앱 소유 OBS 런타임의 경로와 버전을 표시한다. Windows 준비 안내도 내장 엔진 기준으로 다시 작성했다.
- OBS 자체의 DirectX/DXGI 그래픽 처리 DLL과 공식 엔진 대응 소스는 유지했다. 이는 삭제한 DXCAM 모니터 캡처 경로가 아니라 OBS 실행에 필요한 구성이다. 앱이 만드는 캡처 소스는 게임 캡처다.

## 완료 후 재검토

1. 코드·설정·의존성·테스트·도구·문서 전체를 다시 검색해 이전 모듈 import, 선택 메뉴, backend 분기, 설치 안내가 남지 않은 것을 확인했다. 이 정리 문서의 삭제 이력은 검색에서 구분했다.
2. 기존 문서에 남은 모듈 경로와 CLI 안내를 변경하고, 이전 테스트 산출물과 모듈 캐시를 제거했다. 패키징 휠 캐시·기존 EXE는 현재 작업 공간에 없다.
3. 전체 회귀 테스트 **283개 통과**. 샌드박스에서 Windows DPAPI 검사만 실패하여 일반 Windows 권한으로 전체를 재실행했고 모두 통과했다.
4. 내장 OBS의 내부 색상 소스 두 장으로 libobs → BGRA → 공유 메모리 전달과 픽셀 변경을 실측했다. `outputs/embedded-obs-probe/engine-test.json`에 결과를 갱신했다.
5. CLI 도움말·환경 진단과 Git 변경분 공백 검사 통과.

이번 정리는 캡처 구현과 연결·문서에 한정한다. 이 작업에서 YOLO/OCR 모델과 클래스, 완료 기록 DB는 변경하지 않았다. 최신 전체 EXE 재빌드 및 최소화·가림 상태의 실제 게임 통합 검증은 수행하지 않았다. 실행 중인 앱은 완전히 종료하고 새 코드로 재시작해야 반영된다.
