from fastapi import APIRouter

from .conversations import router as conversations_router
from .organize import router as organize_router
from .requirements import router as requirements_router

router = APIRouter()
router.include_router(requirements_router)
router.include_router(conversations_router)
router.include_router(organize_router)
