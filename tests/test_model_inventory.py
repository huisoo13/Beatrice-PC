"""활성 모델/클래스 변경 시 README 빠른 확인 표도 함께 변경해야 합니다."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class ModelInventoryTests(unittest.TestCase):
    def test_readme_lists_every_active_model_and_class(self):
        readme=(ROOT/'README.md').read_text(encoding='utf-8')
        block=readme.split('<!-- MODEL-INVENTORY:START -->')[1].split('<!-- MODEL-INVENTORY:END -->')[0]
        total=0
        for config in ('character-regions','dungeon-regions','dungeon-elements','completion-overlay'):
            doc=json.loads((ROOT/f'config/{config}.json').read_text(encoding='utf-8'))
            listed=[];active=False
            for line in block.splitlines():
                if not line.startswith('| '):continue
                cells=[c.strip() for c in line.split('|')]
                if cells[1]!='↳':active=cells[1]==f"`{Path(doc['weights']).name}`"
                if active:listed.append(cells[2].strip('`'))
            self.assertEqual(listed,doc['classes'],config)
            total+=len(doc['classes'])
        self.assertIn(f'4개 / {total}클래스',block)
