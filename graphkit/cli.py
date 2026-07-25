from __future__ import annotations

import asyncio
import json
import os
import secrets
import webbrowser
from pathlib import Path

import typer
import uvicorn

from graphkit.api import create_app
from graphkit.compiler import compile_workspace, validate_workspace
from graphkit.evaluation import evaluate_workspace
from graphkit.models import GraphSpec
from graphkit.neo4j_store import ingest_graph
from graphkit.providers import (
    PROFILES,
    build_vector_index,
    check_profile,
    planner_for,
)
from graphkit.retrieval import RulePlanner, public_query_payload, recipe_for
from graphkit.workspace import (
    approve_workspace,
    atomic_write,
    initialize_workspace,
    load_spec,
    profile_sources,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Convert governed data sources into an approved GraphRAG workspace.",
)


@app.command("init")
def initialize(
    data: Path = typer.Option(..., exists=True, file_okay=False, readable=True),
    workspace: Path = typer.Option(Path(".")),
) -> None:
    """Copy and profile supported sources, then generate an agent brief."""
    profile = initialize_workspace(data, workspace)
    typer.echo(
        json.dumps(
            {"workspace": str(workspace.resolve()), "sources": len(profile.sources)},
            indent=2,
        )
    )


@app.command()
def profile(workspace: Path = typer.Option(Path("."), exists=True, file_okay=False)) -> None:
    """Refresh the source manifest for an existing workspace."""
    source_root = workspace / "sources"
    result = profile_sources(source_root)
    atomic_write(workspace / "source-profile.json", result.model_dump_json(indent=2) + "\n")
    typer.echo(json.dumps({"sources": len(result.sources)}, indent=2))


@app.command()
def schema(output: Path | None = typer.Option(None)) -> None:
    """Print or write the canonical GraphSpec JSON Schema."""
    content = json.dumps(GraphSpec.model_json_schema(), indent=2) + "\n"
    if output:
        output.write_text(content)
    else:
        typer.echo(content)


@app.command()
def validate(workspace: Path = typer.Option(Path("."), exists=True, file_okay=False)) -> None:
    """Validate mappings, source coverage, recipes, and compilation."""
    report = validate_workspace(workspace)
    typer.echo(report.model_dump_json(indent=2))
    if not report.valid:
        raise typer.Exit(1)


@app.command()
def approve(workspace: Path = typer.Option(Path("."), exists=True, file_okay=False)) -> None:
    """Approve the current spec and source manifest after validation."""
    report = validate_workspace(workspace)
    if not report.valid:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(1)
    typer.echo(approve_workspace(workspace).model_dump_json(indent=2))


@app.command()
def build(
    workspace: Path = typer.Option(Path("."), exists=True, file_okay=False),
    load_neo4j: bool = typer.Option(False, "--load-neo4j/--no-load-neo4j"),
    provider: str = typer.Option("offline", help="offline, openai, or ollama"),
) -> None:
    """Compile an approved workspace into graph IR and corpus artifacts."""
    graph = compile_workspace(workspace)
    output = workspace / "generated"
    output.mkdir(exist_ok=True)
    (output / "graph-ir.json").write_text(graph.model_dump_json(indent=2) + "\n")
    (output / "corpus.jsonl").write_text(
        "".join(chunk.model_dump_json() + "\n" for chunk in graph.corpus)
    )
    result: dict[str, object] = {"counts": graph.counts, "neo4j_loaded": False}
    if load_neo4j:
        uri = os.getenv("NEO4J_URI")
        username = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        if not all((uri, username, password)):
            raise typer.BadParameter(
                "NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD are required"
            )
        from neo4j import AsyncGraphDatabase

        async def load() -> None:
            driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
            try:
                await ingest_graph(driver, graph)
            finally:
                await driver.close()

        asyncio.run(load())
        result["neo4j_loaded"] = True
        runtime = PROFILES.get(provider)
        if not runtime:
            raise typer.BadParameter(f"Unknown provider profile: {provider}")
        if provider != "offline":
            result["vector_index"] = build_vector_index(
                uri,
                username,
                password,
                graph,
                runtime,
            )
    typer.echo(json.dumps(result, indent=2))


@app.command("eval")
def evaluate(
    workspace: Path = typer.Option(Path("."), exists=True, file_okay=False),
    provider: str = typer.Option("offline", help="offline, openai, or ollama"),
) -> None:
    """Evaluate approved-recipe routing against reviewed cases."""
    runtime = PROFILES.get(provider)
    if not runtime:
        raise typer.BadParameter(f"Unknown provider profile: {provider}")
    readiness = asyncio.run(check_profile(runtime))
    if not readiness["ready"]:
        typer.echo(json.dumps(readiness, indent=2))
        raise typer.Exit(1)
    planner = planner_for(runtime)
    typer.echo(
        json.dumps(
            asyncio.run(
                evaluate_workspace(
                    workspace,
                    planner=planner,
                    provider=(
                        "rule-planner"
                        if runtime.provider == "rule"
                        else runtime.provider
                    ),
                    model=runtime.planner_model,
                )
            ),
            indent=2,
        )
    )


@app.command()
def query(
    question: str,
    workspace: Path = typer.Option(Path("."), exists=True, file_okay=False),
) -> None:
    """Plan a free-text question through an approved query recipe."""
    spec = load_spec(workspace)
    graph = compile_workspace(workspace)
    selection = asyncio.run(RulePlanner().select(question, spec, graph))
    typer.echo(
        json.dumps(
            public_query_payload(
                question,
                selection,
                recipe_for(selection, spec),
                graph,
                spec.vector.top_k,
            ),
            indent=2,
        )
    )


@app.command("provider-check")
def provider_check(
    profile: str = typer.Option("offline", help="offline, openai, or ollama"),
) -> None:
    """Check provider credentials, connectivity, and required local models."""
    runtime = PROFILES.get(profile)
    if not runtime:
        raise typer.BadParameter(f"Unknown provider profile: {profile}")
    result = asyncio.run(check_profile(runtime))
    typer.echo(json.dumps(result, indent=2))
    if not result["ready"]:
        raise typer.Exit(1)


@app.command()
def review(
    workspace: Path = typer.Option(Path("."), exists=True, file_okay=False),
    port: int = typer.Option(8765, min=1024, max=65535),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Launch the local ontology editor."""
    token = secrets.token_urlsafe(24)
    local_app = create_app(workspace=workspace, token=token)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    uvicorn.run(local_app, host="127.0.0.1", port=port)


@app.command()
def serve(
    workspace: Path = typer.Option(Path("."), exists=True, file_okay=False),
    port: int = typer.Option(8000, min=1024, max=65535),
) -> None:
    """Serve the read-only query API for one workspace."""
    uvicorn.run(create_app(workspace=workspace, public=True), host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
