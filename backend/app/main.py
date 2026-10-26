from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.research import router as research_router
from app.core.config import settings
from app.research.job_manager import ResearchJobManager


def create_app(manager: ResearchJobManager | None = None) -> FastAPI:
    """Create one in-memory manager for this backend process."""
    application = FastAPI(title="Autocomplete Keyword Research")
    application.state.settings = settings
    application.state.research_manager = manager or ResearchJobManager()
    application.include_router(health_router)
    application.include_router(research_router)
    return application


app = create_app()
