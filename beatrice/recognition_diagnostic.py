"""최근 게임 프레임과 같은 프레임의 인식/상태 결과를 제한된 슬롯에 보관합니다."""
import json
import time
import uuid
from pathlib import Path


class RecognitionDiagnostic:
    def __init__(self, directory, capacity=180, interval=1.0):
        if capacity < 1 or interval <= 0:
            raise ValueError('진단 보관 개수와 간격은 양수여야 합니다.')
        self.directory=Path(directory)
        self.capacity=capacity
        self.interval=interval
        self.session=uuid.uuid4().hex
        self.sequence=0
        self.last_saved=None
        self.previous=None

    def record(self, frame, report, now=None):
        import cv2
        now=time.monotonic() if now is None else now
        character=report.get('character',{})
        identity=report.get('state',{}).get('identity',{})
        signature=(character.get('switchDialog'),character.get('switchLoading'),
                   identity.get('currentName'),identity.get('status'))
        changed=signature!=self.previous
        if not changed and self.last_saved is not None and now-self.last_saved<self.interval:
            return False
        self.directory.mkdir(parents=True,exist_ok=True)
        slot=f'frame-{self.sequence % self.capacity:03d}'
        # 저장 실패 시 다른 프레임의 결과와 섞이지 않도록 이전 JSON부터 무효화합니다.
        metadata=self.directory/(slot+'.json')
        metadata.unlink(missing_ok=True)
        ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,92])
        if not ok:
            raise OSError('게임 진단 이미지 인코딩에 실패했습니다.')
        encoded.tofile(self.directory/(slot+'.jpg'))
        payload=dict(report,sessionId=self.session,sequence=self.sequence,
                     frameFile=slot+'.jpg',frameSize=list(frame.shape[:2]))
        metadata.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        self.last_saved=now
        self.previous=signature
        self.sequence+=1
        return True
