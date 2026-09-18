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
    commands.add_parser("monitors", help="Windows 캡처 장치 및 모니터 목록")
    capture = commands.add_parser("capture", help="선택한 모니터 전체 화면을 PNG로 한 장 저장")
    capture.add_argument("--device", type=int, default=0)
    capture.add_argument("--output", type=int, default=0)
    capture.add_argument("--delay", type=float, default=5.0)
    capture.add_argument("--directory", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    if args.command == "doctor":
        print(f"OS: {platform.platform()} / {platform.machine()}")
        print(f"Python: {platform.python_version()} / {sys.executable}")
        print(f"가상환경: {sys.prefix != sys.base_prefix}")
        print("개발 기준: Python 3.11 (현재 3.9에서도 환경/규칙 검사만 실행 가능)")
        for package in ("dxcam", "opencv-python", "opencv-python-headless", "torch", "ultralytics"):
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = "미설치"
            print(f"{package}: {version}")
        print("위 정보는 설치 메타데이터입니다. 캡처/GPU/탐지 작동 검증이 아닙니다.")
        return 0
    if args.command == "rules":
        issues = inspect_rules(json.loads(args.config.read_text(encoding="utf-8")))
        for issue in issues:
            print(f"- {issue}")
        print("규칙을 구체화해야 합니다." if issues else "필수 항목 입력 완료. 의미와 실행 가능성은 별도 검토합니다.")
        return 2 if issues else 0
    from .capture import load_dxcam, capture_one, save_png
    if args.command == "monitors":
        dxcam = load_dxcam()
        print(dxcam.device_info())
        print(dxcam.output_info())
        return 0
    load_dxcam()  # 지원하지 않는 OS에서는 기다리기 전에 종료합니다.
    if not 0 <= args.delay <= 60 or min(args.device, args.output) < 0:
        raise ValueError("delay는 0~60초, device/output은 0 이상의 정수여야 합니다.")
    print(f"{args.delay}초 후 선택 모니터 전체를 캡처합니다. 게임으로 전환해주세요.", flush=True)
    time.sleep(args.delay)
    frame = capture_one(args.device, args.output)
    now = datetime.now(timezone.utc)
    destination = args.directory / (now.strftime("%Y%m%dT%H%M%S_%fZ") + ".png")
    save_png(frame, destination)
    metadata = {"schemaVersion": 1, "capturedAt": now.isoformat(),
                "timestampMeaning": "PC에서 프레임을 받은 시각; 게임 이벤트 시각 아님",
                "source": "dxcam", "device": args.device, "output": args.output,
                "width": int(frame.shape[1]), "height": int(frame.shape[0]),
                "captureScope": "monitor", "colorOrder": "BGR"}
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
