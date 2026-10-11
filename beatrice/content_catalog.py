"""Public dungeon schema and reward index; no transport, SQL or UI dependencies."""
import copy
import math


class ContentError(Exception):
    pass


def _label(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 200 and not any(ord(c) < 32 for c in value)


def validate_reward(value):
    if not isinstance(value, dict) or set(value) != {'gold', 'fee', 'bound_percentage'}:
        raise ContentError('각 관문에는 gold, fee, bound_percentage가 필요합니다.')
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10**12 for k in ('gold', 'fee')):
        raise ContentError('gold와 fee는 0 이상의 정수여야 합니다.')
    ratio = value['bound_percentage']
    if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise ContentError('bound_percentage는 0~1 사이 숫자여야 합니다.')


def _entries(content):
    # Older caches remain readable until a successful download replaces them.
    if isinstance(content, dict):
        for name, modes in content.items():
            if not isinstance(modes, dict):
                raise ContentError('던전별 난이도 객체가 필요합니다.')
            yield name, name, modes
    elif isinstance(content, list):
        seen = set()
        for dungeon in content:
            if not isinstance(dungeon, dict) or set(dungeon) != {'name', 'field_name', 'difficulties'}:
                raise ContentError('던전에는 name, field_name, difficulties가 필요합니다.')
            name, field_name = dungeon['name'], dungeon['field_name']
            if not _label(name) or name in seen or not _label(field_name):
                raise ContentError('던전 name·field_name 또는 중복 이름을 확인해주세요.')
            seen.add(name)
            difficulties = dungeon['difficulties']
            if not isinstance(difficulties, list) or not 1 <= len(difficulties) <= 30:
                raise ContentError('difficulties에는 난이도 배열이 필요합니다.')
            modes = {}
            for difficulty in difficulties:
                if not isinstance(difficulty, dict) or set(difficulty) != {'name', 'gates'}:
                    raise ContentError('난이도에는 name과 gates가 필요합니다.')
                mode, gates = difficulty['name'], difficulty['gates']
                if not _label(mode) or mode in modes or not isinstance(gates, list) or not 1 <= len(gates) <= 8:
                    raise ContentError('난이도 이름·중복 또는 관문 배열을 확인해주세요.')
                converted = {}
                for expected, gate in enumerate(gates, 1):
                    if (not isinstance(gate, dict) or set(gate) != {'number', 'gold', 'fee', 'bound_percentage'}
                            or type(gate['number']) is not int or gate['number'] != expected):
                        raise ContentError('관문 number는 1부터 순서대로 필요합니다.')
                    converted[f'{expected}관문'] = {k: gate[k] for k in ('gold', 'fee', 'bound_percentage')}
                modes[mode] = converted
            yield name, field_name, modes
    else:
        raise ContentError('공용 데이터에는 던전 배열이 필요합니다.')


def validate_content(content):
    if not isinstance(content, (list, dict)) or not 1 <= len(content) <= 500:
        raise ContentError('공용 던전 데이터는 1~500개여야 합니다.')
    count = 0
    for name, field_name, modes in _entries(content):
        if not _label(name) or not _label(field_name) or not 1 <= len(modes) <= 30:
            raise ContentError('던전 또는 난이도 형식이 올바르지 않습니다.')
        for mode, gates in modes.items():
            if not _label(mode) or not isinstance(gates, dict) or not 1 <= len(gates) <= 8:
                raise ContentError('난이도 또는 관문 형식이 올바르지 않습니다.')
            if set(gates) != {f'{i}관문' for i in range(1, len(gates) + 1)}:
                raise ContentError('공용 관문은 1관문부터 순서대로 필요합니다.')
            for value in gates.values():
                validate_reward(value)
                count += 1
    if count > 10000:
        raise ContentError('공용 관문 데이터가 너무 많습니다.')
    return content


class ContentCatalog:
    """One normalized index for both schema versions, preserving field/display names."""
    def __init__(self, content=None):
        self.rewards, self.field_names = {}, {}
        if content is not None:
            for name, field_name, modes in _entries(validate_content(content)):
                self.rewards[name] = copy.deepcopy(modes)
                self.field_names[name] = field_name

    def rows(self):
        return [dict(dungeon=name, mode=mode, gate=gate, **copy.deepcopy(values))
                for name, modes in self.rewards.items() for mode, gates in modes.items()
                for gate, values in gates.items()]
