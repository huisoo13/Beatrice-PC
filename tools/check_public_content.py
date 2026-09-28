"""Read public Drive content and verify local cache; no Google account required."""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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
    modes = sum(len(value) for value in content.values())
    gates = sum(len(g) for value in content.values() for g in value.values())
    print(f'PASS: 최상위 폴더 -> JSON -> {settings["fileName"]} 조회', flush=True)
    print(f'PASS: 던전 {len(content)}개 / 난이도 항목 {modes}개 / 관문 항목 {gates}개 검증 및 로컬 보관', flush=True)
    again = client.refresh(result)
    if again['content'] != content:
        raise ContentError('재조회 중 공용 데이터가 변경되었습니다.')
    print('PASS: 변경 여부 재확인 및 캐시 재사용. 원격 파일은 변경하지 않았습니다.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ContentError, OSError):
        print('공용 데이터 연결 검증에 실패했습니다. API 설정·공유 권한·로컬 저장 경로를 확인해주세요.', flush=True)
        sys.exit(1)
