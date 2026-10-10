"""OS file lock: duplicate hosts are rejected; process exit releases the lock."""
import os
import time
from pathlib import Path


class InstanceLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def acquire(self,timeout=.25):
        if self.file is not None:return True
        file=self.path.open('a+b')
        if file.seek(0,2)==0:file.write(b'0');file.flush()
        file.seek(0)
        deadline=time.monotonic()+max(0,timeout)
        while True:
            try:
                file.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                # Windows can release process-owned locks shortly after its
                # process handle signals exit. Allow a bounded restart grace.
                if time.monotonic()>=deadline:
                    file.close();return False
                time.sleep(.01)
        self.file=file;return True
    def release(self):
        file=self.file
        if file is None:return
        self.file=None
        try:
            file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_UN)
        finally:file.close()
