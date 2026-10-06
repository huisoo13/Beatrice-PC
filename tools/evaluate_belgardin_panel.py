"""Compare old/new parent models on preserved same-session temporal holdout."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    import cv2
    import numpy as np
    import torch
    from beatrice.ui_regions import UIRegionDetector
    torch.set_num_threads(2)
    config = json.loads((ROOT / 'config/dungeon-regions.json').read_text(encoding='utf-8'))
    config.pop('elementConfig', None)
    models = [UIRegionDetector(config), UIRegionDetector(dict(config, weights=args.weights))]
    raw = ROOT / 'data/raw/belgardin-panel-1006'
    replay = json.loads((raw / 'replay.json').read_text(encoding='utf-8'))
    rows = []
    for row in replay['images']:
        path = ROOT / 'data/annotations' / row['path']
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        results = []
        for model in models:
            regions = model.locate(frame)
            entry = regions['dungeon_panel']
            expected = row['boxes'][0]['xyxy'] if row['boxes'] else None
            actual = entry.get('xyxy')
            overlap = 0
            if actual and expected:
                intersection = max(0,min(expected[2],actual[2])-max(expected[0],actual[0])) * max(0,min(expected[3],actual[3])-max(expected[1],actual[1]))
                union = (expected[2]-expected[0])*(expected[3]-expected[1]) + (actual[2]-actual[0])*(actual[3]-actual[1]) - intersection
                overlap = intersection / union
            passed = ((entry['status']=='detected' and overlap>=.5) if expected else entry['status']=='missing') and regions['gateless_raid_panel']['status']=='missing'
            results.append(dict(status=entry['status'], confidence=entry.get('confidence'), xyxy=actual, iou=overlap, passed=passed))
        rows.append(dict(path=row['path'], observedAt=row['observedAt'], baseline=results[0], candidate=results[1]))
    report = dict(purpose=replay['purpose'], total=len(rows),
        positiveFrames=sum(bool(r['boxes']) for r in replay['images']),
        baselinePassed=sum(r['baseline']['passed'] for r in rows),
        candidatePassed=sum(r['candidate']['passed'] for r in rows),
        regressions=sum(r['baseline']['passed'] and not r['candidate']['passed'] for r in rows), rows=rows)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k:v for k,v in report.items() if k!='rows'})


if __name__ == '__main__':
    main()
