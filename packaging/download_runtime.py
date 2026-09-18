from pathlib import Path
from urllib.request import urlretrieve
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'build/runtime-downloads'
URLS={
 'python-3.12.10-embed-amd64.zip':'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip',
 'lzma2603.7z':'https://github.com/ip7z/7zip/releases/download/26.03/lzma2603.7z',
}
DEST.mkdir(parents=True,exist_ok=True)
for name,url in URLS.items():
 path=DEST/name
 if not path.exists():
  temp=path.with_suffix(path.suffix+'.part');urlretrieve(url,temp);temp.replace(path)
 print(path)
