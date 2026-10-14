"""Download and verify the pinned embedded Python and 7-Zip build tools."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import zipfile
import argparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'build/runtime-downloads'
DOWNLOADS = {
    'Microsoft.VCLibs.x64.14.00.Desktop.appx': (
        'https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx',
        'b56a9101f706f9d95f815f5b7fa6efbac972e86573d378b96a07cff5540c5961'),
    'python-3.12.10-embed-amd64.zip': (
        'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip',
        '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'),
    'lzma2603.7z': (
        'https://github.com/ip7z/7zip/releases/download/26.03/lzma2603.7z',
        '86c213f752520ab5325c310f50bef63ec344b56dd1c80b0246d06dc6cec953b2'),
    '7zr.exe': (
        'https://www.7-zip.org/a/7zr.exe',
        '256feca8e274e5da655e2a284fabafd9f554365eb164862089dacd4e8276d282'),
}


def main(offline=False):
    DEST.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in DOWNLOADS.items():
        path = DEST / name
        if not path.exists():
            if offline:raise FileNotFoundError('Offline cache missing: ' + name)
            partial = path.with_suffix(path.suffix + '.part')
            with urlopen(url, timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
                raise ValueError('Download checksum mismatch: ' + name)
            partial.replace(path)
        with path.open('rb') as file:
            if hashlib.file_digest(file, 'sha256').hexdigest() != expected:
                raise ValueError('Cached download checksum mismatch: ' + name)
        print('Verified', name, flush=True)
    sdk = ROOT / 'build/7zip-sdk'
    subprocess.run([str(DEST / '7zr.exe'), 'x', str(DEST / 'lzma2603.7z'),
                    '-o' + str(sdk), '-y'], check=True, stdout=subprocess.DEVNULL)
    for name in ('bin/7zSD.sfx', 'DOC/installer.txt', 'DOC/lzma-sdk.txt'):
        if not (sdk / name).is_file():
            raise ValueError('7-Zip SDK file missing: ' + name)
    vc_runtime = ROOT / 'build/vc-runtime'
    vc_runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DEST / 'Microsoft.VCLibs.x64.14.00.Desktop.appx') as bundle:
        for name in bundle.namelist():
            if name.startswith(('msvcp140', 'vcruntime140', 'concrt140')) and name.endswith('.dll'):
                (vc_runtime / name).write_bytes(bundle.read(name))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true')
    main(offline=parser.parse_args().offline)
