"""PPT 생성 전용 프롬프트 + AI JSON 응답 파서.

AI는 슬라이드 deck을 JSON 하나로만 출력한다.
gemma 계열은 JSON 모드를 보장하지 않으므로, 파서가 방어적으로
코드펜스/앞뒤 잡설을 제거하고 첫 { ~ 마지막 }를 추출한다.

템플릿이 주어지면 그 템플릿의 블록 타입·필드로 시스템 프롬프트와 허용 타입을
파생한다 (build_ppt_system_prompt / parse_deck_json(template=...)).
템플릿이 없으면 기존 고정 프롬프트(title/section/bullets)로 폴백한다.
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


# ───────── 템플릿에서 블록/필드 파생 ─────────
def _plain_field(bind: str) -> str | None:
    """슬라이드 필드 바인딩만 추출 (@계산값·deck.* 제외)."""
    if not bind:
        return None
    if bind.startswith(("@", "deck.")):
        return None
    return bind


def _collect_fields(elements, scalars: set, arrays: set) -> None:
    for el in elements or []:
        kind = el.get("kind")
        if kind == "bound":
            f = _plain_field(el.get("bind", ""))
            if f:
                scalars.add(f)
        elif kind == "repeater":
            f = _plain_field(el.get("bind", ""))
            if f:
                arrays.add(f)
        vif = el.get("visibleIf")
        if vif:
            f = _plain_field(vif)
            if f:
                scalars.add(f)


def derive_block_specs(template: dict) -> list[dict]:
    """각 블록의 type/label + 소비하는 슬라이드 필드(scalar/array)."""
    specs = []
    for b in template.get("blocks", []):
        scalars: set = set()
        arrays: set = set()
        _collect_fields(b.get("elements", []), scalars, arrays)
        specs.append({
            "type": b.get("type"),
            "label": b.get("label", ""),
            "scalars": sorted(scalars),
            "arrays": sorted(arrays),
        })
    return specs


def build_ppt_system_prompt(template: dict | None = None) -> str:
    """템플릿이 있으면 그 블록/필드로 시스템 프롬프트를 구성, 없으면 기본."""
    if not template or not template.get("blocks"):
        return PPT_SYSTEM_PROMPT

    specs = derive_block_specs(template)
    lines = []
    for s in specs:
        if not s["type"]:
            continue
        fields = [f'"type": "{s["type"]}"']
        for f in s["scalars"]:
            fields.append(f'"{f}": "..."')
        for a in s["arrays"]:
            fields.append(f'"{a}": ["...", "..."]')
        label = f'   // {s["label"]}' if s["label"] else ""
        lines.append("    {" + ", ".join(fields) + "}" + label)

    types = ", ".join(f'"{s["type"]}"' for s in specs if s["type"])
    slides_block = ",\n".join(lines)
    return f"""당신은 프레젠테이션 슬라이드 설계 전문 AI입니다.
사용자의 요청과 참고 자료(프로젝트 개요·문서)를 바탕으로 발표용 슬라이드 구조를 설계하세요.

반드시 아래 JSON 형식 하나만 출력하세요. 인사·설명·코드펜스 금지.

{{
  "title": "발표 전체 제목",
  "slides": [
{slides_block}
  ]
}}

규칙:
1. slide 의 "type" 은 반드시 다음 중 하나입니다: {types}.
2. 각 type 은 위 예시에 표시된 필드만 사용합니다. 배열 필드(["..."])는 항목 3~6개 권장.
3. 첫 슬라이드는 표지 성격의 슬라이드로 시작하세요.
4. 한국어로 작성하고, 전체 8~15장 내외로 구성합니다.
5. 참고 자료에서 도출 가능한 내용만 사용하고, 모르는 사실은 창작하지 않습니다.
6. JSON 외 어떤 텍스트도 출력하지 마세요.
"""


# ───────── 파서 ─────────
def parse_deck_json(raw: str, template: dict | None = None) -> dict:
    """LLM 출력에서 deck JSON 추출·검증. 실패 시 ValueError.

    template 이 주어지면 그 블록 타입/필드로 정규화, 없으면 기존 규칙.
    """
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
    return _normalize_deck(data, template)


def _normalize_deck(data: dict, template: dict | None = None) -> dict:
    """타입/필드 검증 + 정규화."""
    if not isinstance(data, dict):
        raise ValueError("deck 최상위가 객체가 아님")
    title = str(data.get("title") or "발표 자료").strip()
    raw_slides = data.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise ValueError("slides 배열이 비어있음")

    if template and template.get("blocks"):
        slides = _normalize_with_template(raw_slides, template)
    else:
        slides = _normalize_default(raw_slides)

    if not slides:
        raise ValueError("유효한 slide 없음")
    return {"title": title, "slides": slides}


def _normalize_with_template(raw_slides: list, template: dict) -> list[dict]:
    specs = {s["type"]: s for s in derive_block_specs(template) if s["type"]}
    if not specs:
        return _normalize_default(raw_slides)
    types = list(specs.keys())
    default_type = "bullets" if "bullets" in specs else types[0]

    slides: list[dict] = []
    for s in raw_slides:
        if not isinstance(s, dict):
            continue
        stype = str(s.get("type") or default_type).strip()
        if stype not in specs:
            stype = default_type
        spec = specs[stype]
        slide = {"type": stype, "title": str(s.get("title") or "").strip()}
        for f in spec["scalars"]:
            if f == "title":
                continue
            slide[f] = str(s.get(f) or "").strip()
        for a in spec["arrays"]:
            arr = s.get(a) or []
            if isinstance(arr, list):
                slide[a] = [str(x).strip() for x in arr if str(x).strip()]
            else:
                slide[a] = []
        slides.append(slide)
    return slides


def _normalize_default(raw_slides: list) -> list[dict]:
    """알 수 없는 타입은 bullets로 폴백 (기존 동작)."""
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
    return slides
