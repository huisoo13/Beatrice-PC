import argparse
import importlib.metadata
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .rules import inspect_rules


def main():
    parser = argparse.ArgumentParser(description="Beatrice: 환경 확인과 게임 이미지 수집")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="OS, Python, 설치 패키지 진단")
    rules = commands.add_parser("rules", help="미정 기록 규칙 검사 (미정이면 종료 코드 2)")
    rules.add_argument("--config", type=Path, default=Path("config/scene.json"))
    commands.add_parser("clients", help="OBS 캡처 대상 게임 창 목록")
    capture = commands.add_parser("capture", help="내장 OBS로 게임 프레임을 PNG로 한 장 저장")
    capture.add_argument("--pid", type=int, help="게임 창 목록의 프로세스 ID")
    capture.add_argument("--timeout", type=float, default=15.0)
    capture.add_argument("--directory", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    if args.command == "doctor":
        print(f"OS: {platform.platform()} / {platform.machine()}")
        print(f"Python: {platform.python_version()} / {sys.executable}")
        print(f"가상환경: {sys.prefix != sys.base_prefix}")
        print("개발 기준: Python 3.11 (현재 3.9에서도 환경/규칙 검사만 실행 가능)")
        for package in ("opencv-python", "opencv-python-headless", "torch", "ultralytics"):
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = "미설치"
            print(f"{package}: {version}")
        from .obs_capture import runtime_path
        try:
            runtime = runtime_path()
            manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
            print(f"내장 OBS: {manifest.get('version')} / {runtime}")
        except RuntimeError as exc:
            print(f"내장 OBS: {exc}")
        print("위 정보는 설치 메타데이터입니다. 캡처/GPU/탐지 작동 검증이 아닙니다.")
        return 0
    if args.command == "rules":
        issues = inspect_rules(json.loads(args.config.read_text(encoding="utf-8")))
        for issue in issues:
            print(f"- {issue}")
        print("규칙을 구체화해야 합니다." if issues else "필수 항목 입력 완료. 의미와 실행 가능성은 별도 검토합니다.")
        return 2 if issues else 0
    from .game_window import find_clients
    if sys.platform != 'win32':
        raise RuntimeError('OBS 게임 캡처는 Windows에서 실행해주세요.')
    clients = find_clients()
    if args.command == "clients":
        for client in clients:
            print(f"PID {client.pid} / HWND {client.hwnd} / {client.title}")
        return 0
    if not 0 < args.timeout <= 60:
        raise ValueError('timeout은 0초 초과, 60초 이하여야 합니다.')
    targets = [client for client in clients if args.pid is None or client.pid == args.pid]
    if len(targets) != 1:
        raise RuntimeError('게임 창을 하나로 지정해주세요. clients 목록을 확인하고 --pid를 사용하세요.')
    from .obs_capture import ObsCapture
    adapter = ObsCapture(targets[0], args.directory / 'capture-logs')
    reason = 'OBS 새 게임 프레임 대기'
    try:
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            frame, reason = adapter.grab()
            if frame is not None:
                break
            time.sleep(.1)
        else:
            raise RuntimeError(f'캡처 시간 초과: {reason}')
        now = adapter.observed_at or datetime.now(timezone.utc)
        capture_info = dict(adapter.frame_info)
    finally:
        adapter.close()
    destination = args.directory / (now.strftime("%Y%m%dT%H%M%S_%fZ") + ".png")
    import cv2
    ok, encoded = cv2.imencode('.png', frame)
    if not ok:
        raise RuntimeError('PNG 변환에 실패했습니다.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(encoded.tobytes())
    metadata = {"schemaVersion": 1, "capturedAt": now.isoformat(),
                "timestampMeaning": "PC에서 프레임을 받은 시각; 게임 이벤트 시각 아님",
                "source": "embedded_obs", "pid": targets[0].pid, "hwnd": targets[0].hwnd,
                "width": int(frame.shape[1]), "height": int(frame.shape[0]),
                "captureScope": "game", "colorOrder": "BGR", "capture": capture_info}
    with destination.with_suffix(".json").open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    print(f"저장: {destination.resolve()} ({frame.shape[1]} × {frame.shape[0]})")
    print("PNG를 직접 열어 게임 화면·색상·아이콘 선명도를 확인해주세요.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        sys.exit(1)
