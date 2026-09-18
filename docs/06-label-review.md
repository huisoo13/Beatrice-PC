# 첫 라벨 검수 — 2026-09-15

`outputs/label-review/review-sheet.png`에 A~D 이미지 4장, 아이콘 박스 10개를 표시했다. 각 개별 이미지는 같은 폴더의 A.png~D.png다. 모델이 생성한 결과가 아니라 원본을 보고 지정한 수작업 초안이다. 표시된 개수 역시 지정한 박스를 집계한 값이며 탐지 성능이 아니다.

- A: 사용자 확인을 받은 기존 스크린샷의 상태. 박스 범위는 이번에 검수한다.
- B: 영상 약 7.25초, 완료 직전.
- C: 영상 약 7.50초, 완료 직후.
- D: 영상 약 25.13초, 어두워진 상태.

박스는 본체와 초록 체크를 포함하고 아이콘 사이 연결선과 버튼을 제외한다. 흐릿한 발광 번짐 전체를 감싸지는 않는다. 검수 화면에서는 원본 왼쪽 위 일부를 3배 확대하고 박스를 겹쳐 표시했으며 학습 원본에 선이나 글자를 합성하지 않았다. 원본 픽셀 좌표는 `data/annotations/review-v1.json`에 저장되어 있다. 관문 번호는 사람이 검수하기 위한 메타데이터이며 YOLO 클래스가 아니다.

사용자는 빠진 아이콘, 잘못된 상태, 박스가 잘라낸 본체/체크가 있는지 확인한다. 예를 들어 “C의 1관문 박스를 왼쪽으로 조금 넓혀줘”처럼 이미지 문자와 관문 번호로 수정 사항을 전달하면 된다. 수정 없이 맞으면 전체가 맞다고 알려주면 된다.

현재 reviewStatus는 pending이다. 검수 이후 확정 라벨로 변환한다. 아직 YOLO txt 내보내기나 모델 학습은 하지 않았다. 영상의 세 이미지는 모두 같은 sessionId를 유지하여 향후 train/val/test 사이에 나뉘지 않도록 한다.

## 재생성

렌더러 `tools/render_label_review.py`는 Pillow와 한국어 글꼴이 필요하다. 현재는 프로젝트 가상환경과 별개인 Codex 번들 Python의 Pillow로 실행했다.

```bash
cd /Users/huisoo/Project/Beatrice-PC
/Users/huisoo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 tools/render_label_review.py --font /System/Library/Fonts/AppleSDGothicNeo.ttc
```

다른 환경에서는 Pillow가 설치된 Python으로 실행하고 `--font`에 한국어 지원 TTF/TTC 경로를 지정한다. 실행 결과 4장·10박스를 확인했고, 출력 시트를 직접 열어 한국어 표시와 박스 위치를 검토했다. 원본 크기, 좌표 범위, 상태 목록과 관문 번호 중복을 검사했으며 원본 SHA256도 JSON에 기록했다. 학습 정확도 검증은 아니다.
