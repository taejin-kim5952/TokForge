"""세련된 디자인 build_pptx — 색·타입·룰선 위주의 에디토리얼 톤.
시그니처(build_pptx(deck))와 슬라이드 type 키는 기존과 동일."""
import io

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

# ─────────────────────────────────────────────
#  THEME  (이 블록만 바꾸면 전체 톤이 바뀜)
# ─────────────────────────────────────────────
INK         = RGBColor(0x0F, 0x17, 0x2A)   # 본문/제목
INK_SOFT    = RGBColor(0x33, 0x3D, 0x52)   # 부제·메타
MUTE        = RGBColor(0x8A, 0x91, 0xA3)   # 페이지번호·캡션
RULE        = RGBColor(0xD9, 0xD7, 0xCE)   # 룰선
PAPER       = RGBColor(0xFA, 0xFA, 0xF7)   # 본문 배경
INK_PAPER   = RGBColor(0xF1, 0xEE, 0xE6)   # 표지·간지 배경(살짝 더 따뜻)
ACCENT      = RGBColor(0xC2, 0x41, 0x0C)   # 단일 액센트 (테라코타)

FONT_HEAD   = "Pretendard"      # 없으면 자동으로 맑은 고딕로 폴백됨 (PowerPoint 측에서)
FONT_BODY   = "Pretendard"
FONT_MONO   = "Consolas"        # 메타·페이지번호용

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN  = Inches(0.85)          # 좌우 공통 마진
_BLANK  = 6


# ─────────────────────────────────────────────
#  Low-level helpers
# ─────────────────────────────────────────────
def _bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def _rect(slide, left, top, width, height, color, line=False):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    if not line:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def _line(slide, left, top, width, color, thickness_pt=0.75):
    """얇은 가로 룰선 — 두께를 Pt로 정확히 컨트롤."""
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, Emu(int(Pt(thickness_pt))))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def _box(slide, left, top, width, height, anchor=None):
    tf = slide.shapes.add_textbox(left, top, width, height).text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    if anchor is not None:
        tf.vertical_anchor = anchor
    return tf


def _para(tf, text, *, size, color, bold=False, align=PP_ALIGN.LEFT,
          space_after=6, line_spacing=None, font=None, tracking=None, first=False):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space_after)
    if line_spacing is not None:
        p.line_spacing = line_spacing
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = font or FONT_BODY
    return p


# ─────────────────────────────────────────────
#  Footer  (본문 슬라이드 공통)
# ─────────────────────────────────────────────
def _footer(slide, deck_title, page_no, total):
    y = SLIDE_H - Inches(0.55)
    _line(slide, MARGIN, y, SLIDE_W - MARGIN * 2, RULE, thickness_pt=0.5)
    # 좌측: 덱 제목
    tf = _box(slide, MARGIN, y + Inches(0.08), Inches(8), Inches(0.35))
    _para(tf, deck_title, size=9, color=MUTE, font=FONT_MONO, first=True, space_after=0)
    # 우측: 페이지 번호
    tf = _box(slide, SLIDE_W - MARGIN - Inches(4), y + Inches(0.08), Inches(4), Inches(0.35))
    _para(
        tf, f"{page_no:02d} / {total:02d}",
        size=9, color=INK_SOFT, font=FONT_MONO,
        align=PP_ALIGN.RIGHT, first=True, space_after=0,
    )


