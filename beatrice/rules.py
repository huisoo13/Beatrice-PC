"""미정(null)과 명시적인 없음(false 또는 빈 목록)을 구분합니다."""


def inspect_rules(data):
    issues = []
    if not isinstance(data, dict):
        return ["설정 최상위는 JSON 객체여야 합니다."]
    if type(data.get("schemaVersion")) is not int or data["schemaVersion"] != 1:
        issues.append("schemaVersion: 현재 지원 버전은 1입니다.")
    for key in ("game", "scene", "confirmationRule", "eventIdentityRule",
                "reopenPolicy", "uncertainPolicy"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{key}: 비어 있지 않은 설명이 필요합니다.")
    states = data.get("iconStates")
    if (not isinstance(states, list) or not states
            or any(not isinstance(s, str) or not s.strip() for s in states)):
        issues.append("iconStates: 실제 상태 이름 목록이 필요합니다.")
    elif len(set(s.strip() for s in states)) != len(states):
        issues.append("iconStates: 상태 이름이 중복됩니다.")
    for key in ("positionMeaning", "requiresHistory"):
        if type(data.get(key)) is not bool:
            issues.append(f"{key}: true 또는 false 결정이 필요합니다.")
    fields = data.get("ocrFields")
    if not isinstance(fields, list) or any(
            not isinstance(v, str) or not v.strip() for v in fields):
        issues.append("ocrFields: 필드 이름 목록이 필요합니다. OCR 불필요 시 []입니다.")
    profile = data.get("captureProfile")
    if not isinstance(profile, dict):
        return issues + ["captureProfile: 객체가 필요합니다."]
    for key in ("width", "height"):
        value = profile.get(key)
        if type(value) is not int or value <= 0:
            issues.append(f"captureProfile.{key}: 양의 정수 픽셀이 필요합니다.")
    for key in ("uiScale", "displayScale", "screenMode"):
        value = profile.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"captureProfile.{key}: 게임/Windows 설정값을 문자열로 적어주세요.")
    return issues
