from __future__ import annotations

import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from graphkit.compiler import compile_workspace, validate_workspace
from graphkit.evaluation import evaluate_workspace
from graphkit.models import GraphSpec
from graphkit.neo4j_store import execute_recipe
from graphkit.retrieval import RulePlanner, public_query_payload, recipe_for
from graphkit.workspace import (
    approval_is_current,
    approve_workspace,
    load_approval,
    load_profile,
    load_spec,
    save_spec,
)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str | None = None
    question: str = Field(min_length=2, max_length=500)


class RateLimiter:
    def __init__(self, requests: int = 60, window_seconds: int = 60) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, identity: str) -> None:
        now = time.monotonic()
        events = self.events[identity]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.requests:
            raise HTTPException(status_code=429, detail="Query rate limit exceeded")
        events.append(now)


def create_app(
    *,
    workspace: Path | None = None,
    scenarios_root: Path | None = None,
    public: bool = False,
    token: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="GraphRAG Ontology Workbench",
        version="0.2.0",
        debug=False,
        docs_url=None if public else "/docs",
        redoc_url=None if public else "/redoc",
        openapi_url=None if public else "/openapi.json",
    )
    configured_hosts = [
        host.strip()
        for host in os.getenv("GRAPHKIT_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=configured_hosts
        or ["127.0.0.1", "localhost", "testserver"],
    )
    local_token = token or secrets.token_urlsafe(24)
    workspace = workspace.resolve() if workspace else None
    scenarios_root = scenarios_root.resolve() if scenarios_root else None
    static_dir = Path(__file__).parent / "static"
    limiter = RateLimiter()

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = None
        if public:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > 16_384:
                        response = JSONResponse(
                            {"detail": "Request body too large"},
                            status_code=413,
                        )
                except ValueError:
                    response = JSONResponse(
                        {"detail": "Invalid Content-Length header"},
                        status_code=400,
                    )
        if response is None:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "style-src-attr 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        return response

    def require_local_token(
        request: Request,
        x_graphkit_token: str = Header(default=""),
    ) -> None:
        fetch_site = request.headers.get("sec-fetch-site", "")
        if fetch_site not in {"", "none", "same-origin"}:
            raise HTTPException(status_code=403, detail="Cross-site request rejected")
        origin = request.headers.get("origin")
        if origin:
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme != "http"
                or parsed_origin.hostname not in {"127.0.0.1", "localhost"}
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise HTTPException(status_code=403, detail="Invalid local request origin")
        session_token = request.cookies.get("graphkit_session", "")
        valid_header = secrets.compare_digest(x_graphkit_token, local_token)
        valid_session = secrets.compare_digest(session_token, local_token)
        if public or not (valid_header and valid_session):
            raise HTTPException(status_code=403, detail="Invalid local workbench token")

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "mode": "public" if public else "local"}

    @app.get("/v1/scenarios")
    async def scenarios() -> list[dict[str, Any]]:
        if not scenarios_root:
            return []
        output = []
        for path in sorted(scenarios_root.iterdir()):
            if not path.is_dir() or not (path / "graphspec.yaml").exists():
                continue
            spec = load_spec(path)
            output.append(
                {
                    "id": path.name,
                    "name": spec.metadata.name,
                    "version": spec.metadata.version,
                    "description": spec.metadata.description,
                }
            )
        return output

    @app.get("/v1/scenarios/{scenario_id}/build")
    async def scenario_build(scenario_id: str) -> dict[str, Any]:
        scenario = resolve_scenario(scenarios_root, scenario_id)
        graph = compile_workspace(scenario)
        return {
            "profile": load_profile(scenario).model_dump(mode="json"),
            "spec": load_spec(scenario).model_dump(mode="json"),
            "counts": graph.counts,
            "ontology_hash": graph.ontology_hash,
            "data_hash": graph.data_hash,
        }

    @app.get("/v1/evaluations/{scenario_id}")
    async def scenario_evaluation(scenario_id: str) -> dict[str, Any]:
        scenario = resolve_scenario(scenarios_root, scenario_id)
        report = scenario / "generated" / "evaluation.json"
        if not report.exists():
            raise HTTPException(status_code=404, detail="No evaluation artifact is committed")
        return json.loads(report.read_text())

    @app.post("/v1/query")
    async def query(payload: QueryRequest, request: Request) -> dict[str, Any]:
        if public:
            limiter.check(request.client.host if request.client else "unknown")
        target = (
            resolve_scenario(scenarios_root, payload.scenario)
            if scenarios_root and payload.scenario
            else workspace
        )
        if not target:
            raise HTTPException(status_code=400, detail="A workspace or scenario is required")
        spec = load_spec(target)
        graph = compile_workspace(target)
        started = time.perf_counter()
        selection = await RulePlanner().select(payload.question, spec, graph)
        planning_ms = round((time.perf_counter() - started) * 1000, 2)
        recipe = recipe_for(selection, spec)
        response = public_query_payload(
            payload.question,
            selection,
            recipe,
            graph,
            spec.vector.top_k,
        )
        response["timings_ms"]["planning"] = planning_ms
        if (
            selection.supported
            and recipe
            and recipe.cypher
            and selection.route in {"graph", "hybrid"}
        ):
            neo4j_config = (
                os.getenv("NEO4J_URI"),
                os.getenv("NEO4J_USERNAME"),
                os.getenv("NEO4J_PASSWORD"),
            )
            if all(neo4j_config):
                from neo4j import AsyncGraphDatabase

                driver = AsyncGraphDatabase.driver(
                    neo4j_config[0],
                    auth=(neo4j_config[1], neo4j_config[2]),
                )
                graph_started = time.perf_counter()
                try:
                    response["graph_trace"] = await execute_recipe(
                        driver,
                        recipe,
                        selection.parameters,
                        spec.metadata.tenant_id,
                    )
                    response["engine"] = "neo4j_read_only"
                    response["notice"] = (
                        "Executed an approved, tenant-scoped, bounded read recipe."
                    )
                finally:
                    await driver.close()
                response["timings_ms"]["graph"] = round(
                    (time.perf_counter() - graph_started) * 1000,
                    2,
                )
        response["reference_evaluation"] = reference_evaluation(
            target,
            payload.question,
        )
        return response

    if not public and workspace:

        @app.get("/api/workspace")
        async def get_workspace() -> dict[str, Any]:
            return {
                "profile": load_profile(workspace).model_dump(mode="json"),
                "spec": load_spec(workspace).model_dump(mode="json"),
                "validation": validate_workspace(workspace).model_dump(mode="json"),
                "approval": (
                    load_approval(workspace).model_dump(mode="json")
                    if load_approval(workspace)
                    else None
                ),
                "approval_current": approval_is_current(workspace),
            }

        @app.put("/api/workspace/spec", dependencies=[Depends(require_local_token)])
        async def put_spec(spec: GraphSpec) -> dict[str, Any]:
            save_spec(workspace, spec)
            return {"saved": True, "approval_current": False}

        @app.post("/api/workspace/validate", dependencies=[Depends(require_local_token)])
        async def validate() -> dict[str, Any]:
            return validate_workspace(workspace).model_dump(mode="json")

        @app.post("/api/workspace/approve", dependencies=[Depends(require_local_token)])
        async def approve() -> dict[str, Any]:
            report = validate_workspace(workspace)
            if not report.valid:
                raise HTTPException(status_code=422, detail=report.model_dump(mode="json"))
            return approve_workspace(workspace).model_dump(mode="json")

        @app.post("/api/workspace/build", dependencies=[Depends(require_local_token)])
        async def build() -> dict[str, Any]:
            graph = compile_workspace(workspace)
            output = workspace / "generated"
            output.mkdir(exist_ok=True)
            (output / "graph-ir.json").write_text(graph.model_dump_json(indent=2) + "\n")
            return graph.model_dump(mode="json")

        @app.post("/api/workspace/evaluate", dependencies=[Depends(require_local_token)])
        async def evaluate() -> dict[str, Any]:
            return await evaluate_workspace(workspace)

        @app.get("/")
        async def index(request: Request) -> HTMLResponse:
            index_path = static_dir / "index.html"
            if not index_path.exists():
                response = HTMLResponse(
                    "<h1>Workbench UI is not built</h1><p>Run the frontend build first.</p>",
                    status_code=503,
                )
            else:
                html = index_path.read_text().replace("__GRAPHKIT_TOKEN__", local_token)
                response = HTMLResponse(html)
            response.set_cookie(
                "graphkit_session",
                local_token,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
            return response

        if static_dir.exists():
            app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    return app


def resolve_scenario(root: Path | None, scenario_id: str | None) -> Path:
    if not root or not scenario_id or not scenario_id.replace("-", "_").isalnum():
        raise HTTPException(status_code=404, detail="Unknown scenario")
    candidate = (root / scenario_id).resolve()
    if root not in candidate.parents or not (candidate / "graphspec.yaml").exists():
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return candidate


def reference_evaluation(workspace: Path, question: str) -> dict[str, Any] | None:
    path = workspace / "generated" / "evaluation.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    row = next(
        (item for item in report.get("rows", []) if item["question"] == question),
        None,
    )
    if not row:
        return None
    return {
        "case_id": row["id"],
        "category": row.get("category"),
        "passed": row["passed"],
        "provider": report["provider"],
        "model": report["model"],
        "notice": "This result exists only because the exact question is held out.",
    }


def app_from_environment() -> FastAPI:
    workspace = os.getenv("GRAPHKIT_WORKSPACE")
    scenarios = os.getenv("GRAPHKIT_SCENARIOS_ROOT")
    public = os.getenv("GRAPHKIT_PUBLIC", "false").lower() == "true"
    return create_app(
        workspace=Path(workspace) if workspace else None,
        scenarios_root=Path(scenarios) if scenarios else None,
        public=public,
    )


app = app_from_environment()
