"""빌트인 PPT 템플릿 프리셋 (editorial / minimal / modern).

`editorial` 은 기존 builder.py 의 하드코딩 레이아웃을 데이터(JSON)로 1:1 인코딩한
것으로, 인터프리터 리팩터의 **회귀 기준점**이다. 활성 템플릿이 없을 때의
DEFAULT_TEMPLATE 로도 쓰여 "템플릿 0개여도 기존과 동일 출력"을 보장한다.

────────────────────────────────────────────────────────────────────────
인터프리터(builder.py)가 지켜야 할 바인딩/트랜스폼 계약:

  bind 해석 우선순위:
    "deck.title"      → deck["title"]
    "@pageNo"         → 현재 슬라이드 페이지 번호 (1-based)
    "@total"          → 전체 슬라이드 수
    "@sectionNo"      → 현재 섹션 번호 (1-based, section 블록마다 증가)
    "@sectionTitle"   → 직전 section 블록의 title
    "@item"           → repeater 항목 값 (문자열) / "@item.<field>" → 객체 필드
    "@index"          → repeater 항목 인덱스 (0-based)
    "@itemNo"         → repeater 항목 번호 (1-based)
    그 외             → slide.get(bind)

  transform: upper / lower / trim / roman / pad2
    - roman  : 정수 → "II." (기존 _roman 과 동일, 마침표 포함)
    - pad2   : "%02d" (예: 3 → "03")

  visibleIf: 해당 슬라이드 필드가 비어있으면 그 요소는 렌더하지 않음.
  fallback : bound 값이 비어있을 때 대체 문자열.
  repeater(render="paragraphs"): 단일 textbox, 항목당 1문단, item.elements 는
    kind="run" 들을 한 문단의 run 으로 이어 붙임. paraStyle 이 문단 간격 제어.
  repeater(render="boxes"): 항목당 박스 1개. item.geom = 한 칸 크기,
    item.elements 의 geom 은 칸 기준 상대 좌표. 배치는 direction/columns/stride/spacing.
────────────────────────────────────────────────────────────────────────
"""

# 슬라이드 치수 (기존 builder.py 와 동일)
_SW = 13.333
_SH = 7.5
_MG = 0.85
_RULE_W = round(_SW - _MG * 2, 3)        # 11.633
_META_X = round(_SW - _MG - 6, 3)        # 6.483
_FOOT_R_X = round(_SW - _MG - 4, 3)      # 8.483
_SEC_TITLE_X = 6.4
_SEC_TITLE_W = round(_SW - _SEC_TITLE_X - _MG, 3)  # 6.083


# ───────── dict 빌더 헬퍼 ─────────
def _style(font="body", size=18, color="ink", **kw):
    s = {"font": font, "size": size, "color": color}
    s.update(kw)
    return s


