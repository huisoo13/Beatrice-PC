"""사용자가 검수한 원본 픽셀 좌표를 YOLO 정규화 좌표로 변환합니다."""
import hashlib
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, default=ROOT / 'data/annotations/review-v1.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/labels/review-v1')
    args = parser.parse_args()
    data = json.loads(args.annotations.read_text())
    if data['reviewStatus'] != 'approved':
        raise ValueError('검수 완료된 라벨만 내보낼 수 있습니다.')
    output = args.output.resolve()
    prepared = []
    for item in data['images']:
        source = ROOT / item['path']
        if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f"원본 변경 감지: {source}")
        width, height = item['width'], item['height']
        lines = []
        for box in item['boxes']:
            x1, y1, x2, y2 = box['xyxy']
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError('박스가 이미지 범위를 벗어났습니다.')
            values = [(x1+x2)/(2*width), (y1+y2)/(2*height),
                      (x2-x1)/width, (y2-y1)/height]
            encoded = [f'{v:.9f}' for v in values]
            cx, cy, bw, bh = map(float, encoded)
            restored = [(cx-bw/2)*width, (cy-bh/2)*height,
                        (cx+bw/2)*width, (cy+bh/2)*height]
            if max(abs(a-b) for a,b in zip(restored,box['xyxy'])) > 0.001:
                raise ValueError('좌표 왕복 검증 실패')
            lines.append(str(data['classes'].index(box['state']))+' '+' '.join(encoded))
        prepared.append((source.stem+'.txt', '\n'.join(lines)+'\n', item))
    if len({name for name,_,_ in prepared}) != len(prepared):
        raise ValueError('중복 이미지 파일명')
    output.mkdir(parents=True, exist_ok=True)
    for name, content, _ in prepared:
        destination = output/name
        if destination.exists() and destination.read_text() != content:
            raise ValueError(f'기존 라벨과 다릅니다. 새 버전으로 내보내세요: {destination}')
    for name, content, _ in prepared:
        (output/name).write_text(content)
    manifest = {'classes': data['classes'], 'splitStatus': 'unassigned',
                'images': [{'image': i['path'], 'label': str((output/name).relative_to(ROOT)),
                            'sessionId': i['sessionId']} for name,_,i in prepared]}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(prepared)}장 / {sum(len(i[2]["boxes"]) for i in prepared)}개 박스 내보내기 완료')
    print('원본 해시 및 좌표 왕복 검증 통과. 학습/검증/평가 분할은 아직 미정입니다.')


if __name__ == '__main__':
    main()
