# Google Drive API 모듈

2026-10-10. 개인 기록과 공용 데이터의 HTTP 통신을 `beatrice.drive`로 통합했다.

## 구조와 변경 경계

- `drive/client.py`: 공식 Drive 엔드포인트, 인증, 시간·응답 크기 제한, 취소, JSON/바이너리 응답 처리. 기본 시간 제한 20초, 응답 크기 4 MiB. 리다이렉트는 거부한다.
- `drive/files.py`: 파일 목록과 페이지 순회, 메타데이터 조회, bytes 다운로드, multipart 생성·수정.
- `drive/folders.py`: 폴더 내부 파일 조회. 폴더도 Drive 파일이므로 파일 API를 사용한다.
- `drive/errors.py`: 상태 코드와 안전한 오류 사유에 따른 예외. 원본 HTTP 메시지·URL·인증 정보는 노출하지 않는다.

이 패키지는 표준 라이브러리만 사용한다. UI, SQLite, 기록 스키마, 파일명, 로컬 백업, 캐시, 로그인과 토큰 갱신에 의존하지 않는다. 공개 메서드의 인자·반환값·예외 규칙을 유지하면 내부 통신 구현을 바꿔도 호출부 수정이 필요 없다. 공개 계약이나 Google 권한 변경은 호출부 검토가 필요하다.

`google_drive.DriveClient`는 기존 생성자, `download`, `upload`, `request`, `json_request`, `opener`를 유지하는 기록 저장 어댑터다. `DriveError`, `API`, `UPLOAD`의 기존 import도 유지한다. 기존 점검 도구의 DELETE 요청은 공식 엔드포인트에 한해 계속 지원하며, 앱 기록 저장에는 삭제 기능을 추가하지 않았다.

`public_content.PublicContentClient`도 기존 호출 방식과 ContentError를 유지한다. 폴더 탐색과 다운로드는 새 모듈을 호출하고, 데이터 검증·MD5 비교·캐시는 기존 코드가 담당한다. 공용 데이터의 실행 주기와 작업 관리는 기존 Host에 유지했다.

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

바이너리 전송을 지원하지만 이미지 목록, 이미지 캐시, UI 이미지 표시 기능은 추가하지 않았다.

## 검증

`tests/test_drive_client.py`는 인증 분리, 공용 쓰기 거부, 취소, 크기 제한, 바이너리 multipart, 빈 계정·빈 페이지·반복 페이지, 오류 분류·비밀 정보 비노출·자동 재시도 금지를 검증한다. 기존 Drive·공용 데이터·서비스·주간 기록 테스트로 앱 동작의 호환성을 확인한다. 실제 Google 서버와의 검증은 별도의 연결 점검 도구를 사용하며, 단위 테스트는 외부 요청을 보내지 않는다.


### 실제 Google 서버 검증 — 2026-10-10

- `tools/check_public_content.py`: 공용 폴더 → JSON → ContentJSON.json 조회 성공. 던전 10개, 난이도 항목 30개, 관문 항목 63개를 검증하고 별도 로컬 캐시 저장·재사용을 확인했다.
- `tools/check_drive_connection.py`: 별도의 integration-test 파일 생성, 앱 전용 폴더 목록 조회, 다운로드 내용 일치 확인. 같은 파일에 PATCH로 2관문을 추가하고 파일 ID 유지·수정 내용 재다운로드를 확인했다. 삭제 후 메타데이터 조회의 404까지 확인했다.
- `tools/check_auto_drive.py`: 임시 DB의 1·2관문 완료 → 자동 업로드 → 최신 기록 재조회 성공. 기존 recordID와 변경 없는 기록의 updatedAt 유지, 동일 완료 재관측 시 전송 대기 없음 확인. 생성한 테스트 파일 2개를 삭제했다.

점검용 파일은 총 3개 생성하고 정리했다. 운영 PC.json·iOS.json 또는 앱의 실제 기록 DB를 수정하는 경로는 사용하지 않았다. 공용 점검 캐시는 outputs/public-content-check에만 저장했다.

자동 업로드 점검 도구의 첫 실행은 현재 서비스가 전달하는 backup_directory 인자를 테스트 클라이언트가 받지 못해 실패했다. 점검 도구 생성자를 수정한 뒤 재실행하여 통과했다. 첫 실행은 원격 파일을 생성하지 않았다. 연결 점검 도구에는 동일 파일 PATCH와 삭제 후 404 확인을 추가했다.

Python 회귀 테스트는 모듈 분리 후 381개 통과했다. 실제 연결 검증은 현재 저장된 계정 권한과 API 키로 수행했으며, 권한 동의나 설정 변경은 필요하지 않았다.
