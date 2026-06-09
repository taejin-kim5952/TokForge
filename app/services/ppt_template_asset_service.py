"""PPT 템플릿 이미지 에셋 저장소 (로고/배경 등).

에셋은 (project_id, asset_id)로만 식별된다 — 템플릿 id 와 무관하며, 파서가
이미지를 추출하는 즉시 디스크에 저장되어 편집 중 <img> 프리뷰·서버 preview·
실제 생성이 모두 같은 id 로 해석한다. 별도 DB 테이블 없음(디스크가 진실).

저장 경로: storage/ppt_template_assets/project_{id}/{asset_id}.{ext}
"""

import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

ASSETS_BASE = Path(__file__).parent.parent.parent / "storage" / "ppt_template_assets"

# python-pptx shape.image.ext 가 돌려주는 확장자들
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "emf", "wmf"}

_ASSET_ID_RE = re.compile(r"^[0-9a-f]{12}$")

_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "emf": "image/emf",
    "wmf": "image/wmf",
}


def _project_dir(project_id: int) -> Path:
    return ASSETS_BASE / f"project_{project_id}"


def _norm_ext(ext: str) -> str:
    e = (ext or "").lower().lstrip(".")
    return e if e in ALLOWED_IMAGE_EXTS else "png"


def save_asset(project_id: int, raw: bytes, ext: str) -> str:
    """이미지 바이트 저장 → asset_id 반환 (12-hex)."""
    asset_id = uuid.uuid4().hex[:12]
    d = _project_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{asset_id}.{_norm_ext(ext)}"
    path.write_bytes(raw)
    logger.info("ppt asset saved: project=%d asset=%s bytes=%d",
                project_id, asset_id, len(raw))
    return asset_id


def resolve_asset_path(project_id: int, asset_id: str) -> Path | None:
    """(project_id, asset_id) → 디스크 경로. 형식 위반/부재 시 None (traversal 방지)."""
    if not asset_id or not _ASSET_ID_RE.match(asset_id):
        return None
    matches = list(_project_dir(project_id).glob(f"{asset_id}.*"))
    return matches[0] if matches else None


def asset_media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
