from fastapi import APIRouter

from .ppt import router as ppt_router

router = APIRouter()
router.include_router(ppt_router)
