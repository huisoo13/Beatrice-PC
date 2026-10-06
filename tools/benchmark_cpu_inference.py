"""Measure CPU settings on one fixed corpus, without game input or record writes."""
import argparse
import json
import os
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/cpu-inference'


def corpus():
    manifest = OUTPUT / 'samples.json'
    if manifest.exists():
        rows = json.loads(manifest.read_text(encoding='utf-8'))
    else:
        source = Path(os.environ['LOCALAPPDATA']) / 'BeatricePC/recognition-diagnostics'
        rows = []
        counts = {}
        for path in sorted(source.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            report = json.loads(path.read_text(encoding='utf-8'))
            regions = report.get('character', {}).get('detections', {})
            from beatrice.ui_regions import dungeon_location, get_box
            fields = dungeon_location(regions, (1440, 3440, 3))['regions']
            name = get_box(regions, 'current_name_line') or get_box(regions, 'selected_character_name')
            kind = 'dungeon' if fields else 'character' if name else 'other'
            if counts.get(kind, 0) >= (4 if kind == 'dungeon' else 3):
                continue
            try:
                contents = path.with_suffix('.jpg').read_bytes()
            except OSError:
                continue
            OUTPUT.mkdir(parents=True, exist_ok=True)
            image = OUTPUT / f'sample-{len(rows):02d}.jpg'
            image.write_bytes(contents)
            rows.append(dict(image=str(image.relative_to(ROOT)), kind=kind, fields=fields,
                             name=name, includesLevel=bool(get_box(regions, 'current_name_line'))))
            counts[kind] = counts.get(kind, 0) + 1
        if not rows:
            raise RuntimeError('No preserved diagnostic frames')
        manifest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return [(row, cv2.imdecode(np.fromfile(ROOT / row['image'], dtype=np.uint8), cv2.IMREAD_COLOR))
            for row in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['yolo', 'ocr', 'pipeline'])
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--mkldnn', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    frames = corpus()
    rows = []
    if args.mode in ('yolo','pipeline'):
        import torch
        from beatrice.ui_regions import UIRegionDetector, load_config
        detector = UIRegionDetector(load_config())
        completion = UIRegionDetector(json.loads((ROOT / 'config/completion-overlay.json').read_text(encoding='utf-8')))
        # Initialize all predictors before setting threads; first CPU setup can reset them.
        dummy = np.zeros((960, 1280, 3), dtype=np.uint8)
        for part in (detector.character_detector, detector.dungeon_detector,
                     detector.dungeon_detector.element_detector, completion):
            part.model.predict(dummy, imgsz=part.config['imageSize'], device='cpu', verbose=False)
            part.cpu_threads=args.threads
        torch.set_num_threads(args.threads)
        effective = torch.get_num_threads()
        if args.mode=='pipeline':
            from beatrice.paddle_reader import PaddleKoreanReader
            from beatrice.character_vision import CharacterVision
            from beatrice.dungeon import DungeonOCR
            from beatrice.dungeon_observer import DungeonObserver
            from beatrice.completion_overlay import CompletionOverlayDetector
            reader=PaddleKoreanReader(cpu_threads=4,enable_mkldnn=args.mkldnn)
            overlay=CompletionOverlayDetector(reader,completion.config,detector=completion)
        for metadata, frame in frames:
            timings = []
            for repeat in range(4):
                started = time.perf_counter()
                regions=detector.locate(frame)
                if args.mode=='pipeline':
                    character=CharacterVision(reader).analyze_detected(frame,regions,seconds=0)
                    blocked=any(regions.get(k,{}).get('status')!='missing' for k in ('game_menu','switch_dialog')) or character.get('switchLoading',False)
                    blocked=blocked or any(character.get(k) for k in ('serverSelection','characterSelection','loginLoading','selectionUncertain'))
                    dungeon,gates=DungeonObserver(DungeonOCR(reader)).analyze(frame,regions,0,blocked=blocked)
                    result=dict(character=character,dungeon=dungeon,gates=gates,
                                completion=overlay.analyze(frame) if not blocked else None)
                else:
                    result = dict(regions=regions, completion=completion.locate(frame))
                elapsed = (time.perf_counter() - started) * 1000
                if repeat:
                    timings.append(elapsed)
            rows.append(dict(sample=metadata['image'], kind=metadata['kind'], result=result,
                             timings=timings, milliseconds=statistics.median(timings)))
    else:
        from beatrice.paddle_reader import PaddleKoreanReader
        from beatrice.dungeon import DungeonOCR
        from beatrice.character_vision import CharacterVision
        reader = PaddleKoreanReader(cpu_threads=args.threads, enable_mkldnn=args.mkldnn)
        effective = args.threads
        for metadata, frame in frames:
            if metadata['kind'] not in ('dungeon','character'):
                continue
            timings = []
            for repeat in range(4):
                started = time.perf_counter()
                result = (DungeonOCR(reader).read_regions(frame, metadata['fields'])
                          if metadata['kind'] == 'dungeon' else
                          CharacterVision(reader).read_name(frame, metadata['name'], metadata['includesLevel']))
                elapsed = (time.perf_counter() - started) * 1000
                if repeat:
                    timings.append(elapsed)
            rows.append(dict(sample=metadata['image'], kind=metadata['kind'], result=result,
                             timings=timings, milliseconds=statistics.median(timings)))
    payload = dict(mode=args.mode, threads=args.threads, effectiveThreads=effective,
                   mkldnn=args.mkldnn, medianMs=statistics.median(r['milliseconds'] for r in rows), rows=rows)
    output = args.output or OUTPUT / f'{args.mode}-{args.threads}-mkldnn-{int(args.mkldnn)}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in payload.items() if key != 'rows'}))


if __name__ == '__main__':
    main()
