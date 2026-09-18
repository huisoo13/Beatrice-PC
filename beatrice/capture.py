"""Windows 캡처 어댑터. 프레임은 OpenCV와 같은 BGR 배열로 반환합니다."""

import platform
import time


def load_dxcam():
    if platform.system() != "Windows":
        raise RuntimeError("dxcam 캡처는 Windows에서만 실행할 수 있습니다.")
    try:
        import dxcam
    except ImportError as exc:
        raise RuntimeError("requirements-capture.txt를 Windows 가상환경에 설치해주세요.") from exc
    return dxcam


def capture_one(device, output, timeout=3.0):
    dxcam = load_dxcam()
    camera = dxcam.create(device_idx=device, output_idx=output,
                          backend="dxgi", output_color="BGR")
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = camera.grab()
            if frame is not None:
                # 캡처 버퍼 수명과 독립적인 이미지를 반환합니다.
                return frame.copy()
            time.sleep(0.05)
        raise RuntimeError("새 프레임이 없습니다. 화면 모드와 모니터를 확인해주세요.")
    finally:
        camera.release()


def save_png(frame, destination):
    import cv2
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("PNG 변환에 실패했습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # x 모드로 기존 원본을 덮어쓰지 않으며 한글 경로도 지원합니다.
    with destination.open("xb") as stream:
        stream.write(encoded.tobytes())
