"""이미지 또는 저장된 영상 패널에서 던전 이름·난이도를 읽습니다."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.dungeon import DungeonOCR,DungeonTracker,CONFIG


def main():
    import cv2
    p=argparse.ArgumentParser(description='이미지/영상 관측의 던전 이름·난이도 OCR')
    p.add_argument('source',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();ocr=DungeonOCR()
    if args.source.suffix.lower()=='.json':
        data=json.loads(args.source.read_text());tracker=DungeonTracker()
        for i,row in enumerate(data['observations']):
            path=args.source.parent/'frames'/f"{row['frameIndex']:06d}.png"
            panel=cv2.imread(str(path))
            if panel is None:raise ValueError(f'원본 패널 없음: {path}')
            observation=ocr.analyze_panel(panel)
            row['dungeonObservation']=observation
            row['dungeonContext']=tracker.update(row['videoSeconds'],observation)
            if i%25==0:print(f'{i+1}개 관측 완료',flush=True)
        data['meta']['dungeonOCR']=dict(config=CONFIG,sourceObservations=str(args.source.resolve()),source='original_top_left_panels',independentEvaluation=False)
    else:
        frame=cv2.imread(str(args.source))
        if frame is None:raise ValueError('이미지 읽기 실패')
        data=dict(source=str(args.source.resolve()),observation=ocr.analyze_panel(frame[:240,:800]),
                  purpose='ocr_only_without_dungeon_hud_validation',eventConfirmed=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(args.output)

if __name__=='__main__':main()
