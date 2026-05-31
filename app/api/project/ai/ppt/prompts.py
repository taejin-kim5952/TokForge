"""PPT 생성 전용 프롬프트 + AI JSON 응답 파서.

AI는 슬라이드 deck을 JSON 하나로만 출력한다.
gemma 계열은 JSON 모드를 보장하지 않으므로, 파서가 방어적으로
코드펜스/앞뒤 잡설을 제거하고 첫 { ~ 마지막 }를 추출한다.
"""
import json
import re

PPT_SYSTEM_PROMPT = """당신은 프레젠테이션 슬라이드 설계 전문 AI입니다.
사용자의 요청과 참고 자료(프로젝트 개요·문서)를 바탕으로 발표용 슬라이드 구조를 설계하세요.

반드시 아래 JSON 형식 하나만 출력하세요. 인사·설명·코드펜스 금지.

{
  "title": "발표 전체 제목",
  "slides": [
    {"type": "title", "title": "표지 제목", "subtitle": "부제목", "meta": "버전/날짜/라벨"},
    {"type": "section", "title": "섹션 구분 제목", "note": "섹션 한줄 요약(선택)"},
    {"type": "bullets", "title": "슬라이드 제목", "bullets": ["요점1", "요점2", "요점3"]}
  ]
}

규칙:
1. 첫 슬라이드는 반드시 "title" 타입 표지입니다.
2. 본문 슬라이드는 "bullets" 타입이며, 슬라이드당 bullets 3~6개를 권장합니다.
3. 큰 주제 전환에는 "section" 타입을 사용합니다 (선택).
4. 한국어로 작성하고, 전체 8~15장 내외로 구성합니다.
5. 참고 자료에서 도출 가능한 내용만 사용하고, 모르는 사실은 창작하지 않습니다.
6. JSON 외 어떤 텍스트도 출력하지 마세요.
"""

ALLOWED_TYPES = {"title", "section", "bullets"}

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_deck_json(raw: str) -> dict:
    """LLM 출력에서 deck JSON 추출·검증. 실패 시 ValueError."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    if not text.startswith("{"):
        m = _JSON_BLOCK.search(text)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"deck JSON 파싱 실패: {e}")
    return _normalize_deck(data)


def _normalize_deck(data: dict) -> dict:
    """타입/필드 검증 + 정규화. 알 수 없는 타입은 bullets로 폴백."""
    if not isinstance(data, dict):
        raise ValueError("deck 최상위가 객체가 아님")
    title = str(data.get("title") or "발표 자료").strip()
    raw_slides = data.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise ValueError("slides 배열이 비어있음")

    slides: list[dict] = []
    for s in raw_slides:
        if not isinstance(s, dict):
            continue
        stype = str(s.get("type") or "bullets").strip()
        if stype not in ALLOWED_TYPES:
            stype = "bullets"
        slide = {"type": stype, "title": str(s.get("title") or "").strip()}
        if stype == "title":
            slide["subtitle"] = str(s.get("subtitle") or "").strip()
            slide["meta"] = str(s.get("meta") or "").strip()
        elif stype == "section":
            slide["note"] = str(s.get("note") or "").strip()
        elif stype == "bullets":
            bullets = s.get("bullets") or []
            slide["bullets"] = [str(b).strip() for b in bullets if str(b).strip()]
        slides.append(slide)

    if not slides:
        raise ValueError("유효한 slide 없음")
    return {"title": title, "slides": slides}
