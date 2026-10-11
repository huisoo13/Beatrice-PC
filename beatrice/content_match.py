"""Conservative, local-only matching of OCR observations to the public catalog."""
import copy
from difflib import SequenceMatcher
import re
import unicodedata

from .public_content import ContentCache, ContentError, load_settings
from .content_catalog import ContentCatalog
from .completion_record import recognition_record,canonical,validate


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def mode_key(text):
    value = normalized(text)
    return value[:-2] if value.endswith('모드') else value


class ContentMatcher:
    def __init__(self, cached=None):
        self.catalog = ContentCatalog(cached['content'] if cached else None)
        self.content = self.catalog.rewards
        metadata = cached.get('metadata', {}) if cached else {}
        self.version = {k: metadata[k] for k in ('id', 'version', 'md5Checksum') if k in metadata}

    def _candidates(self, text, *, stored=False, exact_only=False):
        value = normalized(text or '')
        if not value:
            return []
        exact = [name for name, field in self.catalog.field_names.items()
                 if normalized(field) == value or (stored and normalized(name) == value)]
        if exact or exact_only:
            return exact
        # OCR correction compares field_name only, keeping stage/chapter digits distinct.
        if len(value) < 5:
            return []
        digits = re.findall(r'\d+', value)
        return [name for name, field in self.catalog.field_names.items()
                if re.findall(r'\d+', normalized(field)) == digits
                and SequenceMatcher(None, value, normalized(field), autojunk=False).ratio() >= .85]

    def dungeon_candidates(self, text):
        return self._candidates(text)

    def stored_candidates(self, text):
        return self._candidates(text, stored=True, exact_only=True)

    def record_candidates(self, record, *, exact_only=True):
        record=recognition_record(record)
        sources = [record.get('dungeonName'),
                   (record.get('catalogMatch') or {}).get('fieldName'),
                   (record.get('ocrOriginal') or {}).get('dungeonName')]
        return list(dict.fromkeys(name for source in sources if source
                    for name in self._candidates(source, stored=True, exact_only=exact_only)))

    def display_record_context(self, record):
        record=recognition_record(record)
        names = self.record_candidates(record)
        difficulty = record.get('difficulty')
        if len(names) != 1:
            return record.get('dungeonName'), difficulty
        name = names[0]
        modes = [mode for mode in self.content[name] if mode_key(mode) == mode_key(difficulty or '')]
        return name, modes[0] if len(modes) == 1 else difficulty

    def display_context(self, dungeon, difficulty, *, stored=False):
        """OCR uses field_name; stored names also accept exact canonical names."""
        names = self._candidates(dungeon, stored=stored, exact_only=stored)
        if len(names) != 1:
            return dungeon, difficulty
        name = names[0]
        modes = [mode for mode in self.content[name] if mode_key(mode) == mode_key(difficulty or '')]
        return name, modes[0] if len(modes) == 1 else difficulty

    def match(self, dungeon, difficulty, gate, raid=False, exact_only=False, *, stored=False):
        names = self._candidates(dungeon, stored=stored, exact_only=exact_only)
        if len(names) != 1:
            return dict(status='ambiguous' if names else 'unmatched')
        name = names[0]
        modes = [mode for mode in self.content[name] if mode_key(mode) == mode_key(difficulty)]
        if len(modes) != 1:
            return dict(status='ambiguous' if modes else 'unmatched')
        mode = modes[0]
        gates = self.content[name][mode]
        gate_name = f'{gate}관문'
        if gate_name not in gates or (raid and len(gates) != 1):
            return dict(status='unmatched')
        return dict(status='matched', dungeonName=name, fieldName=self.catalog.field_names[name],
                    difficulty=mode, gateName=gate_name,
                    version=copy.deepcopy(self.version), values=copy.deepcopy(gates[gate_name]))

    def reward_rows(self):
        return self.catalog.rows()

    def saved_reward(self, match):
        if 'contentName' in match:
            match=dict(match,dungeonName=match['contentName'],gateName=f"{match['gateNumber'] or 1}관문")
        names = self.stored_candidates(match.get('fieldName') or match['dungeonName'])
        if len(names) != 1:
            return None
        modes = [mode for mode in self.content[names[0]] if mode_key(mode) == mode_key(match['difficulty'])]
        return self.content[names[0]][modes[0]].get(match['gateName']) if len(modes) == 1 else None

    def record(self, record):
        canonical_input='contentName' in record and 'dungeonName' not in record
        row = recognition_record(record) if canonical_input else copy.deepcopy(record)
        # Re-observation preserves the saved decision; explicit refresh is separate.
        if 'catalogMatch' in row:
            return copy.deepcopy(record)
        if 'ocrOriginal' not in row:
            row['ocrOriginal'] = {k: row.get(k) for k in ('dungeonName', 'difficulty', 'gate')}
        source=(row.get('ocrOriginal') or {}).get('dungeonName') or row['dungeonName']
        result = self.match(source, row['difficulty'], row['gate'],
                            row.get('completionScope') == 'raid',exact_only=canonical_input)
        row['catalogMatch'] = result
        names = self.dungeon_candidates(source)
        if len(names) == 1:
            row['dungeonName'] = names[0]
        if result['status'] == 'matched':
            row.update(dungeonName=result['dungeonName'], difficulty=result['difficulty'],
                       gateName=result['gateName'])
        return canonical(row) if canonical_input else row

    def refresh_record_match(self, record):
        """Attach an exact, unique catalog reward to an unmatched canonical record."""
        value=validate(record)
        if (value.get('catalogMatch') or {}).get('status')=='matched':return value
        source=(value.get('ocrOriginal') or {}).get('contentName') or (value.get('catalogMatch') or {}).get('fieldName') or value['contentName']
        names=self._candidates(source,exact_only=True)
        if len(names)!=1:return value
        row=recognition_record(value)
        match=self.match(source,value['difficulty'],row['gate'],
                         value['gateNumber']==0,exact_only=True)
        if match['status']!='matched':return value
        row.update(dungeonName=match['dungeonName'],difficulty=match['difficulty'],catalogMatch=match)
        return validate(canonical(row))


class FileContentMatcher:
    """Refresh an immutable matcher only when the atomically saved cache changes."""
    def __init__(self, root, directory):
        self.root, self.directory = root, directory
        self.signature = None
        self.matcher = ContentMatcher()

    def __call__(self):
        try:
            cache = ContentCache(self.directory, load_settings(self.root))
            stat = cache.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature != self.signature:
                self.matcher = ContentMatcher(cache.load())
                self.signature = signature
        except (OSError, ContentError):
            pass  # No network or capture failure; keep the last valid catalog.
        return self.matcher


def record_detail(record, cached=None, *, matcher=None):
    """Use a saved link exactly; never fuzzy-remap an unmatched historical record."""
    matcher = ContentMatcher(cached) if matcher is None else matcher
    record=recognition_record(record)
    match = record.get('catalogMatch')
    if match is None:  # Ignore formatting in older/imported names, but don't guess typos.
        result = matcher.match(record['dungeonName'], record['difficulty'],
                    record['gate'], record.get('completionScope') == 'raid', exact_only=True, stored=True)
        if result['status'] == 'matched':
            return dict(status='matched', values=result['values'], source='현재 공용 데이터')
        return dict(status=result['status'])
    if match['status'] != 'matched':
        return dict(status=match['status'])
    values = matcher.saved_reward(match)
    return dict(status='matched', values=values if values is not None else match['values'],
                source='현재 공용 데이터' if values is not None else '저장 당시 공용 데이터')
