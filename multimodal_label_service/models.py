"""Pydantic request/response models for retrieval service."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    media_type: Optional[Literal["image", "video"]] = None
    label_id: Optional[str] = None
    is_gold_sample: Optional[bool] = None
    bad_case_flag: Optional[bool] = None
    has_person: Optional[bool] = None
    has_motion_sequence: Optional[bool] = None
    has_tech_feature: Optional[bool] = None
    has_celebrity_signal: Optional[bool] = None
    scene_type: Optional[str] = None


class SimilarSamplesRequest(BaseModel):
    query_text: str = Field(..., min_length=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=100)


class RuleSearchRequest(BaseModel):
    query_text: str = Field(..., min_length=1)
    media_type: Optional[Literal["image", "video"]] = None
    label_target: Optional[str] = None
    top_k: int = Field(default=10, ge=1, le=100)


class ExplainRequest(BaseModel):
    asset_id: str


class SearchHit(BaseModel):
    asset_id: Optional[str] = None
    rule_id: Optional[str] = None
    label_id: Optional[str] = None
    label_display_name: Optional[str] = None
    score: Optional[float] = None
    text: Optional[str] = None
    source: str
    metadata: dict = Field(default_factory=dict)


class ExplainResponse(BaseModel):
    asset: dict
    observation: Optional[dict] = None
    sample_memory: Optional[dict] = None
    decision_trace: Optional[dict] = None
    analysis_failure: Optional[dict] = None
    related_rules: List[SearchHit] = Field(default_factory=list)