def _geom(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def _text(text, geom, style, transform=None, **kw):
    d = {"kind": "text", "geom": geom, "text": text, "style": style}
    if transform:
        d["transform"] = transform
    d.update(kw)
    return d


def _bound(bind, geom, style, transform=None, fallback=None, visible_if=None, **kw):
    d = {"kind": "bound", "geom": geom, "bind": bind, "style": style}
    if transform:
        d["transform"] = transform
    if fallback is not None:
        d["fallback"] = fallback
    if visible_if is not None:
        d["visibleIf"] = visible_if
    d.update(kw)
    return d


def _line(x, y, w, color, thickness_pt):
    return {"kind": "line", "geom": _geom(x, y, w, 0), "color": color, "thicknessPt": thickness_pt}


def _rect(geom, fill):
    return {"kind": "rect", "geom": geom, "fill": fill}


def _pageno(fmt, geom, style):
    return {"kind": "pageNumber", "geom": geom, "format": fmt, "style": style}


def _run(style, *, text=None, bind=None, transform=None):
    d = {"kind": "run", "style": style}
    if text is not None:
        d["text"] = text
    if bind is not None:
        d["bind"] = bind
    if transform:
        d["transform"] = transform
    return d


def _footer_elements():
    """본문/간지 공통 푸터 — 룰선 + 좌(덱 제목) + 우(페이지)."""
    y = round(_SH - 0.55, 3)        # 6.95
    ty = round(y + 0.08, 3)         # 7.03
    return [
        _line(_MG, y, _RULE_W, "rule", 0.5),
        _bound("deck.title", _geom(_MG, ty, 8, 0.35), _style("mono", 9, "mute")),
        _pageno(
            "{page:02d} / {total:02d}",
            _geom(_FOOT_R_X, ty, 4, 0.35),
            _style("mono", 9, "inkSoft", align="right"),
        ),
    ]


# ───────── editorial (= 기존 builder.py) ─────────
def _editorial():
    theme = {
        "colors": {
            "ink": "#0F172A",
            "inkSoft": "#333D52",
            "mute": "#8A91A3",
            "rule": "#D9D7CE",
            "paper": "#FAFAF7",
            "panel": "#F1EEE6",
            "accent": "#C2410C",
        },
        "fonts": {"head": "Pretendard", "body": "Pretendard", "mono": "Consolas"},
    }

    title_block = {
        "type": "title",
        "label": "Title",
        "bg": "panel",
        "elements": [
            _bound("deck.title", _geom(_MG, 0.7, 6, 0.4),
                   _style("mono", 10, "inkSoft", bold=True), transform=["upper"]),
            _bound("meta", _geom(_META_X, 0.7, 6, 0.4),
                   _style("mono", 10, "inkSoft", align="right"), visible_if="meta"),
            _line(_MG, 1.15, _RULE_W, "rule", 0.5),
            _bound("title", _geom(_MG, 3.5, _RULE_W, 1.4),
                   _style("body", 64, "ink", bold=True, lineSpacing=1.05),
                   fallback=""),
            _bound("subtitle", _geom(_MG, 5.0, _RULE_W, 1.2),
                   _style("body", 20, "inkSoft", lineSpacing=1.35), visible_if="subtitle"),
            _line(_MG, 6.65, 1.4, "accent", 1.5),
        ],
    }

    section_block = {
        "type": "section",
        "label": "Section",
        "bg": "panel",
        "elements": [
            _text("SECTION", _geom(_MG, 0.7, 6, 0.4), _style("mono", 10, "accent", bold=True)),
            _line(_MG, 1.15, _RULE_W, "rule", 0.5),
            _bound("@sectionNo", _geom(_MG, 2.2, 6.5, 3.5),
                   _style("head", 160, "ink", bold=True, anchor="top", lineSpacing=0.95),
                   transform=["roman"]),
            _bound("title", _geom(_SEC_TITLE_X, 3.2, _SEC_TITLE_W, 1.4),
                   _style("body", 34, "ink", bold=True, anchor="top", lineSpacing=1.15)),
            _bound("note", _geom(_SEC_TITLE_X, 4.7, _SEC_TITLE_W, 1.0),
                   _style("body", 15, "inkSoft", lineSpacing=1.5), visible_if="note"),
            *_footer_elements(),
        ],
    }

    bullets_block = {
        "type": "bullets",
        "label": "Bullets",
        "bg": "paper",
        "elements": [
            _bound("@sectionTitle", _geom(_MG, 0.7, 8, 0.4),
                   _style("mono", 10, "accent", bold=True),
                   transform=["upper"], fallback="OVERVIEW"),
            _bound("deck.title", _geom(_FOOT_R_X, 0.7, 4, 0.4),
                   _style("mono", 10, "inkSoft", align="right")),
            _line(_MG, 1.15, _RULE_W, "rule", 0.5),
            _bound("title", _geom(_MG, 1.5, _RULE_W, 1.0),
                   _style("body", 32, "ink", bold=True, lineSpacing=1.15)),
            _bound("subtitle", _geom(_MG, 2.5, _RULE_W, 0.6),
                   _style("body", 15, "inkSoft", lineSpacing=1.4), visible_if="subtitle"),
            {
                "kind": "repeater",
                "bind": "bullets",
                "geom": _geom(_MG, 3.2, _RULE_W, 3.4),
                "direction": "vertical",
                "stride": 0.0,
                "render": "paragraphs",
                "item": {
                    "paraStyle": {"spaceAfter": 14, "lineSpacing": 1.5, "align": "left"},
                    "elements": [
                        _run(_style("mono", 11, "mute", bold=True), bind="@itemNo", transform=["pad2"]),
                        _run(_style("mono", 11, "mute", bold=True), text="   "),
                        _run(_style("body", 18, "ink"), bind="@item"),
                    ],
                },
            },
            *_footer_elements(),
        ],
    }

    return {
        "schema_version": 1,
        "slide": {"w": _SW, "h": _SH, "margin": _MG},
        "theme": theme,
        "blocks": [title_block, section_block, bullets_block],
    }


# ───────── minimal ─────────
def _minimal():
    theme = {
        "colors": {
            "ink": "#111111",
            "inkSoft": "#555555",
            "mute": "#999999",
            "rule": "#E5E5E5",
            "paper": "#FFFFFF",
            "panel": "#FAFAFA",
            "accent": "#111111",
        },
        "fonts": {"head": "Pretendard", "body": "Pretendard", "mono": "Consolas"},
    }
    title_block = {
        "type": "title", "label": "Title", "bg": "paper",
        "elements": [
            _bound("deck.title", _geom(_MG, 0.8, 8, 0.4),
                   _style("mono", 10, "mute"), transform=["upper"]),
            _bound("title", _geom(_MG, 2.8, _RULE_W, 1.8),
                   _style("body", 60, "ink", bold=True, lineSpacing=1.05), fallback=""),
            _bound("subtitle", _geom(_MG, 4.7, _RULE_W, 1.0),
                   _style("body", 18, "inkSoft", lineSpacing=1.4), visible_if="subtitle"),
        ],
    }
    section_block = {
        "type": "section", "label": "Section", "bg": "paper",
        "elements": [
            _bound("@sectionNo", _geom(_MG, 2.2, 2, 1.0),
                   _style("mono", 18, "mute"), transform=["pad2"]),
            _bound("title", _geom(_MG, 3.0, _RULE_W, 1.6),
                   _style("body", 44, "ink", bold=True, lineSpacing=1.1)),
            _bound("note", _geom(_MG, 4.6, _RULE_W, 1.0),
                   _style("body", 16, "inkSoft", lineSpacing=1.5), visible_if="note"),
            *_footer_elements(),
        ],
    }
    bullets_block = {
        "type": "bullets", "label": "Bullets", "bg": "paper",
        "elements": [
            _bound("title", _geom(_MG, 0.9, _RULE_W, 1.0),
                   _style("body", 30, "ink", bold=True, lineSpacing=1.15)),
            _bound("subtitle", _geom(_MG, 1.9, _RULE_W, 0.6),
                   _style("body", 15, "inkSoft"), visible_if="subtitle"),
            {
                "kind": "repeater", "bind": "bullets",
                "geom": _geom(_MG, 2.7, _RULE_W, 3.9),
                "direction": "vertical", "stride": 0.0, "render": "paragraphs",
                "item": {
                    "paraStyle": {"spaceAfter": 12, "lineSpacing": 1.45, "align": "left"},
                    "elements": [
                        _run(_style("body", 18, "mute"), text="—  "),
                        _run(_style("body", 18, "ink"), bind="@item"),
                    ],
                },
            },
            *_footer_elements(),
        ],
    }
    return {
        "schema_version": 1,
        "slide": {"w": _SW, "h": _SH, "margin": _MG},
        "theme": theme,
        "blocks": [title_block, section_block, bullets_block],
    }


# ───────── modern ─────────
def _modern():
    theme = {
        "colors": {
            "ink": "#0F172A",
            "inkSoft": "#475569",
            "mute": "#94A3B8",
            "rule": "#E2E8F0",
            "paper": "#FFFFFF",
            "panel": "#F1F5F9",
            "accent": "#2563EB",
        },
        "fonts": {"head": "Pretendard", "body": "Pretendard", "mono": "Consolas"},
    }
    title_block = {
        "type": "title", "label": "Title", "bg": "paper",
        "elements": [
            _rect(_geom(0, 0, 0.35, _SH), "accent"),
            _bound("deck.title", _geom(_MG, 0.8, 8, 0.4),
                   _style("mono", 10, "accent", bold=True), transform=["upper"]),
            _bound("title", _geom(_MG, 3.0, _RULE_W, 1.7),
                   _style("head", 58, "ink", bold=True, lineSpacing=1.05), fallback=""),
            _bound("subtitle", _geom(_MG, 4.7, _RULE_W, 1.0),
                   _style("body", 20, "inkSoft", lineSpacing=1.35), visible_if="subtitle"),
            _bound("meta", _geom(_META_X, 0.8, 6, 0.4),
                   _style("mono", 10, "mute", align="right"), visible_if="meta"),
        ],
    }
    section_block = {
        "type": "section", "label": "Section", "bg": "panel",
        "elements": [
            _rect(_geom(0, 0, _SW, 0.25), "accent"),
            _text("SECTION", _geom(_MG, 0.9, 6, 0.4), _style("mono", 10, "accent", bold=True)),
            _bound("@sectionNo", _geom(_MG, 2.4, 6.5, 3.0),
                   _style("head", 140, "accent", bold=True, anchor="top", lineSpacing=0.95),
                   transform=["roman"]),
            _bound("title", _geom(_SEC_TITLE_X, 3.2, _SEC_TITLE_W, 1.4),
                   _style("head", 34, "ink", bold=True, anchor="top", lineSpacing=1.15)),
            _bound("note", _geom(_SEC_TITLE_X, 4.7, _SEC_TITLE_W, 1.0),
                   _style("body", 15, "inkSoft", lineSpacing=1.5), visible_if="note"),
            *_footer_elements(),
        ],
    }
    bullets_block = {
        "type": "bullets", "label": "Bullets", "bg": "paper",
        "elements": [
            _rect(_geom(_MG, 1.5, 0.5, 0.08), "accent"),
            _bound("title", _geom(_MG, 0.9, _RULE_W, 0.8),
                   _style("head", 30, "ink", bold=True, lineSpacing=1.1)),
            _bound("subtitle", _geom(_MG, 1.8, _RULE_W, 0.6),
                   _style("body", 15, "inkSoft"), visible_if="subtitle"),
            {
                "kind": "repeater", "bind": "bullets",
                "geom": _geom(_MG, 2.6, _RULE_W, 4.0),
                "direction": "vertical", "stride": 0.0, "render": "paragraphs",
                "item": {
                    "paraStyle": {"spaceAfter": 13, "lineSpacing": 1.5, "align": "left"},
                    "elements": [
                        _run(_style("mono", 13, "accent", bold=True), bind="@itemNo", transform=["pad2"]),
                        _run(_style("body", 18, "ink"), text="   "),
                        _run(_style("body", 18, "ink"), bind="@item"),
                    ],
                },
            },
            *_footer_elements(),
        ],
    }
    # cards 블록 — boxes 그리드 repeater 데모
    cards_block = {
        "type": "cards", "label": "Cards", "bg": "paper",
        "elements": [
            _bound("title", _geom(_MG, 0.9, _RULE_W, 0.8),
                   _style("head", 30, "ink", bold=True)),
            {
                "kind": "repeater", "bind": "bullets",
                "geom": _geom(_MG, 2.2, _RULE_W, 4.2),
                "direction": "grid", "columns": 2,
                "stride": 1.5, "spacing": 0.4, "render": "boxes",
                "item": {
                    "geom": _geom(0, 0, 5.6, 1.3),
                    "elements": [
                        _rect(_geom(0, 0, 5.6, 1.3), "panel"),
                        _rect(_geom(0, 0, 0.1, 1.3), "accent"),
                        _bound("@item", _geom(0.3, 0.2, 5.1, 0.9),
                               _style("body", 14, "ink", anchor="middle", lineSpacing=1.3)),
                    ],
                },
            },
            *_footer_elements(),
        ],
    }
    return {
        "schema_version": 1,
        "slide": {"w": _SW, "h": _SH, "margin": _MG},
        "theme": theme,
        "blocks": [title_block, section_block, bullets_block, cards_block],
    }


# ───────── 공개 API ─────────
PRESETS = {
    "editorial": {
        "key": "editorial",
        "name": "Editorial",
        "description": "에디토리얼 톤 — 룰선·테라코타 액센트·큰 타이포 (기존 기본 디자인).",
        "content": _editorial(),
    },
    "minimal": {
        "key": "minimal",
        "name": "Minimal",
        "description": "여백 위주의 무채색 미니멀 — 룰선·액센트 없이 큰 제목과 대시 불릿.",
        "content": _minimal(),
    },
    "modern": {
        "key": "modern",
        "name": "Modern",
        "description": "블루 액센트 밴드 + 산세리프 헤드, 카드 그리드 블록 포함.",
        "content": _modern(),
    },
}

# 활성 템플릿이 없을 때의 기본값 (= 기존 builder.py 출력)
DEFAULT_TEMPLATE = PRESETS["editorial"]["content"]


def list_presets() -> list[dict]:
    """REST /presets 응답용 — key/name/description/content 리스트."""
    return [PRESETS[k] for k in ("editorial", "minimal", "modern")]
