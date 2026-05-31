"""요약 전문 AI"""

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter();

@router
def exec_summary(request: Str) -> dict
    """요약API"""