from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from graphkit.models import GraphIR, GraphSpec, QuerySelection
from graphkit.retrieval import OllamaPlanner, OpenAIPlanner, Planner, RulePlanner, index_namespace


class RuntimeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["rule", "openai", "ollama"]
    planner_model: str
    embedding_model: str | None = None
    dimensions: int | None = Field(default=None, ge=1)
    base_url: str | None = None


class Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ValidatingPlanner:
    planner: Planner
    profile: RuntimeProfile

    async def select(
        self,
        question: str,
        spec: GraphSpec,
        graph: GraphIR,
    ) -> QuerySelection:
        return await self.planner.select(question, spec, graph)


def planner_for(profile: RuntimeProfile) -> ValidatingPlanner:
    if profile.provider == "openai":
        planner: Planner = OpenAIPlanner(model=profile.planner_model)
    elif profile.provider == "ollama":
        planner = OllamaPlanner(
            model=profile.planner_model,
            base_url=profile.base_url or "http://127.0.0.1:11434",
        )
    else:
        planner = RulePlanner()
    return ValidatingPlanner(planner=planner, profile=profile)


def embedder_for(profile: RuntimeProfile) -> Embedder:
    if not profile.embedding_model:
        raise ValueError("This runtime profile does not define an embedding model")
    try:
        if profile.provider == "openai":
            from neo4j_graphrag.embeddings import OpenAIEmbeddings

            return OpenAIEmbeddings(model=profile.embedding_model)
        if profile.provider == "ollama":
            from neo4j_graphrag.embeddings.ollama import OllamaEmbeddings

            return OllamaEmbeddings(
                model=profile.embedding_model,
                host=profile.base_url or "http://127.0.0.1:11434",
            )
    except ImportError as error:
        raise RuntimeError(
            "Install provider dependencies with `uv sync --extra providers`"
        ) from error
    raise ValueError("The deterministic rule profile does not provide embeddings")


async def check_profile(profile: RuntimeProfile) -> dict[str, Any]:
    if profile.provider == "rule":
        return {
            "ready": True,
            "provider": "rule",
            "planner_model": profile.planner_model,
            "embedding_model": None,
            "limitations": ["Offline preview only; no semantic embeddings or synthesis."],
        }
    if profile.provider == "openai":
        ready = bool(os.getenv("OPENAI_API_KEY"))
        return {
            "ready": ready,
            "provider": "openai",
            "planner_model": profile.planner_model,
            "embedding_model": profile.embedding_model,
            "reason": None if ready else "OPENAI_API_KEY is not configured",
        }
    base_url = profile.base_url or "http://127.0.0.1:11434"
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=3) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            models = [item.get("name", "") for item in response.json().get("models", [])]
    except httpx.HTTPError as error:
        return {
            "ready": False,
            "provider": "ollama",
            "reason": f"Ollama is unavailable: {error.__class__.__name__}",
        }
    required = {
        item for item in (profile.planner_model, profile.embedding_model) if item
    }
    installed_names = {
        name for installed in models for name in (installed, installed.split(":")[0])
    }
    missing = sorted(required - installed_names)
    return {
        "ready": not missing,
        "provider": "ollama",
        "planner_model": profile.planner_model,
        "embedding_model": profile.embedding_model,
        "installed_models": models,
        "reason": f"Missing models: {', '.join(missing)}" if missing else None,
    }


PROFILES = {
    "offline": RuntimeProfile(
        provider="rule",
        planner_model="deterministic-token-overlap",
    ),
    "openai": RuntimeProfile(
        provider="openai",
        planner_model="gpt-5.6-luna",
        embedding_model="text-embedding-3-small",
        dimensions=1536,
    ),
    "ollama": RuntimeProfile(
        provider="ollama",
        planner_model="qwen3:8b",
        embedding_model="nomic-embed-text",
        dimensions=768,
        base_url="http://127.0.0.1:11434",
    ),
}


def build_vector_index(
    uri: str,
    username: str,
    password: str,
    graph: GraphIR,
    profile: RuntimeProfile,
    *,
    batch_size: int = 100,
) -> str:
    if not profile.dimensions:
        raise ValueError("The provider profile must declare embedding dimensions")
    try:
        from neo4j import GraphDatabase
        from neo4j_graphrag.indexes import create_vector_index
    except ImportError as error:
        raise RuntimeError(
            "Install provider dependencies with `uv sync --extra providers`"
        ) from error
    embedder = embedder_for(profile)
    name = index_namespace(
        provider=profile.provider,
        model=profile.embedding_model or "",
        dimensions=profile.dimensions,
        graph=graph,
    )
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        create_vector_index(
            driver,
            name,
            label="Chunk",
            embedding_property="embedding",
            dimensions=profile.dimensions,
            similarity_fn="cosine",
        )
        for start in range(0, len(graph.corpus), batch_size):
            chunk_batch = graph.corpus[start : start + batch_size]
            vectors = embedder.embed_documents([chunk.text for chunk in chunk_batch])
            rows = [
                {
                    "id": chunk.id,
                    "tenant_id": chunk.tenant_id,
                    "embedding": vector,
                }
                for chunk, vector in zip(chunk_batch, vectors, strict=True)
            ]
            with driver.session() as session:
                session.run(
                    "UNWIND $rows AS row "
                    "MATCH (chunk:Chunk {tenant_id: row.tenant_id, id: row.id}) "
                    "SET chunk.embedding = row.embedding",
                    rows=rows,
                ).consume()
    finally:
        driver.close()
    return name
