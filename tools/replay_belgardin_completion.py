"""Replay preserved completion frames with real OCR into an isolated memory DB."""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', required=True)
    parser.add_argument('--element-config', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    import cv2
    import numpy as np
    import torch
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon import DungeonOCR, DungeonTracker
    from beatrice.dungeon_observer import DungeonObserver
    from beatrice.completion_overlay import CompletionOverlayDetector
    from beatrice.live import LiveCoordinator
    from beatrice.storage import Store
    torch.set_num_threads(2)
    config = json.loads((ROOT / 'config/dungeon-regions.json').read_text(encoding='utf-8'))
    if args.element_config:
        config['elementConfig'] = str(args.element_config.resolve())
    detector = UIRegionDetector(dict(config, weights=args.weights))
    ocr = DungeonOCR()
    observer = DungeonObserver(ocr)
    tracker = DungeonTracker(max_gap=5)
    completion = CompletionOverlayDetector(ocr.reader, json.loads((ROOT / 'config/completion-overlay.json').read_text(encoding='utf-8')))
    raw = ROOT / 'data/raw/belgardin-panel-1006'
    seed = json.loads((raw / 'event-00002809.json').read_text(encoding='utf-8'))
    store = Store(':memory:')
    live = LiveCoordinator(store)
    live.identity.current = seed['state']['identity']['currentName']
    live.identity.blocked = False
    at = datetime.fromisoformat(seed['observedAt'])
    for i in range(3):
        live.update(at + timedelta(seconds=i), {}, seed['gates'], seed['state']['dungeon'])
    rows = []
    # Consecutive unseen final frames include the completed panel and rewards.
    manifest = json.loads((raw / 'replay.json').read_text(encoding='utf-8'))
    chronological = sorted(manifest['images'], key=lambda row: datetime.fromisoformat(row['observedAt']))
    for row in chronological[-40:]:
        path = ROOT / 'data/annotations' / row['path']
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        at = datetime.fromisoformat(row['observedAt'])
        regions = detector.locate(frame)
        observation, gates = observer.analyze(frame, regions, at.timestamp())
        observation['completionOverlay'] = completion.analyze(frame)
        context = tracker.update(at.timestamp(), observation)
        result = live.update(at, {}, gates, context)
        rows.append(dict(path=row['path'], observedAt=row['observedAt'],
            dungeon=observation, gates=gates, result=result['result']))
    records = store.state_records()
    report = dict(purpose='same_session_real_models_memory_database_replay', rows=rows, records=records)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(dict(frames=len(rows), records=[dict(gateNumber=r['gateNumber'],observedAt=r['observedAt']) for r in records]))
    store.close()
    if sorted(r['gateNumber'] for r in records) != [1, 2]:
        raise SystemExit('Missing completion in replay')


if __name__ == '__main__':
    main()
