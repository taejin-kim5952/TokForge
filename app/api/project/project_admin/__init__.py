""""""

import logging
from fastapi import APIRouter
from app.api.project.project_admin.modelfile import router as modelfile_router

router = APIRouter(tags=["project_admin"])
router.include_router(modelfile_router)