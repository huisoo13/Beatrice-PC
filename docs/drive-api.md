# Google Drive API 모듈

2026-10-10. 개인 기록과 공용 데이터의 HTTP 통신을 `beatrice.drive`로 통합했다.

## 구조와 변경 경계

- `drive/client.py`: 공식 Drive 엔드포인트, 인증, 시간·응답 크기 제한, 취소, JSON/바이너리 응답 처리. 기본 시간 제한 20초, 응답 크기 4 MiB. 리다이렉트는 거부한다.
- `drive/files.py`: 파일 목록과 페이지 순회, 메타데이터 조회, bytes 다운로드, multipart 생성·수정.
- `drive/folders.py`: 폴더 내부 파일 조회. 폴더도 Drive 파일이므로 파일 API를 사용한다.
- `drive/errors.py`: 상태 코드와 안전한 오류 사유에 따른 예외. 원본 HTTP 메시지·URL·인증 정보는 노출하지 않는다.

이 패키지는 표준 라이브러리만 사용한다. UI, SQLite, 기록 스키마, 파일명, 로컬 백업, 캐시, 로그인과 토큰 갱신에 의존하지 않는다. 공개 메서드의 인자·반환값·예외 규칙을 유지하면 내부 통신 구현을 바꿔도 호출부 수정이 필요 없다. 공개 계약이나 Google 권한 변경은 호출부 검토가 필요하다.

`google_drive.DriveClient`는 기존 생성자, `download`, `upload`, `request`, `json_request`, `opener`를 유지하는 기록 저장 어댑터다. `DriveError`, `API`, `UPLOAD`의 기존 import도 유지한다. 기존 점검 도구의 DELETE 요청은 공식 엔드포인트에 한해 계속 지원하며, 앱 기록 저장에는 삭제 기능을 추가하지 않았다.

`public_content.PublicContentClient`도 기존 호출 방식과 ContentError를 유지한다. 폴더 탐색과 다운로드는 새 모듈을 호출하고, 데이터 검증·MD5 비교·캐시는 기존 코드가 담당한다. 공용 데이터의 실행 주기와 작업 관리는 CatalogService가 담당한다.

## 사용 예

```python
from beatrice.drive import GoogleDriveClient

# 공용 데이터: API 키, GET만 허용, OAuth 토큰을 사용하지 않는다.
public = GoogleDriveClient(api_key=api_key, cancel=cancel, timeout=15)
files = public.folders.children(folder_id)
metadata = public.files.get(file_id, fields='id,name,mimeType')
image_bytes = public.files.download(file_id, max_bytes=8 * 1024 * 1024)

# 개인 데이터: 기존 계정 서비스가 선택한 세션의 액세스 토큰을 갱신해서 전달한다.
private = GoogleDriveClient(access_token=access_token, cancel=cancel)
created = private.files.create(
    {'name': 'example.json', 'parents': ['appDataFolder']},
    b'{"value":1}', mime_type='application/json')
private.files.update(created['id'], {'name': 'example.json'},
                     b'{"value":2}', mime_type='application/json')
```

생성 시 API 키와 액세스 토큰 중 정확히 하나를 지정한다. 생성자에서는 네트워크 요청을 하지 않는다. 개인 클라이언트와 공용 클라이언트는 별도 인스턴스로 사용한다. `files.list(**parameters)`는 한 페이지의 응답 dict, `files.iter_files(**parameters)`는 모든 페이지의 파일 dict를 순서대로 반환한다. 파일이 없어 files 필드가 생략된 응답은 빈 목록으로 처리한다. 빈 중간 페이지도 따라가고, 반복 토큰이나 100페이지 초과는 오류다. 파일 조회·생성·수정은 응답 dict, 다운로드는 bytes를 반환한다.

`request(path='', method='GET', params=None, body=None, content_type=None, upload=False, max_bytes=None)`는 공식 files 엔드포인트 기준 상대 경로만 허용한다. 파일 ID는 Google Drive ID 문자(영문·숫자·밑줄·하이픈)를 사용한다. 임의 호스트로 인증 정보를 보내지 않는다. `opener`는 테스트 또는 별도 전송 구현 주입용이며 기본 리다이렉트 정책을 유지할 책임이 있다.

