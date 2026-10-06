"""공식 Windows 런타임/휠을 7-Zip SFX로 묶습니다. Windows 실행 검증과는 별개입니다."""
from pathlib import Path
import zipfile,shutil,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
stage=ROOT/'build/windows-app'
if stage.exists():shutil.rmtree(stage)  # 이 스크립트가 생성한 임시 패키지 폴더만 재구성
stage.mkdir(parents=True,exist_ok=True)
runtime=stage/'runtime';runtime.mkdir(exist_ok=True)
with zipfile.ZipFile(ROOT/'build/runtime-downloads/python-3.12.10-embed-amd64.zip') as z:z.extractall(runtime)
site=runtime/'Lib/site-packages';site.mkdir(parents=True,exist_ok=True)
wheel_manifest=[]
for wheel in sorted((ROOT/'build/windows-wheels').glob('*.whl')):
    if wheel.name.startswith(('torch-','torchvision-')) and not wheel.name.startswith(('torch-2.8.0-','torchvision-0.23.0-')):continue
    if wheel.name.lower().startswith('easyocr-'):continue
    # contrib가 필요한 PaddleOCR와 다른 OpenCV 의존성은 동일 cv2 바이너리를 공유합니다.
    skip_cv=wheel.name.startswith(('opencv_python-','opencv_python_headless-'))
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.endswith('/'):continue
            if skip_cv and '.dist-info/' not in name:continue
            parts=Path(name).parts
            if parts[0].endswith('.data'):
                if parts[1] not in ('purelib','platlib'):continue
                relative=Path(*parts[2:])
            else:relative=Path(name)
            target=site/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    wheel_manifest.append(dict(file=wheel.name,sha256=hashlib.sha256(wheel.read_bytes()).hexdigest()))
# App-local VC runtime: Qt 공식 휠에서 제공하는 런타임을 Python 실행 파일 옆에 배치합니다.
for pattern in ('msvcp140*.dll','vcruntime140*.dll','concrt140.dll'):
    for dll in (site/'PySide6').glob(pattern):shutil.copy2(dll,runtime/dll.name)
(runtime/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n..\nimport site\n')
for folder in ('beatrice','config'):
    shutil.copytree(ROOT/folder,stage/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
# The engine is part of the app, never resolved from an installed OBS Studio.
obs_runtime=ROOT/'build/obs-runtime'
if not (obs_runtime/'manifest.json').is_file():
    raise ValueError('앱 내장 OBS 엔진을 packaging/prepare_obs.py로 먼저 준비해주세요.')
if list((obs_runtime/'data/obs-plugins/win-capture').glob('obs-vulkan*.json')):
    raise ValueError('배포에 Vulkan 전역 등록 설정을 포함할 수 없습니다.')
shutil.copytree(obs_runtime,stage/'obs-runtime',ignore=shutil.ignore_patterns('*.pdb'))
shutil.copy2(ROOT/'LICENSE',stage/'LICENSE')
# Corresponding Beatrice source accompanies the GPL engine distribution.
source_zip=stage/'obs-runtime/licenses/beatrice-source.zip'
with zipfile.ZipFile(source_zip,'w',compression=zipfile.ZIP_DEFLATED) as source:
    for folder in ('beatrice','config','packaging','tests'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                source.write(path,str(path.relative_to(ROOT)))
    for name in ('LICENSE','README.md','app_launcher.py','run-as-admin.cmd'):
        source.write(ROOT/name,name)
shutil.copytree(ROOT/'models/paddleocr/korean_PP-OCRv5_mobile_rec_infer',stage/'models/paddleocr/korean_PP-OCRv5_mobile_rec_infer',dirs_exist_ok=True)
ui_config=json.loads((ROOT/'config/ui-regions.json').read_text(encoding='utf-8'))
active_config=ui_config
if active_config['mode']!='yolo':raise ValueError('YOLO 설정만 배포할 수 있습니다.')
if active_config['mode']=='yolo':
    model_configs=([json.loads((ROOT/active_config[role]).read_text(encoding='utf-8')) for role in ('characterConfig','dungeonConfig')]
                   if active_config.get('architecture')=='split' else [active_config])
    model_configs.append(json.loads((ROOT/'config/completion-overlay.json').read_text(encoding='utf-8')))
    for model_config in model_configs:
        if model_config.get('elementConfig'):
            model_configs.append(json.loads((ROOT/model_config['elementConfig']).read_text(encoding='utf-8')))
        paths=[model_config['weights']]
        for name in paths:
            weights=Path(name)
            if weights.is_absolute() or '..' in weights.parts:raise ValueError('배포용 모델은 프로젝트 내부 상대 경로여야 합니다.')
            if not (ROOT/weights).is_file():raise ValueError('배포할 모델 파일이 없습니다.')
            (stage/weights).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/weights,stage/weights)
shutil.copy2(ROOT/'app_launcher.py',stage/'app_launcher.py')
shutil.copy2(ROOT/'run-as-admin.cmd',stage/'run-as-admin.cmd')
shutil.copy2(ROOT/'build/7zip-sdk/DOC/installer.txt',stage/'7zip-SFX-license.txt')
(stage/'package-manifest.json').write_text(json.dumps(dict(python='3.12.10 embedded amd64',wheels=wheel_manifest,windowsRuntimeTested=False),indent=2))
print('Staged',sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()),'bytes',flush=True)
if '--stage-only' in sys.argv:sys.exit()
import py7zr
archive=ROOT/'build/BeatricePC.7z'
with py7zr.SevenZipFile(archive,'w',filters=[{'id':py7zr.FILTER_LZMA2,'preset':3}]) as z:
    for p in sorted(stage.rglob('*')):
        if p.is_file():z.write(p,str(p.relative_to(stage)))
config=';!@Install@!UTF-8!\nTitle="Beatrice PC"\nRunProgram="runtime\\\\pythonw.exe app_launcher.py"\n;!@InstallEnd@!\n'
out=ROOT/'dist/BeatricePC.exe';out.parent.mkdir(exist_ok=True)
with out.open('wb') as dest:
    dest.write((ROOT/'build/7zip-sdk/bin/7zSD.sfx').read_bytes());dest.write(config.encode())
    with archive.open('rb') as source:shutil.copyfileobj(source,dest)
with out.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
(out.parent/'BeatricePC.exe.sha256').write_text(digest+'  BeatricePC.exe\n')
print(out, out.stat().st_size,digest,flush=True)
