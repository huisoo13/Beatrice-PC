"""최초 접속 관측. 모든 영역은 YOLO 결과이며 배경/고정 위치를 사용하지 않습니다."""
from .ui_regions import get_box, contained

CLASSES=['server_table','selected_character_card','selected_character_name','game_start_button','loading_progress']


def observe_login(frame, regions, vision):
    card=get_box(regions,'selected_character_card')
    name=get_box(regions,'selected_character_name')
    start=get_box(regions,'game_start_button')
    # A blue selected card with its own name is sufficient, including under
    # the password overlay. The start button is supporting evidence only.
    name_inside=bool(card and name and contained(name,card))
    in_game_menu=get_box(regions,'game_menu') or get_box(regions,'switch_dialog')
    selection=bool(not in_game_menu and card and (name_inside or start))
    reading=None
    if selection and name_inside:
        reading=vision.read_name(frame,name)
    return dict(serverSelection=bool(get_box(regions,'server_table')),
                characterSelection=selection,
                selectedCard=card if selection else None,
                selectedName=(reading or {}).get('accepted'),
                loginLoading=bool(get_box(regions,'loading_progress')),
                loginLoadingAbsent=all(regions.get(k,{}).get('status')=='missing' for k in CLASSES),
                selectionUncertain=any(regions.get(k,{}).get('status')=='ambiguous' for k in CLASSES),
                selectionOCR=reading)
