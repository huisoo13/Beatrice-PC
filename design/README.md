# 디자인 자료 관리

현재 앱 UI의 소스와 실행 에셋은 `ui/Beatrice.App/`에서 관리합니다.
팔레트·폰트·간격은 `ui/Beatrice.App/Assets/tokens.json`, 아이콘은 같은 폴더의 SVG가 원본입니다.
구현과 검증 결과는 `docs/58-winui-desktop.md`, UI 작업 지침은 `design/ui-workflow.md`에 보존합니다.

이전 검토용 `ui-review/`, QML 시안 `ui-v2/`, 독립 WinUI 시안 `winui-preview/`와 대화용 프리뷰는 정리를 마쳐 삭제했습니다.
실제 앱의 검토용 PNG, 빌드 산출물, 진단 로그도 제외합니다. 실행에 필요한 에셋은 제외하지 않습니다.

`ui-ux-pro-max` 설치본과 로컬 검토 도구는 Git에서 제외합니다. UI 작업 환경에는
https://github.com/nextlevelbuilder/ui-ux-pro-max-skill 의 스킬을
`.agents/skills/ui-ux-pro-max/`에 별도로 설치합니다.
