"""Safe public exceptions; never retain credential-bearing HTTP exceptions."""
class DriveError(Exception):
    def __init__(self, message, *, status=None, reason=None, retry_after=None):
        super().__init__(message)
        self.status, self.reason, self.retry_after = status, reason, retry_after

class DriveAuthError(DriveError): pass
class DrivePermissionError(DriveError): pass
class DriveNotFoundError(DriveError): pass
class DriveRateLimitError(DriveError): pass
class DriveNetworkError(DriveError): pass
class DriveResponseError(DriveError): pass
class DriveCancelledError(DriveError): pass
