"""기준 UI 좌표를 화면 높이 및 사용자가 지정한 UI 배율로 변환합니다."""
def normalize(frame, ui_scale=1.0, centered=False):
    import cv2
    h,w=frame.shape[:2]
    scale=h/1440*ui_scale
    if scale<=0: raise ValueError('UI 배율은 양수여야 합니다.')
    import numpy as np
    tx=1720-w/(2*scale) if centered else 0
    ty=720-h/(2*scale) if centered else 0
    return cv2.warpAffine(frame,np.float32([[1/scale,0,tx],[0,1/scale,ty]]),(3440,1440))
