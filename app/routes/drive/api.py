from fastapi import APIRouter
from app.routes.drive import scopes, tree, documents

router = APIRouter(prefix="/drive")
router.include_router(scopes.router)
router.include_router(tree.router)
router.include_router(documents.router)