## 오류와 재시도

모든 예외는 `DriveError`를 상속한다. `DriveAuthError`, `DrivePermissionError`, `DriveNotFoundError`, `DriveRateLimitError`, `DriveNetworkError`, `DriveResponseError`, `DriveCancelledError`로 구분한다. HTTP 오류에는 `status`, 알려진 오류만 허용한 `reason`, 초 단위 Retry-After의 `retry_after`가 있다. 정보가 없으면 None이다.

403은 오류 사유가 호출 제한인지 권한 문제인지 구분한다. 원본 응답 본문과 임의 reason은 전달하지 않는다. 클라이언트는 자동 재시도하거나 대기하지 않는다. 특히 POST/PATCH의 중복 실행을 막기 위해 재시도와 업로드 후 검증은 서비스가 담당한다. cancel은 요청 전과 응답 수신 후 확인하며, 진행 중 네트워크 호출은 timeout까지 기다릴 수 있다.

## 보존하는 앱 동작

- PC.json 파일 ID를 유지하는 PATCH, 교체 전 로컬 백업, 업로드 후 재다운로드 검증.
- iOS.json과 기록 스키마 3, 주간 중복 판정, 완료 기록 보존, isTest 내보내기 제외 규칙.
- 로그인·동의 범위·DPAPI 자격 증명 보관, 작업 시작 시 계정 캡처, 계정 전환·취소 시 결과 처리.
- 공용 데이터 API 키, 4 MiB 제한, JSON 검증, 기존 캐시 포맷과 실패 시 마지막 정상 캐시 사용.
- WinUI 명령과 응답 형식, 자동 업로드 지연·재시도 정책.

바이너리 전송을 지원한다. 2026-10-10 후속 작업에서 공용 EmblemJSON과 Images 캐시를 추가했으며, 아래 내용을 참고한다. UI 표시 연결은 별도다.

## 검증

`tests/test_drive_client.py`는 인증 분리, 공용 쓰기 거부, 취소, 크기 제한, 바이너리 multipart, 빈 계정·빈 페이지·반복 페이지, 오류 분류·비밀 정보 비노출·자동 재시도 금지를 검증한다. 기존 Drive·공용 데이터·서비스·주간 기록 테스트로 앱 동작의 호환성을 확인한다. 실제 Google 서버와의 검증은 별도의 연결 점검 도구를 사용하며, 단위 테스트는 외부 요청을 보내지 않는다.


### 실제 Google 서버 검증 — 2026-10-10

- `tools/check_public_content.py`: 공용 폴더 → JSON → ContentJSON.json 조회 성공. 던전 10개, 난이도 항목 30개, 관문 항목 63개를 검증하고 별도 로컬 캐시 저장·재사용을 확인했다.
- `tools/check_drive_connection.py`: 별도의 integration-test 파일 생성, 앱 전용 폴더 목록 조회, 다운로드 내용 일치 확인. 같은 파일에 PATCH로 2관문을 추가하고 파일 ID 유지·수정 내용 재다운로드를 확인했다. 삭제 후 메타데이터 조회의 404까지 확인했다.
- `tools/check_auto_drive.py`: 임시 DB의 1·2관문 완료 → 자동 업로드 → 최신 기록 재조회 성공. 기존 recordID와 변경 없는 기록의 updatedAt 유지, 동일 완료 재관측 시 전송 대기 없음 확인. 생성한 테스트 파일 2개를 삭제했다.

점검용 파일은 총 3개 생성하고 정리했다. 운영 PC.json·iOS.json 또는 앱의 실제 기록 DB를 수정하는 경로는 사용하지 않았다. 공용 점검 캐시는 outputs/public-content-check에만 저장했다.

자동 업로드 점검 도구의 첫 실행은 현재 서비스가 전달하는 backup_directory 인자를 테스트 클라이언트가 받지 못해 실패했다. 점검 도구 생성자를 수정한 뒤 재실행하여 통과했다. 첫 실행은 원격 파일을 생성하지 않았다. 연결 점검 도구에는 동일 파일 PATCH와 삭제 후 404 확인을 추가했다.

