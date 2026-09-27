"""Coalesce completion changes and pace retries; SQLite owns durable pending state."""


class AutoUploadSchedule:
    def __init__(self):
        self.reset()

    def reset(self):
        self.target = None
        self.first_change = self.last_change = 0
        self.retry_at = 0
        self.failures = 0

    def due(self, target, now):
        if target is None:
            self.reset()
            return False
        if self.target is None or target[:2] != self.target[:2]:
            self.reset()
            self.first_change = now
        if target != self.target:
            self.target = target
            self.last_change = now
        return now >= max(self.retry_at, min(self.last_change + 3, self.first_change + 15))

    def failed(self, now):
        self.failures += 1
        delay = min(300, 5 * 2 ** min(self.failures - 1, 6))
        self.retry_at = now + delay
        return delay
