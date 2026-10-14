"""Smoke-test the prepared Windows runtime without launching the app or game."""
from pathlib import Path
import ctypes
import hashlib
import json
import os
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'build/windows-app'


def main():
    if Path(sys.executable).resolve() != (STAGE / 'runtime/python.exe').resolve():
        raise RuntimeError('Run with build/windows-app/runtime/python.exe')
    required = [
        'native-ui/BeatricePC.exe', 'native-ui/BeatricePC.dll', 'native-ui/BeatricePC.pri',
        'native-ui/Assets/beatrice.ico', 'native-ui/Assets/tokens.json',
        'runtime/python312.dll', 'runtime/msvcp140.dll', 'runtime/vcruntime140.dll',
        'runtime/LICENSE.txt', 'obs-runtime/licenses/OBS-COPYING.txt',
        'obs-runtime/licenses/obs-studio-32.0.4-source.zip',
        'obs-runtime/licenses/beatrice-source.zip', 'licenses/sources/manifest.json',
        'licenses/sources/lzma2603.7z', 'licenses/third-party.json',
    ]
    for name in required:
        if not (STAGE / name).is_file():
            raise RuntimeError('Missing staged file: ' + name)
    for name in ('google-session.bin', 'lostark-api-key.bin', 'records.sqlite3'):
        if list(STAGE.rglob(name)):
            raise RuntimeError('Personal data in stage: ' + name)
    for path in STAGE.rglob('*'):
        if 'pyside6' in path.name.lower() or 'shiboken6' in path.name.lower():
            raise RuntimeError('Obsolete Qt runtime in stage')
    source_path = STAGE / 'obs-runtime/licenses/beatrice-source.zip'
    with zipfile.ZipFile(source_path) as source:
        if source.testzip() is not None:
            raise RuntimeError('Source ZIP CRC failed')
        for name in ('ui/Beatrice.App/Assets/beatrice.ico',
                     'packaging/requirements-windows-lock.txt', 'packaging/prepare_windows.ps1'):
            if name not in source.namelist():
                raise RuntimeError('Incomplete app source: ' + name)
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['PADDLE_PDX_CACHE_HOME'] = str(ROOT / 'outputs/package-verification/paddlex')
    os.environ['MPLCONFIGDIR'] = str(ROOT / 'outputs/package-verification/matplotlib')
    os.environ['YOLO_CONFIG_DIR'] = str(ROOT / 'outputs/package-verification/ultralytics')
    for name in ('PADDLE_PDX_CACHE_HOME','MPLCONFIGDIR','YOLO_CONFIG_DIR'):
        Path(os.environ[name]).mkdir(parents=True,exist_ok=True)
    import numpy as np
    import cv2
    import torch
    import torchvision
    import paddle
    import paddleocr
    from ultralytics import YOLO
    from beatrice.paddle_reader import PaddleKoreanReader
    versions = dict(python=sys.version.split()[0], numpy=np.__version__, opencv=cv2.__version__,
                    torch=torch.__version__, torchvision=torchvision.__version__,
                    paddle=paddle.__version__, paddleocr=paddleocr.__version__)
    print('Runtime imports:', versions, flush=True)
    models = []
    for path in sorted((STAGE / 'models').glob('*.pt')):
        model = YOLO(str(path))
        model.predict(np.zeros((64, 64, 3), dtype=np.uint8), imgsz=64, device='cpu', verbose=False)
        models.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print('YOLO inference:', path.name, flush=True)
    if len(models) != 6:
        raise RuntimeError('Expected six active YOLO models')
    reader = PaddleKoreanReader()
    reader.recognize(np.full((48, 320, 3), 255, dtype=np.uint8))
    print('Local PaddleOCR inference passed', flush=True)
    obs = STAGE / 'obs-runtime/bin/64bit'
    with os.add_dll_directory(str(obs)):
        libraries = [ctypes.CDLL(str(obs / 'obs.dll'))]
        for name in ('win-capture.dll', 'image-source.dll'):
            libraries.append(ctypes.CDLL(str(STAGE / 'obs-runtime/obs-plugins/64bit' / name)))
    print('OBS and capture DLL loading passed', flush=True)
    report = dict(versions=versions, models=models, ocrInference=True, obsDllLoad=True,
                  sourceZipCRC=True, personalDataExcluded=True, cleanPcTested=False,
                  gameCaptureTested=False)
    (STAGE / 'preparation-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Prepared Windows runtime verification passed', flush=True)


if __name__ == '__main__':
    main()
