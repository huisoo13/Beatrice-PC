"""Basic profile and characters on the same account."""
from urllib.parse import quote


def character_path(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or any(
            ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('조회할 캐릭터명을 입력해주세요.')
    return quote(name.strip(), safe='')


class CharactersApi:
    def __init__(self, client):
        self._client = client

    def profile(self, name):
        return self._client.request('GET', '/armories/characters/' + character_path(name) + '/profiles')

    def siblings(self, name):
        return self._client.request('GET', '/characters/' + character_path(name) + '/siblings')
