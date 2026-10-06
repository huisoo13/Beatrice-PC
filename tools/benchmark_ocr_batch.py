"""Compare OCR batching with sequential calls on the same preserved game crops."""
import argparse
import json
import os
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

from beatrice.character_vision import CharacterVision
from beatrice.dungeon import DungeonOCR
from beatrice.paddle_reader import PaddleKoreanReader
from beatrice.ui_regions import dungeon_location, get_box


class SequentialReader:
    def __init__(self, reader):
        self.reader = reader

    def recognize(self, image):
        return self.reader.recognize(image)


class BoundedBatchReader:
    def __init__(self, reader, size):
        self.reader = reader
        self.size = size

    def recognize_many(self, images):
        import cv2
        outputs = []
        for start in range(0, len(images), self.size):
            chunk = images[start:start + self.size]
            converted = [cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
                         for image in chunk]
            results = list(self.reader.model.predict(converted, batch_size=len(converted)))
            if len(results) != len(chunk):
                raise RuntimeError('OCR batch result mismatch')
            outputs.extend([[(None, value['rec_text'], float(value['rec_score']))] for value in results])
        return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('outputs/ocr-batch/benchmark.json'))
    parser.add_argument('--samples', type=int, default=12)
    parser.add_argument('--all-sizes', action='store_true')
    args = parser.parse_args()
    folders = [Path('outputs/tower-review-1006/holdout'),
               Path(os.environ['LOCALAPPDATA']) / 'BeatricePC/recognition-diagnostics']
    samples = []
    for folder in folders:
        count = 0
        for metadata in sorted(folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                report = json.loads(metadata.read_text(encoding='utf-8'))
                image = metadata.with_suffix('.jpg')
                frame = cv2.imdecode(np.fromfile(image, dtype=np.uint8), cv2.IMREAD_COLOR)
                regions = report.get('character', {}).get('detections', {})
                location = dungeon_location(regions, frame.shape)
                fields = location['regions'] if location['status'] == 'detected' else {}
                if fields:
                    samples.append((str(metadata), 'dungeon', frame, fields))
                else:
                    box = get_box(regions, 'current_name_line') or get_box(regions, 'selected_character_name')
                    if box:
                        samples.append((str(metadata), 'character', frame,
                                        (box, bool(get_box(regions, 'current_name_line')))))
                    else:
                        continue
            except (OSError, ValueError, AttributeError):
                continue
            count += 1
            if count >= max(1, args.samples // len(folders)):
                break
    if not samples:
        raise RuntimeError('비교할 보존 프레임이 없습니다.')
    reader = PaddleKoreanReader()
    sequential = SequentialReader(reader)

    def analyze(adapter, kind, frame, fields):
        if kind == 'dungeon':
            return DungeonOCR(adapter).read_regions(frame, fields)
        box, includes_level = fields
        return CharacterVision(adapter).read_name(frame, box, includes_level)

    def summary(value, kind):
        if kind == 'character':
            return value.get('status'), (value.get('accepted') or {}).get('text')
        return tuple((field, (value.get(field) or {}).get('text'), value['ocr'][field]['status'])
                     for field in value['ocr'])

    adapters = dict(sequential=sequential, queued=reader)
    if args.all_sizes:
        adapters.update(batch1=BoundedBatchReader(reader, 1), batch2=BoundedBatchReader(reader, 2),
                        batch3=BoundedBatchReader(reader, 3), batch6=BoundedBatchReader(reader, 6))
    for adapter in adapters.values():
        _, kind, frame, fields = samples[0]
        analyze(adapter, kind, frame, fields)
    rows = []
    for path, kind, frame, fields in samples:
        measurements = {mode: [] for mode in adapters}
        outputs = {}
        for repeat in range(3):
            order = list(adapters.items())
            if repeat % 2:
                order.reverse()
            for mode, adapter in order:
                started = time.perf_counter()
                result = analyze(adapter, kind, frame, fields)
                measurements[mode].append((time.perf_counter() - started) * 1000)
                outputs[mode] = result
        same = all(summary(outputs['sequential'], kind) == summary(value, kind)
                   for value in outputs.values())
        rows.append(dict(path=path, kind=kind, sameDecision=same,
                         milliseconds={k: statistics.median(v) for k, v in measurements.items()},
                         measurements=measurements, results=outputs))
    medians = {mode: statistics.median(row['milliseconds'][mode] for row in rows)
               for mode in adapters}
    payload = dict(samples=len(rows), sameDecisions=sum(row['sameDecision'] for row in rows),
                   medianMs=medians, rows=rows,
                   scope='same preserved crops, not independent accuracy or end-to-end latency')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in payload.items() if key != 'rows'}))


if __name__ == '__main__':
    main()
