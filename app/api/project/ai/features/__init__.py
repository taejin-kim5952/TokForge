from fastapi import APIRouter

from .conversations import router as conversations_router
from .features import router as features_router
from .organize import router as organize_router

router = APIRouter()
router.include_router(features_router)
router.include_router(conversations_router)
router.include_router(organize_router)
