# Windows 개발 환경과 OBS 게임 캡처

Windows x64, Python 3.11 개발 가상환경을 사용합니다. 앱이 포함하는 OBS 엔진을 사용하므로 OBS Studio 설치는 필요 없습니다.

```powershell
py -3.11 -m venv .venv-win
.venv-win/Scripts/python.exe -m pip install -r packaging/requirements-windows.txt
.venv-win/Scripts/python.exe packaging/prepare_obs.py
.venv-win/Scripts/python.exe -m beatrice doctor
```

엔진 준비 도구는 공식 OBS 배포물의 해시를 확인하고 프로젝트의 `build/obs-runtime`에 필요한 모듈과 대응 소스를 준비합니다. 앱의 기존 YOLO/OCR 모델도 별도로 준비되어 있어야 합니다.

현재 데스크톱 UI는 WinUI 3입니다. .NET 8 SDK로 `./ui/Beatrice.App/build.ps1`을 실행해 UI를 빌드한 뒤 `Run-Beatrice.cmd`를 사용합니다. 분석 초기화 진행률은 새 창 상단에 표시합니다. [UI 구조·테스트·배포 방법](58-winui-desktop.md)을 참고하세요.

## 이미지 한 장 수집

```powershell
.venv-win/Scripts/python.exe -m beatrice clients
.venv-win/Scripts/python.exe -m beatrice capture --pid 1234 --timeout 15 --directory data/raw
```

`1234`를 목록의 게임 PID로 바꿉니다. 게임 창이 하나면 `--pid`를 생략할 수 있습니다. 새 OBS 게임 프레임을 PNG로 저장하며 옆의 JSON에 창 식별 정보와 수신 시각을 남깁니다. 기존 파일을 덮어쓰지 않습니다. 게임과 앱의 실행 권한이 같아야 연결할 수 있습니다.

데스크톱 앱은 스플래시에서 모델과 내장 OBS 엔진을 준비한 뒤 자동으로 게임을 분석합니다. 게임이 없으면 메인 화면에서 기다렸다가 감지되면 자동 연결합니다. 시작·정지 버튼은 없습니다. 프로젝트의 `Run-Beatrice.cmd`로 실행하면 관리자 권한을 요청합니다. Windows UAC를 승인한 뒤 사용합니다. 프레임이 중단되면 이유를 표시하고 대기합니다. 최소화 중 게임 자체의 렌더링이 멈추면 새로운 관측을 만들지 않습니다.

[내장 OBS 구조·실측·배포 안내](50-embedded-obs.md)를 참고하세요. 배포 스크립트는 준비한 엔진을 앱에 포함하며, 최신 구성의 전체 EXE 재빌드 및 별도 PC 검증은 아직 완료하지 않았습니다.
