"""HTTP routes for the single in-memory research job."""

import csv
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.research_schemas import (
    DiscoveryResponse,
    JobResponse,
    KeywordPage,
    KeywordResponse,
    ResearchRequest,
)
from app.research.job_manager import (
    InvalidJobTransitionError,
    JobConflictError,
    NoCurrentJobError,
    ResearchJobManager,
)
from app.services.recursive_research import ResearchKeyword


router = APIRouter(prefix="/api/research", tags=["research"])


def get_manager(request: Request) -> ResearchJobManager:
    return request.app.state.research_manager


Manager = Annotated[ResearchJobManager, Depends(get_manager)]


def _api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NoCurrentJobError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, (JobConflictError, InvalidJobTransitionError)):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "research operation failed")


def _keyword_response(keyword: ResearchKeyword) -> KeywordResponse:
    first = keyword.discoveries[0]
    return KeywordResponse(
        keyword=keyword.text,
        depth=keyword.first_depth,
        first_discovery_query=first.query,
        expansion_method=first.method,
        discoveries=[
            DiscoveryResponse.model_validate(origin, from_attributes=True)
            for origin in keyword.discoveries
        ],
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def start_research(body: ResearchRequest, manager: Manager) -> JobResponse:
    try:
        return JobResponse.from_progress(await manager.start(body.to_config()))
    except JobConflictError as exc:
        raise _api_error(exc) from exc


@router.get("/current", response_model=JobResponse)
async def current_research(manager: Manager) -> JobResponse:
    try:
        return JobResponse.from_progress(await manager.get_progress())
    except NoCurrentJobError as exc:
        raise _api_error(exc) from exc


@router.post("/current/pause", response_model=JobResponse)
async def pause_research(manager: Manager) -> JobResponse:
    try:
        return JobResponse.from_progress(await manager.pause())
    except (NoCurrentJobError, InvalidJobTransitionError) as exc:
        raise _api_error(exc) from exc


@router.post("/current/resume", response_model=JobResponse)
async def resume_research(manager: Manager) -> JobResponse:
    try:
        return JobResponse.from_progress(await manager.resume())
    except (NoCurrentJobError, InvalidJobTransitionError) as exc:
        raise _api_error(exc) from exc


@router.post("/current/cancel", response_model=JobResponse)
async def cancel_research(manager: Manager) -> JobResponse:
    try:
        return JobResponse.from_progress(await manager.cancel())
    except (NoCurrentJobError, InvalidJobTransitionError) as exc:
        raise _api_error(exc) from exc


@router.get("/current/keywords", response_model=KeywordPage)
async def list_keywords(
    manager: Manager,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    filter: Annotated[str | None, Query(max_length=200)] = None,
) -> KeywordPage:
    try:
        result = await manager.get_results()
    except NoCurrentJobError as exc:
        raise _api_error(exc) from exc
    needle = filter.casefold() if filter else None
    total = 0
    page: list[KeywordResponse] = []
    # No await inside this traversal, so the worker cannot mutate it mid-iteration.
    for keyword in result.keywords.values():
        if needle is not None and needle not in keyword.text.casefold():
            continue
        if offset <= total < offset + limit:
            page.append(_keyword_response(keyword))
        total += 1
    return KeywordPage(total=total, offset=offset, limit=limit, items=page)


def _safe_csv_cell(value: str) -> str:
    """Prefix spreadsheet formulas, including ones hidden after whitespace."""
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _csv_rows(rows: list[tuple[str, int, str, str, str]]):
    yield "\ufeff"
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("Keyword", "Depth", "First Discovery Query", "Expansion Method", "Discovery Queries"))
    yield buffer.getvalue()
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow((_safe_csv_cell(row[0]), row[1], *(_safe_csv_cell(value) for value in row[2:])))
        yield buffer.getvalue()


@router.get("/current/export")
async def export_keywords(manager: Manager) -> StreamingResponse:
    try:
        result = await manager.get_results()
    except NoCurrentJobError as exc:
        raise _api_error(exc) from exc
    # Capture immutable scalar rows synchronously for a consistent partial export.
    rows = [
        (keyword.text, origin.depth, keyword.discoveries[0].query, origin.method, origin.query)
        for keyword in result.keywords.values()
        for origin in keyword.discoveries
    ]
    return StreamingResponse(
        _csv_rows(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="autocomplete-keywords.csv"'},
    )


@router.delete("/current", status_code=status.HTTP_204_NO_CONTENT)
async def clear_research(manager: Manager) -> None:
    try:
        await manager.clear()
    except (NoCurrentJobError, InvalidJobTransitionError) as exc:
        raise _api_error(exc) from exc
