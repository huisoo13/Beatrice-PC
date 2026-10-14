# Windows 배포 준비

최종 갱신: 2026-10-14.

## 준비 범위

Windows x64용 Python 3.12.10 embedded, 전체 Python 라이브러리 휠, 활성 YOLO 6개와 로컬 한국어 OCR 모델, 자체 런타임을 포함한 WinUI Release 빌드, VC++ DLL, 내장 OBS, 7-Zip SFX 모듈, 라이선스와 대응 소스를 준비합니다. 최종 EXE/ZIP 생성은 별도 단계입니다.

Google OAuth 설정과 공용 Drive API 키는 이 준비 명령에서 복사하지 않습니다. 개인 로그인 토큰·로스트아크 API 키·기록 DB도 배포 폴더에 넣지 않습니다.

## 재현 명령과 빌드 설정

빌드 PC에는 Windows x64, Python 3.11 이상과 pip, .NET 8 SDK가 필요합니다. `.venv-win/Scripts/python.exe`와 `outputs/dotnet/dotnet.exe`가 있으면 우선 사용합니다. 처음에는 인터넷 연결이 필요합니다. 모델은 Git에 없으므로 프로젝트 `models/`에 별도로 보관해야 합니다.

```powershell
./packaging/prepare_windows.ps1
```

다운로드가 준비된 뒤에는 다음 명령으로 기존 재료를 재사용합니다. WinUI restore는 캐시를 사용하지만 NuGet 설정에 따라 메타데이터 조회를 시도할 수 있습니다.

```powershell
./packaging/prepare_windows.ps1 -Offline
```

WinUI 설정은 `ui/Beatrice.App/Beatrice.App.csproj`의 `win-x64`, `SelfContained=true`, `WindowsAppSDKSelfContained=true`, `WindowsPackageType=None`입니다. 이 프로젝트 설정과 `build.ps1`은 Git에서 관리합니다.

`requirements-windows.txt`는 개발 환경용 주요 의존성 목록입니다. `requirements-windows-lock.txt`는 Python 3.12 / Windows x64에 맞춘 전체 휠의 버전과 SHA-256을 고정합니다. 준비 시 pip `--require-hashes`를 사용하고, stage 구성 시에도 lock 해시와 일치하는 휠만 선택합니다. 캐시에 남은 다른 버전은 배포에 섞지 않습니다. 공통 cv2 바이너리는 PaddleOCR에 필요한 opencv-contrib-python을 사용하고 opencv-python은 의존성 메타데이터만 남깁니다. Qt/EasyOCR은 포함하지 않습니다.

## 로컬 산출물

| 경로 | 내용 |
|---|---|
| `build/runtime-downloads/` | 공식 Python ZIP, VC++ 패키지, 7-Zip SDK와 추출 도구 |
| `build/windows-wheels/` | 전체 Windows x64 휠 캐시 |
| `build/vc-runtime/` | 앱에 함께 넣을 VC++ DLL |
| `build/7zip-sdk/` | SFX 모듈·SDK 소스·문서 |
| `build/obs-runtime/` | OBS DLL·플러그인·소스·라이선스 |
| `build/third-party-sources/` | GPL 계열 Python 라이브러리의 버전별 PyPI 소스와 해시 |
| `build/native-ui/` | 최신 WinUI publish 결과 |
| `build/windows-app/` | 실행 재료를 모은 배포 준비 폴더 |
| `build/windows-app/preparation-verification.json` | 포함된 Python의 검증 결과 |

위 산출물과 `outputs/`, 모델 바이너리, 개발 가상환경, `bin/obj`, 향후 `dist/`는 Git에서 제외합니다. 스크립트·버전 lock·문서만 Git에서 관리합니다.

## 재사용과 갱신

- 앱 코드 변경: 다운로드 캐시는 재사용하고 stage의 코드·WinUI·Beatrice 대응 소스를 다시 생성합니다.
- 모델 변경: 모델을 교체하고 stage를 다시 생성합니다.
- 라이브러리 변경: 주요 의존성·전체 lock 버전과 해시를 함께 갱신하고, 대응 소스 및 검증을 갱신합니다.
- Python/CPU 아키텍처 변경: 런타임 URL·해시와 휠 lock, stage의 런타임 경로 설정·검증을 함께 바꿉니다.
- 공식 VC++/7zr 다운로드 주소가 새 파일을 제공하면 고정 해시 불일치로 중단합니다. 새 공식 파일을 확인하고 스크립트의 해시를 의도적으로 갱신해야 합니다.

stage 생성은 `build/windows-app/`만 다시 만듭니다. 앱을 해당 폴더에서 실행 중이라면 먼저 종료해야 합니다.

## 라이선스와 검증

Python 및 휠 내부의 LICENSE/NOTICE는 그대로 보존합니다. `licenses/third-party.json`에는 패키지별 버전·라이선스 메타데이터·라이선스 파일 경로를 기록합니다. Microsoft NuGet 캐시의 라이선스·NOTICE는 `licenses/microsoft/`에 수집합니다. VC++ 공식 패키지도 보존합니다.

OBS의 원본 소스·COPYING과 Beatrice 대응 소스 ZIP은 `obs-runtime/licenses/`에 둡니다. Beatrice 소스에는 실행 코드, 설정, UI 에셋, 빌드/패키징 스크립트, 테스트, 도구, 상세 문서를 포함하고 bin/obj와 캐시는 제외합니다. Ultralytics·THOP·Ultralytics Platform·crc32c·python-bidi의 정확한 버전별 소스와 7-Zip SDK는 `licenses/sources/`에 둡니다. 수집 결과가 최종 배포 라이선스 검토를 대신하지는 않습니다.

`verify_windows_stage.py`는 반드시 포함된 Python으로 실행합니다. 핵심 라이브러리 import, 활성 YOLO 6개 CPU 추론, 로컬 PaddleOCR 추론, OBS/캡처 DLL 로드, 소스 ZIP 무결성과 개인 데이터 제외를 확인합니다. 앱을 실행하거나 게임에 캡처 후크를 연결하지 않습니다. 개발 환경 없는 별도 PC의 실제 시작·게임 캡처·Google 연결·종료 검증은 이후 배포 단계에서 수행합니다.

## 이후 최종 패키징

현재 요청의 범위에는 포함하지 않은 단계입니다. 추후 SFX EXE를 만들 때는 빌드 Python에 `py7zr`가 필요하며, 최종 무결성 검사에는 `pefile`도 필요합니다.

```powershell
.venv-win/Scripts/python.exe packaging/build_single_exe.py
.venv-win/Scripts/python.exe packaging/verify_single_exe.py
```

출력은 `dist/BeatricePC.exe`입니다. ZIP 방식은 검증된 `build/windows-app/` 폴더 전체를 압축하면 되며, Google 설정 제공 여부를 먼저 반영해야 합니다.
