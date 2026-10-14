"""Keep exact PyPI source distributions for bundled GPL-family components."""
from pathlib import Path
import hashlib
import json
import shutil
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'build/third-party-sources'
    destination.mkdir(parents=True, exist_ok=True)
    sources = []
    for name, version in [('ultralytics', '8.4.152'), ('ultralytics-thop', '2.1.6'),
                          ('ultralytics-platform', '0.1.48'), ('crc32c', '2.9.post0'),
                          ('python-bidi', '0.6.11')]:
        with urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
            release = json.load(response)
        asset = next(item for item in release['urls'] if item['packagetype'] == 'sdist')
        path = destination / asset['filename']
        if not path.exists():
            partial = path.with_suffix(path.suffix + '.part')
            with urlopen(asset['url'], timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != asset['digests']['sha256']:
                raise ValueError('Source checksum mismatch: ' + name)
            partial.replace(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset['digests']['sha256']:
            raise ValueError('Source checksum mismatch: ' + name)
        sources.append(dict(name=name, version=version, file=path.name,
                            url=asset['url'], sha256=asset['digests']['sha256']))
        print('Prepared source:', path.name, flush=True)
    (destination / 'manifest.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
