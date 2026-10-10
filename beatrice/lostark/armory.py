"""Character armory endpoints; preserve official response field names."""
from .characters import character_path


class ArmoryApi:
    def __init__(self, client):
        self._client = client

    def _get(self, name, section=''):
        path = '/armories/characters/' + character_path(name)
        return self._client.request('GET', path + ('/' + section if section else ''))

    def full(self, name):
        return self._get(name)

    def equipment(self, name):
        return self._get(name, 'equipment')

    def avatars(self, name):
        return self._get(name, 'avatars')

    def combat_skills(self, name):
        return self._get(name, 'combat-skills')

    def engravings(self, name):
        return self._get(name, 'engravings')

    def cards(self, name):
        return self._get(name, 'cards')

    def gems(self, name):
        return self._get(name, 'gems')

    def colosseums(self, name):
        return self._get(name, 'colosseums')

    def collectibles(self, name):
        return self._get(name, 'collectibles')

    def ark_passive(self, name):
        return self._get(name, 'arkpassive')

    def ark_grid(self, name):
        return self._get(name, 'arkgrid')
