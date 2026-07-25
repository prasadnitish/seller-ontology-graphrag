from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

import httpx

from graphkit.models import GraphIR, GraphSpec, QueryRecipe, QuerySelection, Route

TOKEN_PATTERN = re.compile(r"[a-z0-9_$.-]+", re.IGNORECASE)
STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "for",
    "from",
    "give",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "show",
    "the",
    "to",
    "use",
    "what",
    "when",
    "which",
    "who",
    "why",
    "with",
}
PROMPT_ATTACK_PATTERN = re.compile(
    r"\b(ignore (?:all |the |your )?(?:previous )?instructions|"
    r"system prompt|delete (?:all|every)|drop database|cross[- ]tenant|"
    r"arbitrary cypher|stale ontology|ontology version)\b",
    re.IGNORECASE,
)


class Planner(Protocol):
    async def select(self, question: str, spec: GraphSpec, graph: GraphIR) -> QuerySelection: ...


@dataclass
class RulePlanner:
    minimum_confidence: float = 0.08

    async def select(self, question: str, spec: GraphSpec, graph: GraphIR) -> QuerySelection:
        if PROMPT_ATTACK_PATTERN.search(question):
            return QuerySelection(
                supported=False,
                confidence=1,
                reason="The question contains instructions outside the read-only recipe boundary",
            )
        question_tokens = tokens(question)
        scored: list[
            tuple[float, float, QueryRecipe, dict[str, Any], list[str]]
        ] = []
        for recipe in spec.query_recipes:
            lexical_score = max(
                jaccard(question_tokens, tokens(candidate))
                for candidate in [recipe.description, *recipe.examples]
            )
            parameters: dict[str, Any] = {}
            missing: list[str] = []
            for name, parameter in recipe.parameters.items():
                value = find_candidate(question, parameter.candidates, graph)
                if value is None and parameter.required:
                    missing.append(name)
                elif value is not None:
                    parameters[name] = value
            source_backed_bonus = 0.15 * len(parameters)
            scored.append(
                (
                    lexical_score + source_backed_bonus,
                    lexical_score,
                    recipe,
                    parameters,
                    missing,
                )
            )
        _, confidence, recipe, parameters, missing = max(
            scored,
            key=lambda item: item[0],
            default=(0, 0, None, {}, []),
        )
        if not recipe or confidence < self.minimum_confidence:
            return QuerySelection(
                supported=False,
                confidence=confidence,
                reason="No approved query recipe matched the question",
            )
        if missing:
            return QuerySelection(
                supported=False,
                confidence=confidence,
                reason=f"Required parameter {missing[0]} could not be resolved",
            )
        return validate_selection(
            QuerySelection(
                supported=True,
                recipe_id=recipe.id,
                route=recipe.route,
                parameters=parameters,
                confidence=min(1, confidence + 0.25),
                reason="Matched an approved recipe and resolved typed parameters",
            ),
            spec,
            graph,
        )


@dataclass
class OpenAIPlanner:
    model: str = "gpt-5.6-luna"

    async def select(self, question: str, spec: GraphSpec, graph: GraphIR) -> QuerySelection:
        try:
            from openai import AsyncOpenAI
        except ImportError as error:
            raise RuntimeError("Install the openai optional dependency") from error
        client = AsyncOpenAI()
        schema = QuerySelection.model_json_schema()
        recipes = [
            {
                "id": recipe.id,
                "description": recipe.description,
                "route": recipe.route,
                "parameters": {
                    name: parameter.model_dump(mode="json")
                    for name, parameter in recipe.parameters.items()
                },
                "examples": recipe.examples,
            }
            for recipe in spec.query_recipes
        ]
        response = await client.responses.create(
            model=self.model,
            reasoning={"effort": "none"},
            input=[
                {
                    "role": "developer",
                    "content": (
                        "Select only an approved recipe and extract its typed parameters. "
                        "If the question is unsupported or a required value is missing, "
                        "set supported=false. Never invent identifiers."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"question": question, "recipes": recipes}),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "query_selection",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return validate_selection(
            QuerySelection.model_validate_json(response.output_text),
            spec,
            graph,
        )


@dataclass
class OllamaPlanner:
    model: str = "qwen3:8b"
    base_url: str = "http://127.0.0.1:11434"

    async def select(self, question: str, spec: GraphSpec, graph: GraphIR) -> QuerySelection:
        recipes = [
            {
                "id": recipe.id,
                "description": recipe.description,
                "route": recipe.route,
                "parameters": {
                    name: parameter.model_dump(mode="json")
                    for name, parameter in recipe.parameters.items()
                },
                "examples": recipe.examples,
            }
            for recipe in spec.query_recipes
        ]
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60) as client:
            response = await client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": QuerySelection.model_json_schema(),
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Select only an approved recipe and extract typed parameters. "
                                "Return unsupported rather than inventing a value."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps({"question": question, "recipes": recipes}),
                        },
                    ],
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
        return validate_selection(
            QuerySelection.model_validate_json(response.json()["message"]["content"]),
            spec,
            graph,
        )


