"""Account character discovery and durable reuse, independent of Host and WinUI."""
import json
from decimal import Decimal, InvalidOperation
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from .character_info import from_cache
from .lostark import (LostArkClient, LostArkAuthError, LostArkNotFoundError,
                     LostArkRateLimitError, LostArkMaintenanceError)

MAX_BYTES = 8 * 1024 * 1024


def _label(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100 and not any(ord(c) < 32 for c in value)


def _profiles(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValueError('캐릭터 목록 응답 없음')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not _label(row.get('CharacterName')) or not _label(row.get('CharacterClassName')):
            raise ValueError('캐릭터 목록 형식 오류')
        result[row['CharacterName'].strip()] = dict(row)
    return result


class CharacterCatalog:
    def __init__(self, directory, *, key_available, client_factory=None, clock=time.time):
        self.path = Path(directory) / 'lostark' / 'characters.json'
        self.key_available = key_available
        self.client_factory = client_factory or (lambda: LostArkClient.from_saved_key(directory, timeout=10))
        self.clock = clock
        self.characters, self.retry_at = {}, {}
        self.pending = None
        self.client = None
        self.closed = False
        self._refresh_requests = {}
        self._refresh_version = 0
        self._refresh_results = []
        self.blocked_until = self.next_request = 0
        try:
            with self.path.open('rb') as stream: body = stream.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES: raise ValueError()
            saved = json.loads(body)
            if saved.get('version') != 1 or not isinstance(saved.get('characters'), dict): raise ValueError()
            for name, entry in saved['characters'].items():
                parsed = _profiles([entry['profile']])
                if name not in parsed or not isinstance(entry.get('fetchedAt'), str): raise ValueError()
            if not isinstance(saved.get('retryAt', {}), dict): raise ValueError()
            self.characters = saved['characters']
            self.retry_at = {name: deadline for name, deadline in saved.get('retryAt', {}).items()
                             if _label(name) and type(deadline) in (int, float) and deadline > self.clock()}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass

    def _save(self):
        body = json.dumps(dict(version=1, characters=self.characters, retryAt=self.retry_at),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(body) > MAX_BYTES: return
        temporary = self.path.with_suffix('.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(body)
            temporary.replace(self.path)
        except OSError:
            pass  # Retain this session's result without repeatedly calling the API.
        finally:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass

    def refresh(self, name):
        """Queue an explicit cached-character refresh without bypassing backoff."""
        if self.closed or not _label(name) or name.strip() == '캐릭터 확인 대기': return
        self._refresh_version += 1
        self._refresh_requests[name.strip()] = self._refresh_version

    def info(self, name):
        return from_cache(self.characters.get(name.strip()))

    def take_refresh_results(self):
        results, self._refresh_results = self._refresh_results, []
        return results

    def ensure(self, names):
        if self.closed or self.pending or not self.key_available() or self.clock() < max(self.blocked_until, self.next_request): return
        candidates = list(self._refresh_requests) + list(names)
        name = next((name.strip() for name in dict.fromkeys(candidates) if _label(name)
                     and name.strip() != '캐릭터 확인 대기'
                     and (name.strip() in self._refresh_requests or name.strip() not in self.characters)
                     and self.retry_at.get(name.strip(), 0) <= self.clock()), None)
        if name is None: return
        if self.client is None: self.client = self.client_factory()
        results, cancel = queue.Queue(), threading.Event()
        client = self.client
        refresh_version = self._refresh_requests.get(name, 0)
        def run():
            try:
                profiles = _profiles(client.characters.siblings(name))
                results.put((profiles, None, 0))
            except LostArkAuthError:
                results.put((None, 'auth', 300))
            except LostArkRateLimitError as error:
                results.put((None, 'limited', max(60, error.retry_after or 60)))
            except LostArkMaintenanceError as error:
                results.put((None, 'maintenance', max(300, error.retry_after or 300)))
            except (LostArkNotFoundError, ValueError):
                results.put((None, 'missing', 86400))
            except Exception:
                results.put((None, 'network', 300))
        thread = threading.Thread(target=run, daemon=True, name='LostArkCharacters')
        self.pending = (name, results, cancel, thread, refresh_version)
        self.next_request = self.clock() + .7
        thread.start()

    def poll(self):
        if self.pending is None: return False
        name, results, cancel, thread, refresh_version = self.pending
        if thread.is_alive(): return False
        profiles, error, delay = results.get_nowait()
        self.pending = None
        if self.closed or cancel.is_set(): return False
        if error:
            self.retry_at[name] = self.clock() + delay
            if error in ('auth', 'limited', 'network', 'maintenance'): self.blocked_until = self.clock() + delay
        else:
            fetched = datetime.now(timezone.utc).isoformat()
            for character, profile in profiles.items():
                self.characters[character] = dict(profile=profile, fetchedAt=fetched)
                self.retry_at.pop(character, None)
            if name not in profiles: self.retry_at[name] = self.clock() + 86400
        if self._refresh_requests.get(name, 0) == refresh_version:
            success = not error and name in profiles
            self._refresh_results.append((name, self.info(name)))
            if success: self._refresh_requests.pop(name, None)
        self._save()
        return True

    def decorate(self, records, emblem_path):
        """Use only cached profiles and CatalogService's verified local assets."""
        paths = {}
        for row in records:
            info = row.get('characterInfo') if 'characterInfo' in row else self.info(row['character'])
            info = info or {}
            job = (info.get('className') or '').strip()
            row['characterClass'] = job
            level = str(info.get('itemLevel') or '').strip()
            try:
                number = Decimal(level.replace(',', ''))
                if not number.is_finite() or number <= 0 or len(level) > 30: level = ''
            except InvalidOperation: level = ''
            row['itemLevel'] = level
            if job not in paths:
                path = emblem_path(job) if job else None
                paths[job] = str(path.resolve()) if path is not None else None
            row['characterEmblem'] = paths[job]
        return records

    def character_view(self, name, emblem_path):
        """Expose cached character metadata for the current-character footer."""
        return self.decorate([{'character': name}], emblem_path)[0]

    def credentials_changed(self):
        if self.pending: self.pending[2].set()
        self.client = None
        self.blocked_until = self.next_request = 0
        self.retry_at.clear()
        self._save()

    def stop(self):
        self.closed = True
        if self.pending: self.pending[2].set()

    @property
    def settled(self):
        return self.pending is None or not self.pending[3].is_alive()
