"""FastAPI application for LanceDB-backed multimodal label retrieval."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from multimodal_label_store import StoreConfig

from .models import (
    ExplainRequest,
    ExplainResponse,
    RuleSearchRequest,
    SearchHit,
    SimilarSamplesRequest,
)
from .retriever import RetrievalRepository


def create_app(config: StoreConfig | None = None) -> FastAPI:
    app = FastAPI(title="Multimodal Label Retrieval Service", version="0.2.0")
    repo = RetrievalRepository(config)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict:
        readiness = repo.readiness_summary()
        return {"status": "ready", **readiness}

    @app.post("/api/v1/search/similar-samples", response_model=list[SearchHit])
    def similar_samples(req: SimilarSamplesRequest) -> list[SearchHit]:
        rows = repo.search_similar_samples(req.query_text, req.filters, req.top_k)
        return [
            SearchHit(
                asset_id=row.get("asset_id"),
                label_id=row.get("resolved_label_id") or row.get("label_id"),
                label_display_name=row.get("resolved_label_display_name") or row.get("label_display_name"),
                score=_score_from_row(row),
                text=row.get("decision_trace_text") or row.get("normalized_summary"),
                source=row["source"],
                metadata={
                    "rule_hits": row.get("rule_hits", []),
                    "rule_misses": row.get("rule_misses", []),
                    "media_type": row.get("media_type"),
                    "label_state": row.get("label_state"),
                    "failure_code": row.get("failure_code"),
                    "retrieval_channels": row.get("_retrieval_channels", []),
                    "retrieval_detail": row.get("_retrieval_detail", {}),
                },
            )
            for row in rows
        ]

    @app.post("/api/v1/search/rules", response_model=list[SearchHit])
    def search_rules(req: RuleSearchRequest) -> list[SearchHit]:
        rows = repo.search_rules(req.query_text, req.media_type, req.label_target, req.top_k)
        return [
            SearchHit(
                rule_id=row.get("rule_id"),
                label_id=row.get("label_target"),
                label_display_name=row.get("label_target_display_name"),
                score=_score_from_row(row),
                text=row.get("logic_text"),
                source=row["source"],
                metadata={
                    "rule_type": row.get("rule_type"),
                    "priority": row.get("priority"),
                    "applies_to_media_types": row.get("applies_to_media_types", []),
                    "retrieval_channels": row.get("_retrieval_channels", []),
                    "retrieval_detail": row.get("_retrieval_detail", {}),
                },
            )
            for row in rows
        ]

    @app.post("/api/v1/search/explain", response_model=ExplainResponse)
    def explain(req: ExplainRequest) -> ExplainResponse:
        payload = repo.explain_asset(req.asset_id)
        if not payload["asset"]:
            raise HTTPException(status_code=404, detail=f"Asset not found: {req.asset_id}")

        related_rules = []
        sample_memory = payload.get("sample_memory")
        if sample_memory:
            label_id = sample_memory.get("label_id")
            media_type = sample_memory.get("media_type")
            query_text = sample_memory.get("decision_trace_text") or sample_memory.get("normalized_summary") or ""
            if query_text:
                rows = repo.search_rules(query_text, media_type, label_id, top_k=5)
                related_rules = [
                    SearchHit(
                        rule_id=row.get("rule_id"),
                        label_id=row.get("label_target"),
                        label_display_name=row.get("label_target_display_name"),
                        score=_score_from_row(row),
                        text=row.get("logic_text"),
                        source=row["source"],
                        metadata={
                            "rule_type": row.get("rule_type"),
                            "priority": row.get("priority"),
                            "retrieval_channels": row.get("_retrieval_channels", []),
                        },
                    )
                    for row in rows
                ]

        return ExplainResponse(
            asset=payload["asset"],
            observation=payload["observation"],
            sample_memory=payload["sample_memory"],
            decision_trace=payload["decision_trace"],
            analysis_failure=payload["analysis_failure"],
            related_rules=related_rules,
        )

    return app


def _score_from_row(row: dict) -> float | None:
    for key in ("_hybrid_score", "_score", "_relevance_score", "_fallback_score", "_distance"):
        if key in row and row[key] is not None:
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                return None
            if key == "_distance":
                return 1.0 - value
            return value
    return None


app = create_app()
