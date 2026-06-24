"""High-level retrieval helpers built on top of LanceDB tables."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional

from multimodal_label_embedding import (
    EmbeddingProviderSettings,
    create_embedding_provider,
    provider_settings_from_env,
    render_rule_query_text,
    render_sample_query_text,
)
from multimodal_label_store import LanceStore, StoreConfig

from .models import SearchFilters


class RetrievalRepository:
    def __init__(
        self,
        config: StoreConfig | None = None,
        provider_settings: EmbeddingProviderSettings | None = None,
    ):
        self.store = LanceStore(config or StoreConfig())
        self.store.ensure_all_tables()
        provider_settings = provider_settings or provider_settings_from_env(
            dim=self.store.config.embedding_dim
        )
        self.embedder = create_embedding_provider(provider_settings)

    def search_similar_samples(
        self,
        query_text: str,
        filters: SearchFilters,
        top_k: int,
    ) -> List[dict]:
        query_embedding_text = render_sample_query_text(
            query_text,
            media_type=filters.media_type,
            label_id=filters.label_id,
            has_person=filters.has_person,
            has_motion_sequence=filters.has_motion_sequence,
            has_tech_feature=filters.has_tech_feature,
            has_celebrity_signal=filters.has_celebrity_signal,
            scene_type=filters.scene_type,
        )
        rows = self._hybrid_query(
            table_name="sample_memories",
            query_text=query_text,
            query_embedding_text=query_embedding_text,
            top_k=top_k,
            id_field="memory_id",
            where_expr=self._sample_filter_expression(filters),
            text_fields=["normalized_summary", "decision_trace_text"],
            vector_columns=[
                ("sample_embedding", 0.25),
                ("reason_embedding", 0.2),
            ],
            fts_weight=1.0,
            keyword_weight=0.7,
        )
        observation_map = {
            row["asset_id"]: row
            for row in self.store.load_rows("observations")
        }
        rows = self._rerank_sample_rows(
            query_text=query_text,
            rows=rows,
            filters=filters,
            observation_map=observation_map,
        )
        if self._has_observation_filters(filters):
            rows = [
                row
                for row in rows
                if self._matches_observation_filters(
                    observation_map.get(str(row.get("asset_id", ""))),
                    filters,
                )
            ]

        result = []
        for row in rows[:top_k]:
            row = self._public_row(row)
            row["source"] = "sample_memories"
            result.append(row)
        return result

    def search_rules(
        self,
        query_text: str,
        media_type: Optional[str],
        label_target: Optional[str],
        top_k: int,
    ) -> List[dict]:
        clauses = []
        if media_type:
            clauses.append(f"array_contains(applies_to_media_types, '{media_type}')")
        if label_target:
            clauses.append(f"label_target = '{label_target}'")

        rows = self._hybrid_query(
            table_name="rule_cards",
            query_text=query_text,
            query_embedding_text=render_rule_query_text(
                query_text,
                media_type=media_type,
                label_target=label_target,
            ),
            top_k=top_k,
            id_field="rule_id",
            where_expr=" AND ".join(clauses) if clauses else None,
            text_fields=["logic_text"],
            vector_columns=[("rule_embedding", 0.55)],
            fts_weight=0.9,
            keyword_weight=0.6,
        )
        result = []
        for row in rows[:top_k]:
            row = self._public_row(row)
            row["source"] = "rule_cards"
            result.append(row)
        return result

    def explain_asset(self, asset_id: str) -> Dict[str, Optional[dict]]:
        asset = self._one_or_none("assets", f"asset_id = '{asset_id}'")
        observation = self._one_or_none("observations", f"asset_id = '{asset_id}'")
        memory = self._one_or_none("sample_memories", f"asset_id = '{asset_id}'")
        trace = self._one_or_none("decision_traces", f"asset_id = '{asset_id}'")
        analysis_failure = self._one_or_none("analysis_failures", f"asset_id = '{asset_id}'")
        return {
            "asset": asset,
            "observation": observation,
            "sample_memory": memory,
            "decision_trace": trace,
            "analysis_failure": analysis_failure,
        }

    def readiness_summary(self) -> dict:
        table_names = [
            "assets",
            "observations",
            "rule_cards",
            "sample_memories",
            "decision_traces",
            "analysis_failures",
        ]
        embedding_tables = {"observations", "rule_cards", "sample_memories", "decision_traces"}
        tables = {}
        for table_name in table_names:
            row_count = self.store.count_rows(table_name)
            status_summary = self.store.embedding_status_summary(table_name) if table_name in embedding_tables else {}
            ready_count = sum(
                count
                for status, count in status_summary.items()
                if str(status).startswith("ready")
            )
            tables[table_name] = {
                "row_count": row_count,
                "embedding_status": status_summary,
                "embedding_ready": (
                    row_count == 0 or ready_count == row_count
                    if table_name in embedding_tables
                    else True
                ),
                "embedding_applicable": table_name in embedding_tables,
            }
        return {
            "provider": {
                "name": self.embedder.name,
                "version": self.embedder.version,
                "dim": self.embedder.dim,
            },
            "tables": tables,
        }

    def _hybrid_query(
        self,
        *,
        table_name: str,
        query_text: str,
        query_embedding_text: str,
        top_k: int,
        id_field: str,
        where_expr: Optional[str],
        text_fields: List[str],
        vector_columns: List[tuple[str, float]],
        fts_weight: float,
        keyword_weight: float,
    ) -> List[dict]:
        table = self.store.open_table(table_name)
        candidate_k = max(top_k * 8, 40)
        channels: List[tuple[str, float, List[dict]]] = []

        if self._table_embeddings_ready(table_name):
            query_vector = self.embedder.embed_text(query_embedding_text)
            for vector_column, weight in vector_columns:
                rows = self._vector_query(
                    table,
                    query_vector=query_vector,
                    vector_column=vector_column,
                    top_k=candidate_k,
                    where_expr=where_expr,
                )
                if rows:
                    channels.append((f"vector:{vector_column}", weight, rows))

        fts_rows = self._fts_query(
            table,
            query_text=query_text,
            top_k=candidate_k,
            where_expr=where_expr,
            text_fields=text_fields,
        )
        if fts_rows:
            channels.append(("fts", fts_weight, fts_rows))
        else:
            keyword_rows = self._fallback_keyword_search(
                table.to_arrow().to_pylist(),
                query_text=query_text,
                top_k=candidate_k,
                where_expr=where_expr,
                text_fields=text_fields,
            )
            if keyword_rows:
                channels.append(("keyword", keyword_weight, keyword_rows))

        if not channels:
            return []

        fused: Dict[str, dict] = {}
        rrf_k = 60.0
        for channel_name, channel_weight, rows in channels:
            for rank, row in enumerate(rows, start=1):
                row_id = str(row.get(id_field, ""))
                if not row_id:
                    continue

                entry = fused.setdefault(
                    row_id,
                    {
                        "row": dict(row),
                        "hybrid_score": 0.0,
                        "channels": {},
                        "best_rank": rank,
                    },
                )
                if rank < entry["best_rank"]:
                    entry["row"] = dict(row)
                    entry["best_rank"] = rank
                entry["hybrid_score"] += channel_weight * (1.0 / (rrf_k + rank))
                entry["channels"][channel_name] = {"rank": rank}

        merged_rows: List[dict] = []
        for entry in fused.values():
            row = dict(entry["row"])
            row["_hybrid_score"] = float(entry["hybrid_score"])
            row["_retrieval_channels"] = sorted(entry["channels"])
            row["_retrieval_detail"] = entry["channels"]
            merged_rows.append(row)

        merged_rows.sort(
            key=lambda row: (
                float(row.get("_hybrid_score", 0.0)),
                float(row.get("quality_score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return merged_rows

    def _sample_filter_expression(self, filters: SearchFilters) -> Optional[str]:
        clauses: List[str] = []
        if filters.media_type:
            clauses.append(f"media_type = '{filters.media_type}'")
        if filters.label_id:
            clauses.append(f"semantic_label_id = '{filters.label_id}'")
        if filters.is_gold_sample is not None:
            clauses.append(f"is_gold_sample = {str(filters.is_gold_sample).lower()}")
        if filters.bad_case_flag is not None:
            clauses.append(f"bad_case_flag = {str(filters.bad_case_flag).lower()}")
        return " AND ".join(clauses) if clauses else None

    def _rerank_sample_rows(
        self,
        *,
        query_text: str,
        rows: List[dict],
        filters: SearchFilters,
        observation_map: Mapping[str, Mapping[str, object]],
    ) -> List[dict]:
        hints = self._extract_query_hints(query_text)
        reranked: List[dict] = []
        for row in rows:
            asset_id = str(row.get("asset_id", "") or "")
            observation = observation_map.get(asset_id)
            score = float(row.get("_hybrid_score", 0.0) or 0.0)
            score += self._sample_rerank_bonus(
                query_text=query_text,
                hints=hints,
                row=row,
                observation=observation,
                filters=filters,
            )
            reranked_row = dict(row)
            reranked_row["_rerank_score"] = score
            reranked.append(reranked_row)

        reranked.sort(
            key=lambda row: (
                float(row.get("_rerank_score", 0.0)),
                float(row.get("_hybrid_score", 0.0)),
                float(row.get("quality_score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return reranked

    def _sample_rerank_bonus(
        self,
        *,
        query_text: str,
        hints: dict,
        row: Mapping[str, object],
        observation: Mapping[str, object] | None,
        filters: SearchFilters,
    ) -> float:
        bonus = 0.0
        label_id = str(row.get("resolved_label_id", "") or row.get("semantic_label_id", "") or row.get("label_id", "") or "")
        label_name = str(row.get("resolved_label_display_name", "") or row.get("semantic_label_display_name", "") or row.get("label_display_name", "") or "")
        haystack = "\n".join(
            [
                str(row.get("normalized_summary", "") or ""),
                str(row.get("decision_trace_text", "") or ""),
                str(label_name),
                str(label_id),
            ]
        ).lower()

        if filters.label_id and label_id == filters.label_id:
            bonus += 0.12
        if label_name and label_name in query_text:
            bonus += 0.10
        if label_id and label_id in query_text:
            bonus += 0.08

        lexical_hits = sum(1 for token in hints["lexical_terms"] if token and token in haystack)
        bonus += min(0.18, lexical_hits * 0.02)
        row_signatures = self._extract_row_signatures(row, observation)
        signature_hits = len(row_signatures & hints["signature_terms"])
        bonus += min(0.20, signature_hits * 0.05)
        row_celebrity_names = row_signatures & hints["known_celebrity_terms"]
        celebrity_overlap = len(row_celebrity_names & hints["celebrity_names"])
        bonus += min(0.18, celebrity_overlap * 0.08)

        if observation:
            body_parts = {str(item) for item in self._as_string_list(observation.get("body_parts_visible"))}
            scene_type = str(observation.get("scene_type", "") or "")
            still_life_style = str(observation.get("still_life_style", "") or "")
            celebrity_name = str(observation.get("celebrity_name_hint", "") or "")
            tech_keywords = {str(item) for item in self._as_string_list(observation.get("tech_keywords"))}
            motion_keywords = {str(item) for item in self._as_string_list(observation.get("motion_keywords"))}
            is_full_body = bool(observation.get("is_full_body"))
            is_foot_only = bool(observation.get("is_foot_only"))
            has_person = observation.get("has_person") is True

            if hints["wants_celebrity"] and bool(observation.get("has_celebrity_signal")):
                bonus += 0.08
            if hints["celebrity_names"] and celebrity_name and celebrity_name in hints["celebrity_names"]:
                bonus += 0.16
            if hints["celebrity_names"] and celebrity_name and celebrity_name not in hints["celebrity_names"]:
                bonus -= 0.08
            if hints["celebrity_names"] and row_celebrity_names and row_celebrity_names.isdisjoint(hints["celebrity_names"]):
                bonus -= 0.14
            if hints["wants_full_body"] and (is_full_body or {"head", "torso", "foot"}.issubset(body_parts)):
                bonus += 0.10
            if hints["wants_full_body"] and is_foot_only:
                bonus -= 0.16
            if hints["wants_on_foot"] and (is_foot_only or {"leg", "foot"} & body_parts):
                bonus += 0.14
            if hints["wants_on_foot"] and is_full_body:
                bonus -= 0.18
            if hints["scene_terms"] and scene_type and scene_type in hints["scene_terms"]:
                bonus += 0.08
            if hints["style_terms"] and still_life_style and still_life_style in hints["style_terms"]:
                bonus += 0.08
            if hints["tech_terms"] and tech_keywords & hints["tech_terms"]:
                bonus += 0.08
            if hints["motion_terms"] and motion_keywords & hints["motion_terms"]:
                bonus += 0.08
            if hints["wants_no_person"] and observation.get("has_person") is False:
                bonus += 0.08
            if hints["wants_no_person"] and has_person:
                bonus -= 0.16

        if label_id == "on_foot_only" and hints["wants_on_foot"]:
            bonus += 0.08
        if label_id != "on_foot_only" and hints["wants_on_foot"] and label_id in {"outfit_core", "celebrity_outfit"}:
            bonus -= 0.12
        if label_id == "outfit_core" and hints["wants_full_body"]:
            bonus += 0.08
        if label_id == "on_foot_only" and hints["wants_full_body"]:
            bonus -= 0.12
        if label_id == "creative_still_life" and hints["wants_creative_still_life"]:
            bonus += 0.08
        if label_id == "celebrity_outfit" and hints["wants_celebrity"]:
            bonus += 0.08
        return bonus

    def _extract_query_hints(self, query_text: str) -> dict:
        text = query_text.strip()
        lower = text.lower()
        tokens = self._query_tokens(text)
        lexical_terms = self._lexical_terms(text)
        celebrity_names = {
            name
            for name in [
                "王一博",
                "王俊凯",
                "李现",
                "林一",
                "赵露思",
                "张天爱",
                "Hoshi",
                "SEVENTEEN",
                "Wonbin",
                "Sunoo",
                "李现",
                "王俊凯",
            ]
            if name.lower() in lower or name in text
        }
        signature_terms = self._signature_terms_from_text(text)
        scene_terms = set()
        if "street" in lower or "街拍" in text or "斑马线" in text:
            scene_terms.add("street")
        if "creative_set" in lower or "创意" in text or "霓虹" in text or "赛博朋克" in text or "圣诞" in text:
            scene_terms.add("creative_set")
        if "plain_background" in lower or "纯背景" in text:
            scene_terms.add("plain_background")
        style_terms = set()
        if "artistic" in lower or "艺术" in text:
            style_terms.add("artistic")
        if "creative" in lower or "创意" in text:
            style_terms.add("creative")
        if "plain" in lower or "简洁" in text:
            style_terms.add("plain")
        tech_terms = {token for token in tokens if token in {"科技点", "zoomx", "中底", "碳板", "boost", "react"}}
        motion_terms = {token for token in tokens if token in {"连续运动", "奔跑", "起跳", "急停", "变向"}}
        return {
            "tokens": tokens,
            "lexical_terms": lexical_terms,
            "celebrity_names": celebrity_names,
            "known_celebrity_terms": {
                "王一博",
                "王俊凯",
                "李现",
                "林一",
                "赵露思",
                "张天爱",
                "Hoshi",
                "Sunoo",
                "Wonbin",
                "IU",
                "Karina",
                "Hanni",
                "BoA",
                "Momo",
                "金珉周",
                "郑恩地",
            },
            "signature_terms": signature_terms,
            "scene_terms": scene_terms,
            "style_terms": style_terms,
            "tech_terms": tech_terms,
            "motion_terms": motion_terms,
            "wants_celebrity": ("明星" in text or "celebrity" in lower),
            "wants_full_body": any(term in text for term in ["全身", "头部", "躯干", "穿搭种草", "OOTD"]),
            "wants_on_foot": any(term in text for term in ["膝盖以下", "脚部", "上脚", "鞋履展示", "小腿"]),
            "wants_no_person": any(term in text for term in ["无人物", "无人", "静物"]),
            "wants_creative_still_life": any(term in text for term in ["创意静物", "艺术置景", "霓虹", "赛博朋克", "圣诞"]),
        }

    def _extract_row_signatures(
        self,
        row: Mapping[str, object],
        observation: Mapping[str, object] | None,
    ) -> set[str]:
        text = "\n".join(
            [
                str(row.get("decision_trace_text", "") or ""),
                str(row.get("normalized_summary", "") or ""),
            ]
        )
        signatures = self._signature_terms_from_text(text)
        if observation:
            celebrity_name = str(observation.get("celebrity_name_hint", "") or "").strip()
            if celebrity_name:
                signatures.add(celebrity_name)
            scene_type = str(observation.get("scene_type", "") or "").strip()
            if scene_type and scene_type != "unknown":
                signatures.add(scene_type)
            still_life_style = str(observation.get("still_life_style", "") or "").strip()
            if still_life_style and still_life_style != "unknown":
                signatures.add(still_life_style)
            if bool(observation.get("is_foot_only")):
                signatures.update({"膝盖以下", "上脚", "脚部"})
            if bool(observation.get("is_full_body")):
                signatures.update({"全身", "完整全身"})
        return signatures

    def _has_observation_filters(self, filters: SearchFilters) -> bool:
        return any(
            value is not None
            for value in [
                filters.has_person,
                filters.has_motion_sequence,
                filters.has_tech_feature,
                filters.has_celebrity_signal,
                filters.scene_type,
            ]
        )

    def _matches_observation_filters(
        self,
        observation: Optional[Mapping[str, object]],
        filters: SearchFilters,
    ) -> bool:
        if observation is None:
            return False
        checks = {
            "has_person": filters.has_person,
            "has_motion_sequence": filters.has_motion_sequence,
            "has_tech_feature": filters.has_tech_feature,
            "has_celebrity_signal": filters.has_celebrity_signal,
            "scene_type": filters.scene_type,
        }
        for field, expected in checks.items():
            if expected is None:
                continue
            if observation.get(field) != expected:
                return False
        return True

    def _one_or_none(self, table_name: str, where_expr: str) -> Optional[dict]:
        table = self.store.open_table(table_name)
        rows = table.to_arrow().to_pylist()
        matched = [self._public_row(row) for row in rows if self._matches_where_expr(row, where_expr)]
        return matched[0] if matched else None

    def _vector_query(
        self,
        table,
        *,
        query_vector: List[float],
        vector_column: str,
        top_k: int,
        where_expr: Optional[str],
    ) -> List[dict]:
        try:
            query = table.search(query_vector, vector_column_name=vector_column).distance_type("cosine")
            if where_expr:
                query = query.where(where_expr)
            return query.limit(top_k).to_list()
        except Exception:
            return []

    def _fts_query(
        self,
        table,
        *,
        query_text: str,
        top_k: int,
        where_expr: Optional[str],
        text_fields: List[str],
    ) -> List[dict]:
        try:
            query = table.search(
                query_text,
                query_type="fts",
                fts_columns=text_fields,
            )
            if where_expr:
                query = query.where(where_expr)
            return query.limit(top_k).to_list()
        except Exception:
            return []

    def _fallback_keyword_search(
        self,
        rows: Iterable[dict],
        *,
        query_text: str,
        top_k: int,
        where_expr: Optional[str],
        text_fields: List[str],
    ) -> List[dict]:
        tokens = self._query_tokens(query_text)
        if not tokens:
            return []

        scored: List[tuple[int, dict]] = []
        for row in rows:
            if where_expr and not self._matches_where_expr(row, where_expr):
                continue
            haystack = "\n".join(str(row.get(field, "") or "") for field in text_fields).lower()
            score = sum(1 for token in tokens if token and token in haystack)
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        result = []
        for score, row in scored[:top_k]:
            public_row = dict(row)
            public_row["_fallback_score"] = float(score)
            result.append(public_row)
        return result

    def _query_tokens(self, query_text: str) -> List[str]:
        lowered = query_text.lower().strip()
        if not lowered:
            return []

        pieces = re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]+", lowered)
        tokens = set(pieces)
        compact = re.sub(r"\s+", "", lowered)
        for size in (2, 3):
            if len(compact) < size:
                continue
            for idx in range(0, len(compact) - size + 1):
                tokens.add(compact[idx : idx + size])
        return sorted(token for token in tokens if token)

    def _lexical_terms(self, query_text: str) -> List[str]:
        lowered = query_text.lower().strip()
        if not lowered:
            return []
        pieces = re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]{2,}", lowered)
        stop_terms = {
            "query_type",
            "similar_samples",
            "image",
            "video",
            "label_id",
            "media_type",
        }
        return sorted({piece for piece in pieces if piece and piece not in stop_terms})

    def _signature_terms_from_text(self, text: str) -> set[str]:
        lower = text.lower()
        signatures = set()
        known_terms = [
            "赵露思",
            "张天爱",
            "王一博",
            "王俊凯",
            "李现",
            "林一",
            "Hoshi",
            "Sunoo",
            "Wonbin",
            "街拍",
            "写真",
            "生活方式",
            "膝盖以下",
            "脚部",
            "上脚",
            "全身",
            "完整全身",
            "霓虹",
            "赛博朋克",
            "圣诞",
            "创意",
            "艺术",
            "开箱",
            "静物",
            "creative_set",
            "artistic",
            "plain_background",
        ]
        for term in known_terms:
            if term.lower() in lower or term in text:
                signatures.add(term)
        return signatures

    def _as_string_list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _table_embeddings_ready(self, table_name: str) -> bool:
        summary = self.store.embedding_status_summary(table_name)
        total = sum(summary.values())
        if total == 0:
            return False
        ready = sum(count for status, count in summary.items() if str(status).startswith("ready"))
        return ready == total

    def _public_row(self, row: Mapping[str, object]) -> dict:
        public = {
            key: value
            for key, value in row.items()
            if not key.endswith("_embedding")
        }
        if public.get("semantic_label_id"):
            public["resolved_label_id"] = public.get("semantic_label_id")
            public["resolved_label_display_name"] = public.get("semantic_label_display_name")
        else:
            public["resolved_label_id"] = public.get("label_id") or public.get("final_label_id")
            public["resolved_label_display_name"] = (
                public.get("label_display_name") or public.get("final_label_display_name")
            )
        return public

    def _matches_where_expr(self, row: Mapping[str, object], where_expr: str) -> bool:
        clauses = [clause.strip() for clause in where_expr.split(" AND ") if clause.strip()]
        for clause in clauses:
            if clause.startswith("array_contains("):
                left, right = clause[len("array_contains(") :].split(")", 1)[0].split(",", 1)
                field = left.strip()
                expected = right.strip().strip("'\" ")
                raw_values = row.get(field, []) or []
                values = raw_values if isinstance(raw_values, list) else [raw_values]
                if expected not in values:
                    return False
                continue

            if " = " in clause:
                field, value = clause.split(" = ", 1)
                field = field.strip()
                value = value.strip()
                if value in {"true", "false"}:
                    expected = value == "true"
                else:
                    expected = value.strip("'\"")
                if row.get(field) != expected:
                    return False
                continue
        return True