Python 회귀 테스트는 모듈 분리 후 381개 통과했다. 실제 연결 검증은 현재 저장된 계정 권한과 API 키로 수행했으며, 권한 동의나 설정 변경은 필요하지 않았다.


## 공용 JSON·이미지·직업 문양 캐시

2026-10-10. 앱 시작 시 기존 CatalogService에서 공용 데이터를 갱신하고, 실행 중에는 1시간 주기와 수동 공용 갱신으로 변경을 확인한다.

| 대상 | 원격 위치 | 로컬 보관 |
| --- | --- | --- |
| 던전 데이터 | Drive JSON/ContentJSON.json | public-content/content-cache.json |
| 문양 목록 JSON 1개 | Drive JSON/EmblemJSON.json | public-content/assets/JSON/ |
| 공용 PNG 등 | Drive Images/ 및 하위 폴더 | public-content/assets/Images/ |
| 직업 문양 SVG | 공식 CDN + EmblemJSON의 상대 경로 | public-content/assets/Emblems/ |

보관 위치는 앱 데이터 디렉터리 기준이다. 다운로드 파일과 메타데이터를 연결하는 목록은 public-content/assets-cache.json에 저장한다. 원격 파일은 읽기만 한다. UI에 문양이나 이미지를 그리는 연결은 별도 작업이다.

### 모듈과 설정

- public_content.py: 던전 JSON 검증·캐시, 공용 Drive 클라이언트와 설정.
- public_assets.py: EmblemJSON 검증, Drive 이미지 탐색, 파일 버전 보관, 캐시 목록 게시.
- emblem_cache.py: CDN 조건부 SVG 조회·검증과 직업별 로컬 파일 조회.
- catalog_service.py: 시작·정기·수동 갱신, 취소와 실패 상태, 마지막 정상 캐시 유지.

config/public-content.json의 설정은 다음과 같다. 기존 설정에 새 항목이 없으면 같은 기본값을 사용한다.

```json
{
  "jsonFolderName": "JSON",
  "fileName": "ContentJSON.json",
  "emblemFileName": "EmblemJSON.json",
  "imagesFolderName": "Images",
  "emblemBaseUrl": "https://cdn-lostark.game.onstove.com",
  "refreshSeconds": 3600
}
```

rootFolderID는 기존 공유 폴더 설정을 사용한다. EmblemJSON은 직업명→이미지 상대 경로 문자열의 객체로 검증하며 원본 경로를 유지한다. CDN 요청은 Google API 키나 OAuth 토큰을 사용하지 않는다. 공식 CDN 호스트의 SVG 경로만 허용하고 임의 URL·리다이렉트·경로 이탈을 거부한다.

### 변경 감지와 보관

Drive 파일은 MD5와 크기를 검증한다. 로컬 파일이 정상이고 MD5가 같으면 다운로드를 생략한다. 파일이 없거나 손상되면 다시 받는다. Drive 캐시 파일명은 검증된 파일 ID와 MD5로 생성하며, 원래 이름과 하위 폴더 경로는 목록에 유지한다. PNG/JPEG/WebP/GIF/SVG/BMP를 지원한다.

CDN SVG는 정상 캐시가 있으면 If-None-Match에 ETag를 전달한다. ETag가 없으면 If-Modified-Since에 Last-Modified를 전달한다. 304는 기존 파일을 재사용하고, 200은 SVG 형식·크기를 확인한 뒤 저장한다. 파일이 없거나 손상되면 조건 없이 다시 받는다. 같은 상대 경로를 쓰는 직업은 파일을 공유한다. SVG 파일명에는 원래 이름, URL 해시, 내용 SHA-256을 사용한다.

새 파일 버전은 별도 경로에 저장하고 마지막에 캐시 목록을 원자적으로 교체한다. 이전 정상 버전은 보존한다. Drive 자산 갱신 실패 시 기존 정상 목록을 유지하며, 성공한 던전 데이터 갱신을 막지 않는다. CDN 문양별 실패는 다른 문양 다운로드를 막지 않는다. 실패한 문양은 같은 경로의 정상 캐시가 있으면 유지하며 없으면 로컬 조회 결과가 None이다. emblemErrors에 실패 사유를 기록하고 앱 공용 데이터 상태에 실패 수를 표시한다. 취소된 작업은 새 목록을 게시하지 않는다.