# ─────────────────────────────────────────────
#  Slide kinds
# ─────────────────────────────────────────────
def _title_slide(prs, sd, deck_title):
    s = prs.slides.add_slide(prs.slide_layouts[_BLANK])
    _bg(s, INK_PAPER)

    # 좌상단 워드마크
    tf = _box(s, MARGIN, Inches(0.7), Inches(6), Inches(0.4))
    _para(tf, deck_title.upper(), size=10, color=INK_SOFT,
          font=FONT_MONO, bold=True, first=True, space_after=0)

    # 우상단 메타 (선택적: 부제 표기용)
    meta = (sd.get("meta") or "").strip()
    if meta:
        tf = _box(s, SLIDE_W - MARGIN - Inches(6), Inches(0.7), Inches(6), Inches(0.4))
        _para(tf, meta, size=10, color=INK_SOFT,
              font=FONT_MONO, align=PP_ALIGN.RIGHT, first=True, space_after=0)

    # 얇은 가로 룰 (상단)
    _line(s, MARGIN, Inches(1.15), SLIDE_W - MARGIN * 2, RULE, 0.5)

    # 중앙 좌측 — 큰 제목 + 부제
    title = sd.get("title") or deck_title
    tf = _box(s, MARGIN, Inches(3.5), SLIDE_W - MARGIN * 2, Inches(2.6))
    _para(tf, title, size=64, color=INK, bold=True,
          line_spacing=1.05, first=True, space_after=18)
    sub = (sd.get("subtitle") or "").strip()
    if sub:
        _para(tf, sub, size=20, color=INK_SOFT, line_spacing=1.35, space_after=0)

    # 액센트 라인 (좌하단)
    _line(s, MARGIN, SLIDE_H - Inches(0.85), Inches(1.4), ACCENT, 1.5)


def _section_slide(prs, sd, section_no, deck_title, page_no, total):
    s = prs.slides.add_slide(prs.slide_layouts[_BLANK])
    _bg(s, INK_PAPER)

    # 상단 라벨 "SECTION"
    tf = _box(s, MARGIN, Inches(0.7), Inches(6), Inches(0.4))
    _para(tf, "SECTION", size=10, color=ACCENT,
          font=FONT_MONO, bold=True, first=True, space_after=0)

    _line(s, MARGIN, Inches(1.15), SLIDE_W - MARGIN * 2, RULE, 0.5)

    # 거대한 섹션 번호 (배경처럼)
    roman = _roman(section_no)
    tf = _box(s, MARGIN, Inches(2.2), Inches(6.5), Inches(3.5),
              anchor=MSO_ANCHOR.TOP)
    _para(tf, roman, size=160, color=INK, bold=True,
          font=FONT_HEAD, line_spacing=0.95, first=True, space_after=0)

    # 섹션 제목 (큰 번호 옆)
    tf = _box(s, Inches(6.4), Inches(3.2), SLIDE_W - Inches(6.4) - MARGIN, Inches(2.5),
              anchor=MSO_ANCHOR.TOP)
    _para(tf, sd.get("title", ""), size=34, color=INK, bold=True,
          line_spacing=1.15, first=True, space_after=10)

    note = (sd.get("note") or "").strip()
    if note:
        _para(tf, note, size=15, color=INK_SOFT, line_spacing=1.5, space_after=0)

    _footer(s, deck_title, page_no, total)


def _bullets_slide(prs, sd, deck_title, page_no, total, section_label=None):
    s = prs.slides.add_slide(prs.slide_layouts[_BLANK])
    _bg(s, PAPER)

    # 상단 메타 라인
    top = Inches(0.7)
    tf = _box(s, MARGIN, top, Inches(8), Inches(0.4))
    _para(tf, (section_label or "OVERVIEW").upper(),
          size=10, color=ACCENT, font=FONT_MONO, bold=True,
          first=True, space_after=0)

    tf = _box(s, SLIDE_W - MARGIN - Inches(4), top, Inches(4), Inches(0.4))
    _para(tf, deck_title, size=10, color=INK_SOFT, font=FONT_MONO,
          align=PP_ALIGN.RIGHT, first=True, space_after=0)

    _line(s, MARGIN, Inches(1.15), SLIDE_W - MARGIN * 2, RULE, 0.5)

    # 슬라이드 제목
    tf = _box(s, MARGIN, Inches(1.5), SLIDE_W - MARGIN * 2, Inches(1.0))
    _para(tf, sd.get("title", ""), size=32, color=INK, bold=True,
          line_spacing=1.15, first=True, space_after=0)

    # 선택적 부제
    sub = (sd.get("subtitle") or "").strip()
    body_top = Inches(2.7)
    if sub:
        tf = _box(s, MARGIN, Inches(2.5), SLIDE_W - MARGIN * 2, Inches(0.6))
        _para(tf, sub, size=15, color=INK_SOFT, line_spacing=1.4,
              first=True, space_after=0)
        body_top = Inches(3.2)

    # 본문 영역 — 좌측 인덱스 + 우측 텍스트의 2열 느낌
    bullets = sd.get("bullets") or []
    body = _box(s, MARGIN, body_top, SLIDE_W - MARGIN * 2,
                SLIDE_H - body_top - Inches(0.9))

    for i, b in enumerate(bullets):
        # 번호 + em-dash + 본문 — 한 줄로 합쳐 들여쓰기 흉내
        idx = f"{i+1:02d}"
        # 인덱스(작게, 모노) — 같은 줄에 run으로 따로 추가
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(14)
        p.line_spacing = 1.5

        r1 = p.add_run(); r1.text = idx + "   "
        r1.font.size = Pt(11); r1.font.color.rgb = MUTE
        r1.font.name = FONT_MONO; r1.font.bold = True

        r2 = p.add_run(); r2.text = b
        r2.font.size = Pt(18); r2.font.color.rgb = INK
        r2.font.name = FONT_BODY

    _footer(s, deck_title, page_no, total)


