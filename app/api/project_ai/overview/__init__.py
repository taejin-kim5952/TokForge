from fastapi import APIRouter

from .overview import router as overview_router
from .conversations import router as conversations_router
from .organize import router as organize_router

router = APIRouter()
router.include_router(overview_router)
router.include_router(conversations_router)
router.include_router(organize_router)
