""""""

import logging
from fastapi import APIRouter
from app.api.project.project_admin.modelfile import router as modelfile_router
from app.api.project.project_admin.ppt_template import router as ppt_template_router

router = APIRouter(tags=["project_admin"])
router.include_router(modelfile_router)
router.include_router(ppt_template_router)