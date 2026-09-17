from fastapi import APIRouter

from app.api.routes import auth, datasets, demo, experiments, health, models, snippets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(models.router)
api_router.include_router(snippets.router)
api_router.include_router(experiments.router)
api_router.include_router(demo.router)
