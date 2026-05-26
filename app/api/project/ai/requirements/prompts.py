"""요구사항정의서 정리(organize) 전용 프롬프트 + 마크다운 표 파서.

대화 전체를 받아 (헤더 + 표 행들) 형태로 구조화된 마크다운을 만든다.
파서는 헤더 섹션과 표를 정규식으로 추출하며,
파싱 실패한 셀은 빈 문자열로 fallback (방어적).
"""
import re


# 표 컬럼 헤더 → 내부 필드명
COLUMN_MAP: dict[str, str] = {
    "업무구분":          "business_category",
    "요구사항분류":      "requirement_category",
    "요구사항ID":        "requirement_id",
    "요구사항번호":      "req_no",
    "요구사항명":        "name",
    "요구사항 상세내용": "detail",
}

# 표 출력 시 사용할 컬럼 순서 (내부 필드명 기준)
ROW_FIELD_ORDER: tuple[str, ...] = (
    "business_category",
    "requirement_category",
    "requirement_id",
    "req_no",
    "name",
    "detail",
)


REQUIREMENTS_ORGANIZER_PROMPT = """당신은 IT 프로젝트 요구사항정의서 작성 전문 AI입니다.
주어진 사용자-AI 대화를 읽고, 아래 정확한 마크다운 형식으로 정리하세요.

## 헤더
- 업무명(대분류): <한 줄>
- 시스템 명: <한 줄>

## 요구사항 표
| 업무구분 | 요구사항분류 | 요구사항ID | 요구사항번호 | 요구사항명 | 요구사항 상세내용 |
|---|---|---|---|---|---|
| 접수기능 | 기능요구사항 | AP-FR-001 | REQ-001 | 프로세스 분리 구조 | 발송요청 접수부와 처리부를 ... |
| ...

규칙:
1. 두 섹션(`## 헤더`, `## 요구사항 표`)을 정확히 이 순서·이 헤더 문구로 작성합니다.
2. 대화에서 직접 도출된 항목만 사용합니다. 추측·창작 금지.
3. 요구사항ID는 `AP-FR-001`, `AP-NFR-001` 같은 일관된 패턴으로 작성합니다 (FR=기능, NFR=비기능).
4. 같은 요구사항ID가 여러 행을 가지면 ID 컬럼만 동일하게 반복합니다.
5. 정보 없는 셀은 빈칸으로 둡니다 (`-` 같은 placeholder 금지).
6. 정보 부족한 항목은 행을 만들지 않습니다 (가짜 행 생성 금지).
7. 표 외 다른 텍스트는 작성하지 마세요 (인사/메타설명/요약/코드블록 금지).
"""


_HEADER_BIZ_PATTERN = re.compile(r"업무명.*?:\s*(.+?)\s*$", re.MULTILINE)
_HEADER_SYS_PATTERN = re.compile(r"시스템\s*명.*?:\s*(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_PATTERN = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)


def _split_row(row_line: str) -> list[str]:
    """`| a | b | c |` → ['a', 'b', 'c'] (외곽 파이프 제거 + trim)."""
    inner = row_line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    """`|---|---|...` 같은 구분 행 판별."""
    return all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c)


def parse_requirements_markdown(markdown: str) -> tuple[dict, list[dict]]:
    """반환: ({"business_name", "system_name"}, [{row1}, {row2}, ...]).

    헤더 섹션과 표를 정규식으로 추출. 파싱 실패 시 안전한 기본값 반환.
    """
    header = {"business_name": "", "system_name": ""}

    biz_match = _HEADER_BIZ_PATTERN.search(markdown)
    if biz_match:
        header["business_name"] = biz_match.group(1).strip().lstrip("-").strip()

    sys_match = _HEADER_SYS_PATTERN.search(markdown)
    if sys_match:
        header["system_name"] = sys_match.group(1).strip().lstrip("-").strip()

    # 표 행 추출 — 모든 `| ... |` 라인을 모은 뒤 헤더 / 구분자 제외
    raw_rows = [_split_row(m.group(0)) for m in _TABLE_ROW_PATTERN.finditer(markdown)]
    if not raw_rows:
        return header, []

    # 첫 행이 컬럼 헤더라고 가정 → 인덱스 → 내부 필드 매핑
    header_cells = raw_rows[0]
    field_by_idx: dict[int, str] = {}
    for i, cell in enumerate(header_cells):
        key = COLUMN_MAP.get(cell.strip())
        if key:
            field_by_idx[i] = key

    if not field_by_idx:
        return header, []

    rows: list[dict] = []
    for cells in raw_rows[1:]:
        if not cells or _is_separator_row(cells):
            continue
        row = {f: "" for f in ROW_FIELD_ORDER}
        for i, value in enumerate(cells):
            field = field_by_idx.get(i)
            if field:
                row[field] = value
        # 모든 필드가 비어있으면 스킵
        if any(row[f] for f in ROW_FIELD_ORDER):
            rows.append(row)

    return header, rows
