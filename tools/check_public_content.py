"""Read public Drive content and verify local cache; no Google account required."""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from beatrice.content_catalog import ContentCatalog
from beatrice.public_assets import PublicAssetCache
from beatrice.public_content import ContentCache, ContentError, PublicContentClient, load_api_key, load_settings


def main():
    settings = load_settings(ROOT)
    cache = ContentCache(ROOT / 'outputs/public-content-check', settings)
    client = PublicContentClient(load_api_key(ROOT), settings, threading.Event())
    result = client.refresh(cache.load())
    cache.save(result)
    if cache.load() != result:
        raise ContentError('공용 데이터 캐시 검증 실패')
    content = result['content']
    catalog = ContentCatalog(content)
    modes = sum(len(value) for value in catalog.rewards.values())
    gates = len(catalog.rows())
    print(f'PASS: 최상위 폴더 -> JSON -> {settings["fileName"]} 조회', flush=True)
    print(f'PASS: 던전 {len(content)}개 / 난이도 항목 {modes}개 / 관문 항목 {gates}개 검증 및 로컬 보관', flush=True)
    again = client.refresh(result)
    if again['content'] != content:
        raise ContentError('재조회 중 공용 데이터가 변경되었습니다.')
    print('PASS: 변경 여부 재확인 및 캐시 재사용. 원격 파일은 변경하지 않았습니다.', flush=True)
    assets = PublicAssetCache(ROOT / 'outputs/public-content-check', settings)
    bundle = assets.prepare(client)
    assets.save(bundle)
    if assets.load() != bundle:
        raise ContentError('문양·이미지 보관 검증 실패')
    again = assets.prepare(client)
    if again['downloadedFiles'] != 0 or again.get('downloadedEmblems', 0) != 0:
        raise ContentError('변경 없는 문양·이미지가 다시 다운로드되었습니다.')
    print(f"PASS: 문양 SVG {len(bundle.get('emblems', {}))}개 / Drive 이미지 {len(bundle['images'])}개 보관 및 재사용", flush=True)
    if assets.emblem_path('워로드', bundle) is None:
        raise ContentError('직업명으로 SVG 캐시를 찾지 못했습니다.')
    print('PASS: 직업명으로 로컬 SVG 경로 조회', flush=True)
    for job, message in bundle.get('emblemErrors', {}).items():
        print(f"WARN: {job} | {bundle['emblem']['content'][job]} | {message}", flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ContentError, OSError):
        print('공용 데이터 연결 검증에 실패했습니다. API 설정·공유 권한·로컬 저장 경로를 확인해주세요.', flush=True)
        sys.exit(1)
