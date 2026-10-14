"""Refresh triggers and write-once record snapshots through public module APIs."""


class CharacterRecordService:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        self._current_name = None
        self._known = set()
        self._pending = {}
        store.remove_character_info_source()
        for row in store.history_records():
            if row['isTest']: continue
            self._known.add(row['recordId'])
            if 'characterInfo' not in row:
                store.set_character_info(row['recordId'], catalog.info(row['characterName']))
        self._pending = {row['recordId']: row['characterName'] for row in store.pending_character_records()}
        for name in set(self._pending.values()): catalog.refresh(name)

    def sync(self, current_name, records):
        changed = False
        # Complete only rows already waiting on this request, before adding new rows.
        for name, info in self.catalog.take_refresh_results():
            for identifier, pending_name in list(self._pending.items()):
                if pending_name == name:
                    changed = self.store.set_character_info(identifier, info, finalize_pending=True) or changed
                    self._pending.pop(identifier, None)
        if not self.catalog.key_available():
            for identifier, name in list(self._pending.items()):
                changed = self.store.set_character_info(identifier, self.catalog.info(name), finalize_pending=True) or changed
                self._pending.pop(identifier, None)
        if changed:
            records = [row for row in self.store.history_records() if not row['isTest']]
        identifiers = {row['recordId'] for row in records}
        waiting = {row['recordId'] for row in self.store.pending_character_records()}
        self._known.intersection_update(identifiers)
        for identifier in list(self._pending):
            if identifier not in identifiers: self._pending.pop(identifier, None)
        if current_name != self._current_name:
            self._current_name = current_name
            self.catalog.refresh(current_name)
        for row in records:
            identifier, name = row['recordId'], row['characterName']
            if identifier in self._known:
                if identifier in waiting and identifier not in self._pending:
                    self._pending[identifier] = name
                    self.catalog.refresh(name)
                continue
            self._known.add(identifier)
            if 'characterInfo' in row and identifier not in waiting:
                # Incoming/restored records retain their saved snapshot.
                continue
            changed = self.store.set_character_info(identifier, self.catalog.info(name), pending=True) or changed
            self._pending[identifier] = name
            self.catalog.refresh(name)
            if not self.catalog.key_available():
                changed = self.store.set_character_info(identifier, self.catalog.info(name), finalize_pending=True) or changed
                self._pending.pop(identifier, None)
        return changed