# ─────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────
_ROMANS = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
           "XI", "XII", "XIII", "XIV", "XV"]
def _roman(n):
    return _ROMANS[n] + "." if 0 < n < len(_ROMANS) else f"{n:02d}."


# ─────────────────────────────────────────────
#  Builder
# ─────────────────────────────────────────────
def build_pptx(deck) -> bytes:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slides = deck["slides"]
    total = len(slides)
    section_no = 0
    current_section_title = None

    for i, sd in enumerate(slides):
        t = sd["type"]
        page_no = i + 1
        if t == "title":
            _title_slide(prs, sd, deck["title"])
        elif t == "section":
            section_no += 1
            current_section_title = sd.get("title", "")
            _section_slide(prs, sd, section_no, deck["title"], page_no, total)
        else:
            _bullets_slide(prs, sd, deck["title"], page_no, total,
                           section_label=current_section_title)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────
#  실행  (python _design_builder_proto.py → 샘플 .pptx 생성)
# ─────────────────────────────────────────────
if __name__ == "__main__":
    DECK = {
        "title": "TokForge 소개",
        "slides": [
            {"type": "title", "title": "TokForge",
             "subtitle": "셀프호스팅 LLM 토큰 절감 워크스페이스", "meta": "2026 PROPOSAL"},
            {"type": "section", "title": "배경 및 필요성", "note": "기존 LLM 운영의 한계 진단"},
            {"type": "bullets", "title": "기존 LLM 운영의 과제", "bullets": [
                "유료 API 토큰 비용이 사용량에 비례해 선형 증가",
                "캐시·로컬 모델 활용 부재로 동일 요청 반복 과금",
                "어떤 호출이 비용을 유발하는지 가시성이 없음",
                "프로젝트별 컨텍스트 격리·재사용 체계 미비",
            ]},
            {"type": "bullets", "title": "TokForge의 접근",
             "subtitle": "캐시·로컬 우선 라우팅 + 비용 가시화",
             "bullets": [
                "캐시 히트 + 로컬 Ollama 우선 라우팅으로 유료 호출 최소화",
                "요청별 토큰·비용 지표 기록으로 절감액 산출",
                "프로젝트 단위 컨텍스트 격리로 재사용성 확보",
            ]},
            {"type": "section", "title": "기대 효과", "note": "비용·운영 관점의 가치"},
            {"type": "bullets", "title": "비용 절감 ROI", "bullets": [
                "캐시 히트·로컬 처리 시 해당 호출 비용 100% 절감",
                "유료 호출은 실제 발생 비용만 베이스라인 대비 집계",
            ]},
        ],
    }
    data = build_pptx(DECK)
    out = r"d:\tuning\_design_sample.pptx"
    with open(out, "wb") as f:
        f.write(data)
    print(f"OK {len(data)} bytes, {len(DECK['slides'])} slides -> {out}")