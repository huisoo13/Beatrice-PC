"""Windows를 실행하지 않는 패키지 무결성 검사."""
from pathlib import Path
import hashlib,json,py7zr,pefile
root=Path(__file__).resolve().parents[1]
exe=root/'dist/BeatricePC.exe';archive=root/'build/BeatricePC.7z'
stub=root/'build/7zip-sdk/bin/7zSD.sfx'
with exe.open('rb') as f:
 assert f.read(2)==b'MZ'
 f.seek(stub.stat().st_size);header=f.read(256)
 assert b'RunProgram="runtime\\\\pythonw.exe app_launcher.py"' in header
with py7zr.SevenZipFile(archive) as z:
 names=set(z.getnames())
 required=['app_launcher.py','runtime/pythonw.exe','runtime/python.exe','runtime/python312.dll','runtime/python312._pth','beatrice/engine_worker.py','beatrice/native_bridge.py','beatrice/account_service.py','beatrice/drive_service.py','beatrice/weekly.py','native-ui/BeatricePC.exe','native-ui/BeatricePC.dll','native-ui/BeatricePC.pri','native-ui/Assets/tokens.json','models/character-regions.pt','models/dungeon-regions.pt','models/dungeon-elements.pt','models/paddleocr/korean_PP-OCRv5_mobile_rec_infer/inference.pdiparams','runtime/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll']
 for path in required:assert path in names,path
 obsolete={'beatrice/desktop.py','beatrice/drive_ui.py','beatrice/google_login_ui.py','beatrice/public_content_ui.py','beatrice/record_detail_ui.py'}
 assert not names.intersection(obsolete),names.intersection(obsolete)
 assert not any('easyocr' in path.lower() for path in names)
 assert not any('torch-2.14' in path for path in names)
 print('필수 파일 및 구성 확인:',len(names),'files',flush=True)
with py7zr.SevenZipFile(archive) as z:
 assert z.testzip() is None
print('압축 데이터 CRC 검사 통과',flush=True)
with exe.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
assert digest in (root/'dist/BeatricePC.exe.sha256').read_text()
report=dict(size=exe.stat().st_size,sha256=digest,archiveCRC=True,requiredFiles=True,windowsExecuted=False)
(root/'dist/verification.json').write_text(json.dumps(report,indent=2));print(report)
