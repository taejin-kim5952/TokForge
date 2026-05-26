"""프로젝트 개요 정리(organize) 전용 프롬프트 + 섹션 파서.

대화 전체를 받아 9개 폼 필드로 구조화된 마크다운으로 만든다.
"""
import re

# 폼 필드 9개 → 사용자 표시 섹션 헤더
SECTION_MAP: dict[str, str] = {
    "프로젝트 목적":   "purpose",
    "배경 / 문제 정의": "background",
    "포함 범위":       "scope",
    "제외 범위":       "out_of_scope",
    "핵심 기능":       "key_features",
    "이해관계자":      "stakeholders",
    "기술 스택":       "tech_stack",
    "주요 일정":       "schedule",
    "리스크 / 메모":   "risks",
}

# 역방향 lookup
FIELD_TO_HEADING: dict[str, str] = {v: k for k, v in SECTION_MAP.items()}


OVERVIEW_ORGANIZER_PROMPT = """당신은 프로젝트 개요 정리 전문 AI입니다.
주어진 사용자-AI 대화를 읽고, 아래 9개 섹션의 마크다운 문서로 정리하세요.

규칙:
1. 반드시 아래 9개 섹션을 모두 포함하고, 정확히 이 순서·이 헤더 문구를 사용합니다:
   ## 프로젝트 목적
   ## 배경 / 문제 정의
   ## 포함 범위
   ## 제외 범위
   ## 핵심 기능
   ## 이해관계자
   ## 기술 스택
   ## 주요 일정
   ## 리스크 / 메모
2. 각 섹션은 대화에서 직접 도출된 내용만 사용합니다. 추측·창작 금지.
3. 대화에 정보가 없는 섹션은 "(추가 논의 필요)" 한 줄만 작성합니다.
4. "핵심 기능"은 "- " 불릿 리스트로, 나머지는 1~3문장 평문으로 작성합니다.
5. 다른 어떤 문장도 추가하지 않습니다 (인사·메타설명·코드블록 금지).
"""


def parse_overview_sections(markdown: str) -> dict[str, str]:
    """마크다운에서 `## 섹션명` 으로 분할하여 9개 필드 dict 반환.

    누락된 섹션은 "(추가 논의 필요)" 로 채움.
    매칭 안 되는 섹션은 무시.
    """
    sections: dict[str, str] = {field: "(추가 논의 필요)" for field in SECTION_MAP.values()}

    # `## 헤더` 단위로 분할
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    parts: list[tuple[str, int]] = [
        (m.group(1).strip(), m.end()) for m in pattern.finditer(markdown)
    ]
    if not parts:
        return sections

    for i, (heading, body_start) in enumerate(parts):
        body_end = parts[i + 1][1] - len(f"## {parts[i + 1][0]}") if i + 1 < len(parts) else len(markdown)
        # 다음 헤더 직전까지가 본문 (안전하게 다시 정규식 split)
        body = markdown[body_start:body_end]
        # 다음 ## 가 본문에 끼어있으면 잘라냄
        next_header_match = re.search(r"^##\s+", body, re.MULTILINE)
        if next_header_match:
            body = body[: next_header_match.start()]
        body = body.strip()

        field = SECTION_MAP.get(heading)
        if field and body:
            sections[field] = body

    return sections
