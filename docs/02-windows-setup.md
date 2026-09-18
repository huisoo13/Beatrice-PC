# 2단계: Windows 환경 준비와 한 장 캡처

## 기준과 확인 범위

개발 기준은 **Windows x64 + Python 3.11 64비트**입니다. 현재 Mac에는 Python 3.9.6만 확인되어 준비 도구용 `.venv`를 만들었습니다. Windows용 라이브러리를 Mac에서 실행한 것으로 간주하지 않습니다. Windows ARM이나 구체적인 GPU 조합은 아직 확인하지 않았습니다.

2026-09-10 공식 문서 확인 결과, [dxcam 0.3.0](https://pypi.org/project/dxcam/)은 Python 3.10 이상이며 CPython 3.11 Windows x64 wheel(미리 빌드한 설치 파일)을 제공합니다. [PyTorch](https://pytorch.org/get-started/locally/)도 Python 3.10 이상을 안내하고, [Ultralytics](https://pypi.org/project/ultralytics/)의 명시된 최소 버전도 3.11을 포함합니다. 이 교집합에서 3.11을 선택했으며 **전체 의존성 설치·실행 호환성은 미검증**입니다.

이번에는 `dxcam[cv2]==0.3.0`만 Windows 설치 후보로 고정했습니다. OpenCV는 이미지 저장과 이후 전처리에 사용합니다. 간접 의존성까지 잠근 lock 파일은 아직 없습니다. 실제 Windows에서 설치와 캡처가 성공하면 `pip freeze` 결과를 보관합니다. YOLO/PyTorch는 학습 단계에 실제 GPU와 드라이버를 확인하고 설치 조합을 결정합니다. OCR은 실제 필드가 확정되기 전 설치하지 않습니다.

## Windows PowerShell에서 실행

[Python 공식 배포 페이지](https://www.python.org/downloads/windows/)에서 Python 3.11 64비트를 준비한 뒤 프로젝트를 Windows로 복사합니다. Mac의 `.venv`는 복사하지 않습니다. PowerShell에서 복사한 프로젝트 폴더를 열고 아래를 실행합니다.

```powershell
py -0p
py -3.11 --version
py -3.11 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install --upgrade pip
.\.venv-win\Scripts\python.exe -m pip install -r requirements-capture.txt
.\.venv-win\Scripts\python.exe -m pip check
.\.venv-win\Scripts\python.exe -m beatrice doctor
.\.venv-win\Scripts\python.exe -m beatrice monitors
```

가상환경의 Python 경로를 직접 실행하므로 PowerShell 실행 정책을 변경하거나 activate 스크립트를 실행할 필요가 없습니다. `py -3.11`이 실패하면 3.11 설치부터 확인합니다. 설치 실패 시 오류 원문을 남겨주세요. `pip check`는 패키지 간 선언된 버전 충돌을 검사할 뿐, 실제 게임 캡처 성공을 의미하지 않습니다.

모니터 목록의 device/output 번호를 보고 선택합니다. 아래의 0은 예시 기본 장치입니다.

```powershell
.\.venv-win\Scripts\python.exe -m beatrice capture --device 0 --output 0 --delay 5
```

명령 뒤 5초 안에 게임 화면으로 전환합니다. 결과는 `data/raw/`의 UTC 시각 파일명 PNG와 JSON입니다. PNG를 열어 게임 화면, 색상, 잘림, 아이콘 디테일을 확인합니다. JSON에는 이미지 크기와 장치 번호, 프레임 수신 시각이 담깁니다. 게임 내부 이벤트 시각은 아닙니다. 기존 원본을 덮어쓰지 않습니다.

**현재 기능은 모니터 전체 캡처**입니다. 특정 게임 창을 찾아 따라가지 않습니다. 창 모드에서 창이 움직이면 이미지 속 게임 위치도 바뀝니다. PNG에는 같은 모니터의 다른 창도 포함될 수 있으므로 학습 데이터로 쓰기 전 내용을 확인합니다. 새 프레임이 없으면 최대 약 3초 재시도 후 오류를 표시합니다(드라이버 내부 호출 지연은 별도). 단발 명령이므로 Alt+Tab 중 캡처 세션을 계속 유지하는 내구성은 이후 실시간 단계에서 검사합니다.

## 실제 PC에서 확인할 표

각 항목을 별도 PNG로 남기고 `data/manifest.csv`의 notes에 조건과 결과를 적습니다. 최초 상태는 모두 미검증입니다.

| 조건 | 확인할 결과 |
| --- | --- |
| 선택한 화면 모드에서 정상 게임 | 검은 화면·이전 프레임·색상 이상 여부 |
| 지원할 창/테두리 없는 창/전체 화면 후보 | 실제 캡처 가능 여부; 초기 지원 모드는 하나로 제한 |
| Alt+Tab 후 복귀 | 복귀 후 새 명령으로 캡처 가능 여부 |
| 게임 창 이동 | 위치·테두리·아이콘 크기 변화 |
| 다른 모니터 선택 및 창 이동 | 목록 번호와 실제 캡처 대상 일치 |
| 해상도·게임 UI 배율·Windows 배율 고정 | 픽셀 크기와 아이콘 선명도 |
| HDR 사용 시 | 원본과 저장 이미지의 밝기·색상 차이 |

설치와 한 장 캡처가 성공한 뒤 다음 명령으로 환경을 보관합니다.

```powershell
.\.venv-win\Scripts\python.exe -m pip freeze > requirements-windows-observed.txt
```

이 파일은 해당 PC의 관측 환경이며 다른 PC의 작동 보증은 아닙니다.
