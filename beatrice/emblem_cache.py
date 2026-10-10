"""Conditional CDN SVG downloads; no Google credentials or UI dependencies."""
import hashlib
from http.client import HTTPException
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree
from .public_content import ContentError

CDN_BASE_URL = 'https://cdn-lostark.game.onstove.com'
MAX_SVG_BYTES = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_svg(body):
    if len(body) > MAX_SVG_BYTES:
        raise ContentError('직업 문양 SVG의 허용 크기를 초과합니다.')
    try:
        text = body.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError()
        root = ElementTree.fromstring(text)
        if root.tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
            raise ValueError()
        if any(node.tag.rsplit('}', 1)[-1].lower() == 'script' for node in root.iter()):
            raise ValueError()
    except (UnicodeError, ValueError, ElementTree.ParseError):
        raise ContentError('직업 문양 응답이 올바른 SVG가 아닙니다.') from None
    return body


class EmblemCache:
    def __init__(self, directory, base_url=CDN_BASE_URL, *, opener=None):
        if not isinstance(base_url, str) or base_url.rstrip('/') != CDN_BASE_URL:
            raise ContentError('직업 문양 CDN 주소를 확인해주세요.')
        self.directory = Path(directory)
        self.base_url = base_url.rstrip('/')
        self.opener = opener if opener is not None else build_opener(_NoRedirect()).open

    def source_url(self, source_path):
        if not isinstance(source_path, str) or not re.fullmatch(r'/[A-Za-z0-9_/-]+\.svg', source_path) or '//' in source_path:
            raise ContentError('직업 문양 SVG 경로를 확인해주세요.')
        return self.base_url + source_path

    def file_path(self, item):
        url = self.source_url(item['sourcePath'])
        digest = item.get('sha256')
        if item.get('sourceUrl') != url or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ContentError('직업 문양 캐시 정보를 확인해주세요.')
        # Keep the basename readable; URL/content hashes avoid collisions and preserve old versions.
        name = Path(item['sourcePath']).stem + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '-' + digest + '.svg'
        target = self.directory / 'assets' / 'Emblems' / name
        if not target.resolve().is_relative_to(self.directory.resolve()):
            raise ContentError('직업 문양 캐시 경로를 확인해주세요.')
        if item.get('localPath') != target.relative_to(self.directory).as_posix():
            raise ContentError('직업 문양 캐시 경로가 일치하지 않습니다.')
        return target

    def body(self, item):
        try:
            with self.file_path(item).open('rb') as stream:
                body = stream.read(MAX_SVG_BYTES + 1)
            if len(body) != item.get('size') or hashlib.sha256(body).hexdigest() != item['sha256']:
                return None
            return validate_svg(body)
        except (OSError, KeyError, TypeError, ContentError):
            return None

    @staticmethod
    def _header(value):
        return value if isinstance(value, str) and 0 < len(value) <= 1024 and all(32 <= ord(c) < 127 for c in value) else None

    @staticmethod
    def _cancel(cancel):
        if cancel.is_set():
            raise ContentError('직업 문양 다운로드를 취소했습니다.')

    def fetch(self, source_path, previous, cancel, *, timeout=15):
        url = self.source_url(source_path)
        valid = previous is not None and previous.get('sourceUrl') == url and self.body(previous) is not None
        headers = {'Accept': 'image/svg+xml'}
        if valid:
            etag = self._header(previous.get('etag'))
            modified = self._header(previous.get('lastModified'))
            if etag: headers['If-None-Match'] = etag
            elif modified: headers['If-Modified-Since'] = modified
        self._cancel(cancel)
        try:
            with self.opener(Request(url, headers=headers), timeout=timeout) as response:
                mime = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if mime not in ('image/svg+xml', 'application/xml', 'text/xml'):
                    raise ContentError('직업 문양 응답 형식을 확인해주세요.')
                body = response.read(MAX_SVG_BYTES + 1)
                etag = self._header(response.headers.get('ETag'))
                modified = self._header(response.headers.get('Last-Modified'))
        except HTTPError as error:
            status = error.code
            error.close()
            self._cancel(cancel)
            if status == 304 and valid:
                return dict(previous), False
            if status == 404:
                raise ContentError('CDN에서 직업 문양 SVG를 찾을 수 없습니다.') from None
            raise ContentError('직업 문양 CDN 요청에 실패했습니다. 나중에 다시 시도해주세요.') from None
        except (URLError, OSError, HTTPException):
            raise ContentError('직업 문양 CDN에 연결하지 못했습니다.') from None
        self._cancel(cancel)
        validate_svg(body)
        item = dict(sourcePath=source_path, sourceUrl=url, sha256=hashlib.sha256(body).hexdigest(),
                    size=len(body), etag=etag, lastModified=modified)
        name = Path(source_path).stem + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '-' + item['sha256'] + '.svg'
        item['localPath'] = 'assets/Emblems/' + name
        path = self.file_path(item)
        self._cancel(cancel)
        if self.body(item) is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
            try:
                temporary.write_bytes(body)
                self._cancel(cancel)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return item, True

    def prepare(self, jobs, previous=None, *, cancel=None, max_bytes=128 * 1024 * 1024):
        cancel = cancel if cancel is not None else threading.Event()
        previous_by_path = {item.get('sourcePath'): item for item in (previous or {}).values() if isinstance(item, dict)}
        by_path, errors, downloaded, total = {}, {}, 0, 0
        deadline = time.monotonic() + 60
        for source_path in dict.fromkeys(jobs.values()):
            previous_item = previous_by_path.get(source_path)
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ContentError('직업 문양 갱신 시간 제한에 도달했습니다.')
                item, fetched = self.fetch(source_path, previous_item, cancel, timeout=min(15, remaining))
            except ContentError as error:
                self._cancel(cancel)
                errors[source_path] = str(error)
                if not previous_item or self.body(previous_item) is None:
                    continue
                item, fetched = dict(previous_item), False
            total += item['size']
            if total > max_bytes:
                raise ContentError('직업 문양 캐시의 전체 크기 제한을 초과합니다.')
            by_path[source_path] = item
            downloaded += int(fetched)
        self._cancel(cancel)
        return ({job: dict(by_path[path]) for job, path in jobs.items() if path in by_path},
                downloaded, {job: errors[path] for job, path in jobs.items() if path in errors})

    def validate(self, jobs, entries, errors=None):
        errors = errors or {}
        if (not isinstance(entries, dict) or not isinstance(errors, dict)
                or set(entries) | set(errors) != set(jobs)
                or any(not isinstance(value, str) for value in errors.values())):
            raise ContentError('직업 문양 캐시 목록이 JSON과 다릅니다.')
        total, seen = 0, set()
        for job, item in entries.items():
            if not isinstance(item, dict) or item.get('sourcePath') != jobs[job] or self.body(item) is None:
                raise ContentError('보관된 직업 문양 SVG를 확인하지 못했습니다.')
            if item['sourcePath'] not in seen:
                total += item['size']
                seen.add(item['sourcePath'])
        return total

    def for_job(self, job, entries):
        item = (entries or {}).get(job)
        return self.file_path(item) if isinstance(item, dict) and self.body(item) is not None else None
