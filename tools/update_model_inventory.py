"""활성 설정으로 README 모델 표를 갱신합니다. 모델 변경 작업에서 실행하세요."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DESCRIPTIONS={
    'game_menu':'게임 메뉴 패널','current_name_line':'현재 캐릭터 이름 줄',
    'switch_dialog':'캐릭터 변경 확인창','target_name_line':'변경 대상 이름',
    'loading_indicator':'오른쪽 아래 회전 표시 — 로딩 전 안내',
    'server_table':'서버 선택 표의 프레임','selected_character_card':'파란 선택 표시가 있는 캐릭터 카드',
    'selected_character_name':'선택된 카드의 이름','game_start_button':'게임시작 버튼 (선택 화면 보조 신호)',
    'loading_progress':'실제 로딩 진행 막대의 이동하는 발광 표식',
    'dungeon_panel':'관문 있는 레이드 패널','gateless_raid_panel':'관문 없는 레이드 패널',
    'gate_panel':'전체 관문 아이콘 영역','dungeon_name':'던전 이름','difficulty':'난이도',
    'gate_in_progress':'진행 중 관문 아이콘','gate_completed':'완료 관문 아이콘',
    'gate_not_started':'진행 전 관문 아이콘','gateless_title':'관문 없는 레이드 제목',
    'completion_overlay':'중앙 완료 연출','completion_text':'N관문 돌파 / 던전 클리어 문구 영역',
    'reward_panel':'관문 보상표 전체','reward_gate_title':'보상표의 N관문 돌파 제목',
    'gold_reward_present':'골드 행이 있는 통화 보상 영역','gold_reward_absent':'골드 행이 없는 통화 보상 영역'}

def inventory():
    configs=[json.loads((ROOT/f'config/{name}.json').read_text(encoding='utf-8')) for name in
             ('character-regions','dungeon-regions','dungeon-elements','completion-overlay','gold-reward-panel','gold-reward')]
    lines=['<!-- MODEL-INVENTORY:START -->','## 현재 모델·클래스 빠른 확인','',
           '모델·클래스 변경 시 설정과 이 표를 함께 갱신합니다. `python tools/update_model_inventory.py`로 재생성하며 테스트로 일치 여부를 검사합니다.',
           '과거 작업 일지보다 이 활성 모델 표를 우선합니다.','',
           f"현재 YOLO **{len(configs)}개 / {sum(len(c['classes']) for c in configs)}클래스** + 공용 PaddleOCR입니다.",'',
           '| 활성 모델 | 클래스 | 탐지 대상 |','|---|---|---|']
    for config in configs:
        for i,name in enumerate(config['classes']):
            model=f"`{Path(config['weights']).name}`" if i==0 else '↳'
            description=DESCRIPTIONS[name]
            if config.get('parentConfig') and name=='reward_panel':description+=' (요소 모델에서는 미사용)'
            lines.append(f'| {model} | `{name}` | {description} |')
    lines+=['','PaddleOCR은 탐지된 글자 영역을 읽는 공용 한국어 인식기입니다. EasyOCR은 사용하지 않습니다.',
            '고정 화면 좌표나 패널 비율로 OCR 영역을 지정하지 않습니다. 모델 파일은 로컬 관리하며 Git에 포함하지 않습니다.',
            '<!-- MODEL-INVENTORY:END -->']
    return '\n'.join(lines)

def main():
    path=ROOT/'README.md';text=path.read_text(encoding='utf-8')
    a=text.index('<!-- MODEL-INVENTORY:START -->');b=text.index('<!-- MODEL-INVENTORY:END -->')+len('<!-- MODEL-INVENTORY:END -->')
    path.write_text(text[:a]+inventory()+text[b:],encoding='utf-8')
if __name__=='__main__':main()
