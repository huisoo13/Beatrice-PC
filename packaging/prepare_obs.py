"""Download an app-local, pinned OBS runtime; never use an installed OBS."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
VERSION='32.0.4'
DEST=ROOT/'build/obs-runtime'

def fetch(url):
    return urlopen(Request(url,headers={'User-Agent':'BeatricePC-build'}),timeout=60)

def main():
    downloads=ROOT/'build/runtime-downloads';downloads.mkdir(parents=True,exist_ok=True)
    with fetch(f'https://api.github.com/repos/obsproject/obs-studio/releases/tags/{VERSION}') as response:
        release=json.load(response)
    asset=next(a for a in release['assets'] if a['name']==f'OBS-Studio-{VERSION}-Windows-x64.zip')
    digest=asset.get('digest','')
    if not digest.startswith('sha256:'):raise RuntimeError('Official release asset has no SHA-256 digest')
    archive=downloads/asset['name']
    if not archive.exists():
        partial=archive.with_suffix('.part')
        with fetch(asset['browser_download_url']) as response,partial.open('wb') as output:
            shutil.copyfileobj(response,output)
        partial.replace(archive)
    with archive.open('rb') as file:actual=hashlib.file_digest(file,'sha256').hexdigest()
    if actual!=digest.split(':',1)[1]:raise RuntimeError('OBS archive checksum mismatch')
    DEST.mkdir(parents=True,exist_ok=True)
    # Only runtime and capture modules, no obs64.exe/OBS UI/virtual camera.
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            relative=Path(name)
            selected=(name.startswith('bin/64bit/') and name.endswith('.dll')
                      or name.startswith('data/libobs/')
                      or (name.startswith('data/obs-plugins/win-capture/')
                          and not relative.name.startswith('obs-vulkan') and not name.endswith('.pdb'))
                      or name.startswith('data/obs-plugins/image-source/')
                      or name in ('obs-plugins/64bit/win-capture.dll','obs-plugins/64bit/image-source.dll'))
            if not selected or name.endswith('/'):continue
            target=(DEST/relative).resolve()
            if not target.is_relative_to(DEST.resolve()):raise RuntimeError('Unsafe archive path')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bundle.read(name))
    # Keep full corresponding source alongside redistributed binaries.
    source_url=f'https://github.com/obsproject/obs-studio/archive/refs/tags/{VERSION}.zip'
    source=DEST/'licenses'/f'obs-studio-{VERSION}-source.zip';source.parent.mkdir(exist_ok=True)
    if not source.exists():
        with fetch(source_url) as response,source.open('wb') as output:shutil.copyfileobj(response,output)
    with fetch(f'https://raw.githubusercontent.com/obsproject/obs-studio/{VERSION}/COPYING') as response:
        (source.parent/'OBS-COPYING.txt').write_bytes(response.read())
    manifest=dict(version=VERSION,archiveSha256=actual,sourceUrl=source_url,
                  origin=asset['browser_download_url'],license='GPL-2.0-or-later',captureApi='DirectX/OpenGL')
    # No Vulkan implicit-layer installation or shared ProgramData hook files.
    for path in (DEST/'data/obs-plugins/win-capture').glob('obs-vulkan*.json'):path.unlink()
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Prepared app-local OBS engine:',DEST,flush=True)

if __name__=='__main__':main()
