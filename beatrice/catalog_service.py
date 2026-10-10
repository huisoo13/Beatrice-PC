"""Public catalog refresh, local cache, cooldown and cancellable background jobs."""
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from .content_match import ContentMatcher
from .public_content import ContentCache, ContentError, PublicContentClient, load_settings, load_api_key


class CatalogService:
    def __init__(self, root, data):
        self.root = Path(root)
        self.cached = self.cache = self.settings = None
        self.message = '공용 데이터 · 확인 대기'
        self.pending = None
        self.jobs = []
        self.startup_finished = False
        self.next_check = 0
        self.refresh_available_at = 0.0
        self.cooldown_path = Path(data) / 'public-content' / 'manual-refresh.json'
        try:
            saved = json.loads(self.cooldown_path.read_text(encoding='utf-8'))
            self.refresh_available_at = max(0.0, float(saved.get('availableAt', 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        try:
            self.settings = load_settings(self.root)
            self.cache = ContentCache(data, self.settings)
            self.cached = self.cache.load()
            if self.cached:
                self.message = '공용 데이터 · 로컬 보관본'
        except ContentError as error:
            self.message = str(error)
        self.matcher = ContentMatcher(self.cached)

    def reserve_manual_refresh(self):
        self.refresh_available_at = time.time() + 300
        try:
            self.cooldown_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cooldown_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(availableAt=self.refresh_available_at)), encoding='utf-8')
            temporary.replace(self.cooldown_path)
        except OSError:
            pass

    def refresh(self):
        if self.pending or not self.settings:
            return
        self.next_check = time.monotonic() + self.settings['refreshSeconds']
        try:
            api_key = load_api_key(self.root)
        except ContentError as error:
            self.message = str(error) + (' · 마지막 정상 데이터 사용 중' if self.cached else '')
            self.startup_finished = True
            return
        cancel, results = threading.Event(), queue.Queue()
        settings, cached = self.settings, self.cached
        def run():
            try:
                results.put((PublicContentClient(api_key, settings, cancel).refresh(cached), None))
            except Exception as error:
                results.put((None, str(error)))
        self.pending = cancel, results
        self.message = '공용 데이터 변경 확인 중…'
        job = threading.Thread(target=run, daemon=True, name='PublicContent')
        self.jobs = [old for old in self.jobs if old.is_alive()]
        self.jobs.append(job)
        job.start()

    def poll(self):
        if not self.pending:
            return False
        try:
            result, error = self.pending[1].get_nowait()
        except queue.Empty:
            return False
        self.pending = None
        self.startup_finished = True
        if error:
            self.message = error + (' · 마지막 정상 데이터 사용 중' if self.cached else '')
        else:
            try:
                self.cache.save(result)
                self.cached = result
                self.matcher = ContentMatcher(result)
                self.message = '공용 데이터 · 최신 확인 ' + datetime.now().strftime('%H:%M')
            except (OSError, ContentError):
                self.message = '공용 데이터를 보관하지 못했습니다.'
        return True

    def stop(self):
        if self.pending:
            self.pending[0].set()
            self.pending = None

    @property
    def settled(self):
        return not any(job.is_alive() for job in self.jobs)

    def rows(self):
        return [dict(dungeon=dungeon, mode=mode, gate=gate, **values)
                for dungeon, modes in (self.cached or {}).get('content', {}).items()
                for mode, gates in modes.items() for gate, values in gates.items()]