크기와 작업 제한: JSON 4 MiB, Drive 이미지 한 파일 16 MiB, SVG 한 파일 4 MiB, 현재 자산 묶음 총 128 MiB, Drive 이미지 500개, 하위 폴더 깊이 8단계, CDN 전체 갱신 최대 60초. 이 제한은 자산 캐시의 정책이며 공통 Drive API에는 포함하지 않는다.

### 직업명으로 사용하기

assets-cache.json의 emblems는 직업명을 키로 sourcePath, sourceUrl, localPath, etag, lastModified, sha256, size를 보관한다. 네트워크 요청 없이 검증된 로컬 Path를 조회한다.

```python
path = catalog_service.emblem_path('워로드')
# 또는 보관된 bundle을 전달한다.
path = asset_cache.emblem_path('워로드', bundle)
# 미보관 또는 손상된 파일은 None이다.
```

### 최종 검증 결과 — 2026-10-10

전체 Python 테스트 429개가 통과했다. tests/test_public_assets.py와 tests/test_emblem_cache.py에서 변경·손상 복구, 실패·취소, 304, ETag/Last-Modified, 경로 검사, 크기·시간 제한과 서비스 연동을 확인했다.

실제 Drive에서 JSON 1개(직업별 항목 38개)와 PNG 2개 저장·재사용을 확인했다. 최초 CDN 점검에서 fighter_female.svg와 delain.svg가 HTTP 404였으나, 사용자가 원격 JSON을 수정한 후 앱과 같은 CatalogService로 재검증하여 SVG 38개 정상·실패 0개를 확인했다.

| 직업 | 수정 전 파일 | 현재 파일 | 갱신 결과 |
| --- | --- | --- | --- |
| 파이터(남) | fighter.svg | fighter_male.svg | 새 다운로드, 10,032 bytes |
| 파이터(여) | fighter_female.svg | fighter.svg | 기존 정상 파일 재사용, 7,467 bytes |
| 암살자 | delain.svg | assassin.svg | 새 다운로드, 7,799 bytes |

SVG 경로 앞에는 /2018/obt/assets/images/common/class/가 붙는다. 변경된 직업은 3개이며 실제 갱신 다운로드는 변경 JSON 1개와 SVG 2개였다. 세 직업 모두 현재 경로의 로컬 SVG 조회와 새 서비스 인스턴스의 오프라인 캐시 복원이 통과했다. 재갱신에서 Drive 파일 0개·SVG 0개 다운로드, 실패 0개를 확인했다.

### Git 제외와 재검증

실제 앱의 다운로드 캐시는 앱 데이터 폴더에 저장한다. 점검 도구는 outputs/public-content-check에, 실제 CatalogService 시작 검증은 outputs/public-assets-startup-check에 별도 캐시를 저장했다. outputs/는 .gitignore로 제외된다. 받은 JSON·PNG·SVG, 캐시 목록, 이전 버전은 커밋하지 않고 코드·설정·테스트·문서만 커밋한다.

```powershell
.\.venv-win\Scripts\python.exe tools/check_public_content.py
```

이 도구는 공용 던전 JSON, EmblemJSON, Drive 이미지, CDN SVG의 저장·재사용과 직업명 조회를 확인한다. 실패한 직업과 경로는 WARN으로 출력한다. 원격 데이터와 개인 완료 기록은 수정하지 않는다.


## ContentJSON 신규 배열 구조 (2026-10-11)

ContentJSON의 신규 배열은 ContentCatalog가 검증·인덱싱한다. OCR 비교용 field_name과 저장·표시용 name을 구분하며 이전 객체 캐시도 유지한다. CatalogService의 보상표, 기록·하단·주간 현황과 중복 판정 연결을 새 구조에 맞췄다. [형식·정책·검증 결과](content-catalog.md)를 참고한다. 기존 Drive 통신·개인 기록 JSON·자산 다운로드 경계는 유지한다.
