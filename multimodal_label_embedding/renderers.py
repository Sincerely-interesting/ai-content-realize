"""Text templates for embedding table rows and query strings."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional


def render_observation_document(row: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "document_type=observation",
            f"asset_id={row.get('asset_id', '')}",
            f"media_type={row.get('media_type', '')}",
            f"has_person={_bool_text(row.get('has_person'))}",
            f"body_parts_visible={_csv(row.get('body_parts_visible'))}",
            f"is_full_body={_bool_text(row.get('is_full_body'))}",
            f"is_half_body={_bool_text(row.get('is_half_body'))}",
            f"is_foot_only={_bool_text(row.get('is_foot_only'))}",
            f"has_motion_sequence={_bool_text(row.get('has_motion_sequence'))}",
            f"motion_signal_strength={row.get('motion_signal_strength', '')}",
            f"motion_keywords={_csv(row.get('motion_keywords'))}",
            f"has_tech_feature={_bool_text(row.get('has_tech_feature'))}",
            f"tech_keywords={_csv(row.get('tech_keywords'))}",
            f"has_celebrity_signal={_bool_text(row.get('has_celebrity_signal'))}",
            f"celebrity_name_hint={row.get('celebrity_name_hint', '')}",
            f"scene_type={row.get('scene_type', '')}",
            f"still_life_style={row.get('still_life_style', '')}",
            f"transcript_summary={row.get('transcript_summary', '')}",
            f"observation_text={row.get('observation_text', '')}",
        ]
    )


def render_rule_card_document(row: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "document_type=rule_card",
            f"rule_id={row.get('rule_id', '')}",
            f"rule_group={row.get('rule_group', '')}",
            f"rule_name={row.get('rule_name', '')}",
            f"rule_type={row.get('rule_type', '')}",
            f"priority={row.get('priority', '')}",
            f"applies_to_media_types={_csv(row.get('applies_to_media_types'))}",
            f"label_target={row.get('label_target', '')}",
            f"label_target_display_name={row.get('label_target_display_name', '')}",
            f"required_all={_csv(row.get('required_all'))}",
            f"required_any={_csv(row.get('required_any'))}",
            f"forbidden_any={_csv(row.get('forbidden_any'))}",
            f"positive_signals={_csv(row.get('positive_signals'))}",
            f"negative_signals={_csv(row.get('negative_signals'))}",
            f"logic_text={row.get('logic_text', '')}",
        ]
    )


def render_sample_memory_document(row: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "document_type=sample_memory",
            f"memory_id={row.get('memory_id', '')}",
            f"asset_id={row.get('asset_id', '')}",
            f"media_type={row.get('media_type', '')}",
            f"label_id={row.get('label_id', '')}",
            f"label_display_name={row.get('label_display_name', '')}",
            f"rule_hits={_csv(row.get('rule_hits'))}",
            f"rule_misses={_csv(row.get('rule_misses'))}",
            f"evidence_positive={_csv(row.get('evidence_positive'))}",
            f"evidence_negative={_csv(row.get('evidence_negative'))}",
            f"normalized_summary={row.get('normalized_summary', '')}",
            f"decision_trace_text={row.get('decision_trace_text', '')}",
        ]
    )


def render_sample_reason_document(row: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "document_type=sample_reason",
            f"asset_id={row.get('asset_id', '')}",
            f"label_id={row.get('label_id', '')}",
            f"label_display_name={row.get('label_display_name', '')}",
            f"rule_hits={_csv(row.get('rule_hits'))}",
            f"rule_misses={_csv(row.get('rule_misses'))}",
            f"decision_trace_text={row.get('decision_trace_text', '')}",
        ]
    )


def render_decision_trace_document(row: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "document_type=decision_trace",
            f"trace_id={row.get('trace_id', '')}",
            f"asset_id={row.get('asset_id', '')}",
            f"final_label_id={row.get('final_label_id', '')}",
            f"final_label_display_name={row.get('final_label_display_name', '')}",
            f"decision_path={_csv(row.get('decision_path'))}",
            f"eliminated_labels={_csv(row.get('eliminated_labels'))}",
            f"primary_evidence={_csv(row.get('primary_evidence'))}",
            f"secondary_evidence={_csv(row.get('secondary_evidence'))}",
            f"conflict_notes={_csv(row.get('conflict_notes'))}",
            f"trace_text={row.get('trace_text', '')}",
        ]
    )


def render_sample_query_text(
    query_text: str,
    *,
    media_type: Optional[str] = None,
    label_id: Optional[str] = None,
    has_person: Optional[bool] = None,
    has_motion_sequence: Optional[bool] = None,
    has_tech_feature: Optional[bool] = None,
    has_celebrity_signal: Optional[bool] = None,
    scene_type: Optional[str] = None,
) -> str:
    parts = [
        "query_type=similar_samples",
        f"query_text={query_text.strip()}",
    ]
    optional_parts = {
        "media_type": media_type,
        "label_id": label_id,
        "has_person": _optional_bool_text(has_person),
        "has_motion_sequence": _optional_bool_text(has_motion_sequence),
        "has_tech_feature": _optional_bool_text(has_tech_feature),
        "has_celebrity_signal": _optional_bool_text(has_celebrity_signal),
        "scene_type": scene_type,
    }
    for key, value in optional_parts.items():
        if value not in {None, ""}:
            parts.append(f"{key}={value}")
    return "\n".join(parts)


def render_rule_query_text(
    query_text: str,
    *,
    media_type: Optional[str] = None,
    label_target: Optional[str] = None,
) -> str:
    parts = [
        "query_type=rule_search",
        f"query_text={query_text.strip()}",
    ]
    if media_type:
        parts.append(f"media_type={media_type}")
    if label_target:
        parts.append(f"label_target={label_target}")
    return "\n".join(parts)


def _csv(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return ",".join(str(item) for item in value)
    return str(value)


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"


def _optional_bool_text(value: Optional[bool]) -> Optional[str]:
    if value is None:
        return None
    return _bool_text(value)
