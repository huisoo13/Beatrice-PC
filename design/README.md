# 디자인 자료 관리

현재 앱 UI의 소스와 실행 에셋은 `ui/Beatrice.App/`에서 관리합니다.
팔레트·폰트·간격은 `ui/Beatrice.App/Assets/tokens.json`, 아이콘은 같은 폴더의 SVG가 원본입니다.
현재 주간 로그 디자인은 `docs/61-weekly-record-ui.md`, 데스크톱 구현은 `docs/58-winui-desktop.md`, UI 작업 지침은 `design/ui-workflow.md`에 보존합니다.

이전 검토용 `ui-review/`, QML 시안 `ui-v2/`, 독립 WinUI 시안 `winui-preview/`와 대화용 프리뷰는 정리를 마쳐 삭제했습니다.
실제 앱의 검토용 PNG, 빌드 산출물, 진단 로그도 제외합니다. 실행에 필요한 에셋은 제외하지 않습니다.

`ui-ux-pro-max` 설치본과 로컬 검토 도구는 Git에서 제외합니다. UI 작업 환경에는
https://github.com/nextlevelbuilder/ui-ux-pro-max-skill 의 스킬을
`.agents/skills/ui-ux-pro-max/`에 별도로 설치합니다.

Pretendard 1.3.9의 Regular·SemiBold와 OFL 라이선스를 실행 에셋에 포함합니다.
주간 로그의 폰트·색상·간격은 `tokens.json`의 `font`, `colors`, `layout.records`에 기록합니다.
이전 카드 전용 토큰과 미사용 Bold 글꼴은 제거했습니다. 보상표의 난이도 캡슐 에셋은 유지합니다.

캐릭터별 주간 영수증은 `docs/62-weekly-character-summary.md`에 보존하며, 승인된 표시 토큰은 `tokens.json`의 `layout.weeklySummary`에서 관리합니다.
