"""Conservative, local-only matching of OCR observations to the public catalog."""
import copy
from difflib import SequenceMatcher
import re
import unicodedata

from .public_content import ContentCache, ContentError, load_settings, validate_content


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def mode_key(text):
    value = normalized(text)
    return value[:-2] if value.endswith('모드') else value


class ContentMatcher:
    def __init__(self, cached=None):
        self.content = copy.deepcopy(validate_content(cached['content'])) if cached else {}
        metadata = cached.get('metadata', {}) if cached else {}
        self.version = {k: metadata[k] for k in ('id', 'version', 'md5Checksum') if k in metadata}

    def dungeon_candidates(self, text):
        value = normalized(text)
        if not value:
            return []
        exact = [name for name in self.content if normalized(name) == value]
        if exact:
            return exact
        # Keep chapter/stage numbers distinct; short names are exact-only.
        if len(value) < 5:
            return []
        digits = re.findall(r'\d+', value)
        return [name for name in self.content
                if re.findall(r'\d+', normalized(name)) == digits
                and SequenceMatcher(None, value, normalized(name), autojunk=False).ratio() >= .85]

    def display_context(self, dungeon, difficulty):
        """Resolve UI labels using the same conservative name/mode rules as records."""
        names = self.dungeon_candidates(dungeon or '')
        if len(names) != 1: return dungeon, difficulty
        name = names[0]
        modes = [mode for mode in self.content[name] if mode_key(mode) == mode_key(difficulty or '')]
        return name, modes[0] if len(modes) == 1 else difficulty

    def match(self, dungeon, difficulty, gate, raid=False, exact_only=False):
        names = ([name for name in self.content if normalized(name) == normalized(dungeon)]
                 if exact_only else self.dungeon_candidates(dungeon))
        if len(names) != 1:
            return dict(status='ambiguous' if names else 'unmatched')
        name = names[0]
        modes = [mode for mode in self.content[name] if mode_key(mode) == mode_key(difficulty)]
        if len(modes) != 1:
            return dict(status='ambiguous' if modes else 'unmatched')
        mode = modes[0]
        gates = self.content[name][mode]
        gate_name = f'{gate}관문'
        # A whole-raid completion may refer to one catalog entry, never one of many.
        if gate_name not in gates or (raid and len(gates) != 1):
            return dict(status='unmatched')
        return dict(status='matched', dungeonName=name, difficulty=mode, gateName=gate_name,
                    version=copy.deepcopy(self.version), values=copy.deepcopy(gates[gate_name]))

    def record(self, record):
        row = copy.deepcopy(record)
        # Pending-character promotion must preserve the original matching decision.
        if 'catalogMatch' in row:
            return row
        row['ocrOriginal'] = {k: row.get(k) for k in ('dungeonName', 'difficulty', 'gate')}
        result = self.match(row['dungeonName'], row['difficulty'], row['gate'],
                            row.get('completionScope') == 'raid')
        row['catalogMatch'] = result
        if result['status'] == 'matched':
            row.update(dungeonName=result['dungeonName'], difficulty=result['difficulty'],
                       gateName=result['gateName'])
        return row


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


def record_detail(record, cached=None):
    """Use a saved link exactly; never fuzzy-remap an unmatched historical record."""
    match = record.get('catalogMatch')
    if match is None:  # Ignore formatting in older/imported names, but don't guess typos.
        result = ContentMatcher(cached).match(record['dungeonName'], record['difficulty'],
                    record['gate'], record.get('completionScope') == 'raid', exact_only=True)
        if result['status'] == 'matched':
            return dict(status='matched', values=result['values'], source='현재 공용 데이터')
        return dict(status=result['status'])
    if match['status'] != 'matched':
        return dict(status=match['status'])
    content = cached.get('content', {}) if cached else {}
    values = content.get(match['dungeonName'], {}).get(match['difficulty'], {}).get(match['gateName'])
    return dict(status='matched', values=values if values is not None else match['values'],
                source='현재 공용 데이터' if values is not None else '저장 당시 공용 데이터')
