"""Preserve October 6 evidence and add reviewed panel labels to the old corpus."""
import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = Path(os.environ['LOCALAPPDATA']) / 'BeatricePC'
    session = source / 'completion-diagnostics/20261006T041151Z-ecb705c3'
    raw = ROOT / 'data/raw/belgardin-panel-1006'
    raw.mkdir(parents=True, exist_ok=False)
    document = json.loads((ROOT / 'data/annotations/dungeon-parents-clean-0929.json').read_text(encoding='utf-8'))
    # These historical "negative" frames visibly contain Serka's gated HUD.
    corrected = {'../raw/ui-bootstrap/negative-260910_213142.png',
                 '../raw/ui-bootstrap/negative-260910_213151.png'}
    for row in document['images']:
        if row['path'] in corrected:
            row['boxes'] = [{'class': 'dungeon_panel', 'xyxy': [0, 36, 360, 250]}]
            row['annotationCorrection'] = 'Visible Serka hard-mode gated panel; revival counter excluded.'
    evidence = []
    # One play session: held-out frames measure temporal replay, not independent accuracy.
    train_sequences = [2639, 2656, 2679, 2682, 2691, 2695, 2697, 2809, 2810, 2862]
    for number in train_sequences:
        name = f'event-{number:08d}'
        shutil.copy2(session / (name + '.jpg'), raw / (name + '.jpg'))
        shutil.copy2(session / (name + '.json'), raw / (name + '.json'))
        document['images'].append(dict(path='../raw/belgardin-panel-1006/' + name + '.jpg',
            split='train', sessionId='live-20261006-belgardin',
            synthetic=False, boxes=[{'class': 'dungeon_panel', 'xyxy': [0, 36, 360, 250]}]))
    for metadata in sorted((source / 'recognition-diagnostics').glob('frame-*.json')):
        report = json.loads(metadata.read_text(encoding='utf-8'))
        image = metadata.with_suffix('.jpg')
        if '2026-10-06' not in report.get('observedAt', ''):
            continue
        name = f"replay-{report['sequence']:08d}"
        shutil.copy2(image, raw / (name + '.jpg'))
        shutil.copy2(metadata, raw / (name + '.json'))
        evidence.append(dict(path='../raw/belgardin-panel-1006/' + name + '.jpg',
            observedAt=report['observedAt'], boxes=[{'class': 'dungeon_panel', 'xyxy': [0, 36, 360, 250]}]))
        if 2023 <= report['sequence'] <= 2026:
            evidence[-1]['boxes'] = []  # Reviewed cutscene frames have no HUD.
    # Add a few completion frames; reserve all other rolling frames for replay.
    for row in evidence[::30]:
        document['images'].append(dict(row, split='train', sessionId='live-20261006-belgardin', synthetic=False))
    for row in document['images']:
        path = ROOT / 'data/annotations' / row['path']
        row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    document['annotationMethod'] = 'Existing reviewed labels plus manually reviewed live panel [0,36,360,250]; revival counter excluded.'
    (ROOT / 'data/annotations/dungeon-parents-belgardin-1006.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    training_paths = {row['path'] for row in document['images']}
    replay = dict(purpose='same_session_temporal_holdout_not_independent_accuracy',
                  images=[row for row in evidence if row['path'] not in training_paths])
    (raw / 'replay.json').write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding='utf-8')
    print(dict(training=len(document['images']), heldout=len(replay['images']), evidence=str(raw)))


if __name__ == '__main__':
    main()
