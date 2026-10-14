"""A corrupt or missing runtime must never be extracted or executed."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('runtime_download',
    Path(__file__).resolve().parents[1]/'packaging/download_runtime.py')
runtime=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeDownloadTests(unittest.TestCase):
    def test_corrupt_cache_stops_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)
            (destination/'7zr.exe').write_bytes(b'corrupt')
            downloads={'7zr.exe':('https://example.invalid/tool',hashlib.sha256(b'expected').hexdigest())}
            with patch.object(runtime,'DEST',destination), patch.object(runtime,'DOWNLOADS',downloads), \
                    patch.object(runtime.subprocess,'run') as run, patch.object(runtime,'urlopen') as fetch:
                with self.assertRaisesRegex(ValueError,'Cached download checksum mismatch'):
                    runtime.main()
                run.assert_not_called()
                fetch.assert_not_called()

    def test_offline_missing_cache_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            downloads={'7zr.exe':('https://example.invalid/tool','0'*64)}
            with patch.object(runtime,'DEST',Path(directory)), patch.object(runtime,'DOWNLOADS',downloads), \
                    patch.object(runtime.subprocess,'run') as run, patch.object(runtime,'urlopen') as fetch:
                with self.assertRaisesRegex(FileNotFoundError,'Offline cache missing'):
                    runtime.main(offline=True)
                run.assert_not_called()
                fetch.assert_not_called()


if __name__=='__main__':unittest.main()
