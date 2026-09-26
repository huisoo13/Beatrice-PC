"""완료 배너 한 번의 노출을 하나의 대상에 고정합니다. 제목 OCR은 사용하지 않습니다."""
class CompletionBanner:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active=False;self.target=None;self.count=0;self.consumed=False
        self.missing=0;self.last=None;self.scene=None

    def update(self,seconds,visible,eligible,target,scene=None):
        if not visible:
            self.count=0
            self.missing+=1
            if self.missing>=2:self.reset()
            return None
        self.missing=0
        if not self.active:
            self.active=True;self.target=target if eligible else None;self.scene=scene
        elif self.target is None and eligible and scene is not None and scene==self.scene:
            # 같은 현재 헤더의 OCR 확정이 배너보다 늦은 경우만 기다립니다.
            self.target=target
        if not eligible or target!=self.target or self.target is None:
            self.count=0;self.last=seconds
            return None
        if self.last is not None and seconds-self.last>5:self.count=0
        self.last=seconds;self.count+=1
        return self.target if self.count>=2 and not self.consumed else None

    def commit(self):
        self.consumed=True