def recipe_for(selection: QuerySelection, spec: GraphSpec) -> QueryRecipe | None:
    return next(
        (recipe for recipe in spec.query_recipes if recipe.id == selection.recipe_id),
        None,
    )


def find_candidate(question: str, lookup: Any, graph: GraphIR) -> Any | None:
    if lookup is None:
        return None
    candidates = [
        node.properties.get(lookup.property)
        for node in graph.nodes
        if node.type == lookup.node_type
    ]
    normalized_question = question.casefold()
    question_tokens = tokens(question)
    matches = [
        value
        for value in candidates
        if value is not None
        and (
            (
                len(str(value)) <= 3
                and str(value).casefold() in question_tokens
            )
            or (
                len(str(value)) > 3
                and str(value).casefold() in normalized_question
            )
        )
    ]
    return max(matches, key=lambda value: len(str(value)), default=None)


def validate_selection(
    selection: QuerySelection,
    spec: GraphSpec,
    graph: GraphIR,
) -> QuerySelection:
    if not selection.supported:
        return selection.model_copy(
            update={"recipe_id": None, "route": None, "parameters": {}}
        )
    recipe = recipe_for(selection, spec)
    if not recipe or selection.route != recipe.route:
        return QuerySelection(
            supported=False,
            confidence=selection.confidence,
            reason="The provider selected a recipe or route outside the approved contract",
        )
    unknown = set(selection.parameters) - set(recipe.parameters)
    if unknown:
        return QuerySelection(
            supported=False,
            confidence=selection.confidence,
            reason=f"The provider returned undeclared parameters: {sorted(unknown)}",
        )
    normalized: dict[str, Any] = {}
    for name, parameter in recipe.parameters.items():
        value = selection.parameters.get(name)
        if value is None:
            if parameter.required:
                return QuerySelection(
                    supported=False,
                    confidence=selection.confidence,
                    reason=f"Required parameter {name} was not provided",
                )
            continue
        try:
            normalized[name] = coerce_parameter(value, parameter.type)
        except (TypeError, ValueError):
            return QuerySelection(
                supported=False,
                confidence=selection.confidence,
                reason=f"Parameter {name} did not match its declared type",
            )
        if parameter.candidates:
            candidate = find_candidate(
                str(normalized[name]),
                parameter.candidates,
                graph,
            )
            if candidate is None or str(candidate) != str(normalized[name]):
                return QuerySelection(
                    supported=False,
                    confidence=selection.confidence,
                    reason=f"Parameter {name} is not a source-backed entity value",
                )
    return selection.model_copy(update={"parameters": normalized})


def coerce_parameter(value: Any, kind: str) -> Any:
    if kind == "string":
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError
        return str(value)
    if kind == "integer":
        if isinstance(value, bool):
            raise TypeError
        return int(value)
    if kind == "number":
        if isinstance(value, bool):
            raise TypeError
        return float(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).casefold() in {"true", "false"}:
            return str(value).casefold() == "true"
        raise ValueError
    raise ValueError


def tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(text)
        if token.casefold() not in STOP_WORDS
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0
    return len(left & right) / len(left | right)


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0


def lexical_retrieve(question: str, graph: GraphIR, top_k: int) -> list[dict[str, Any]]:
    query_tokens = tokens(question)
    scored = [
        (jaccard(query_tokens, tokens(chunk.text)), chunk)
        for chunk in graph.corpus
        if chunk.text
    ]
    return [
        {
            "chunk_id": chunk.id,
            "score": round(score, 4),
            "text": chunk.text,
            "provenance": chunk.provenance.model_dump(mode="json"),
        }
        for score, chunk in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
        if score > 0
    ]


def index_namespace(
    *,
    provider: str,
    model: str,
    dimensions: int,
    graph: GraphIR,
) -> str:
    identity = ":".join(
        [
            provider,
            model,
            str(dimensions),
            graph.ontology_hash,
            graph.data_hash,
        ]
    )
    return f"graphkit_{sha256(identity.encode()).hexdigest()[:20]}"


def public_query_payload(
    question: str,
    selection: QuerySelection,
    recipe: QueryRecipe | None,
    graph: GraphIR | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    vector_trace = (
        lexical_retrieve(question, graph, top_k)
        if graph and selection.supported and selection.route in {Route.VECTOR, Route.HYBRID}
        else []
    )
    return {
        "question": question,
        "supported": selection.supported,
        "route": selection.route,
        "recipe_id": selection.recipe_id,
        "parameters": selection.parameters,
        "confidence": selection.confidence,
        "reason": selection.reason,
        "cypher": recipe.cypher if recipe and selection.supported else None,
        "graph_trace": [],
        "vector_trace": vector_trace,
        "timings_ms": {},
        "engine": "offline_preview",
        "answer": None,
        "citations": [item["provenance"] for item in vector_trace],
        "notice": (
            "This local preview planned an approved recipe and used lexical document "
            "retrieval. Connect Neo4j and a certified embedding profile for measured answers."
            if selection.supported
            else "No approved recipe safely supports this question."
        ),
    }
