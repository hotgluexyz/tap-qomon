"""Custom field discovery, schema extension, and record flattening for Qomon."""

from __future__ import annotations

from typing import Any

from hotglue_singer_sdk import typing as th

from tap_qomon.client import QomonStream

PROBE_SCHEMA = {"type": "object", "properties": {}}

CUSTOM_FIELDS_FORM_TYPE = "custom_fields"

FORM_ANSWER_KEYS = ("custom_fields", "formdatas")

FREE_INPUT_FORM_TYPES = frozenset({"text", "numeric", "date"})

MULTI_VALUE_FORM_TYPES = frozenset({"checkbox"})

# Dropped once unfurled. `formdatas` is kept: it also carries non-custom-field
# form answers (consents, level of support, tasks) that nothing else surfaces.
REPLACED_ANSWER_KEYS = ("custom_fields",)

DATE_FORM_TYPES = frozenset({"date"})


def form_type(definition: dict[str, Any]) -> str:
    return str(definition.get("type") or "text").lower()


def definition_label(definition: dict[str, Any]) -> str | None:
    label = definition.get("label") or definition.get("name")
    return str(label) if label else None


def property_type_for(definition: dict[str, Any]) -> Any:
    """Return the JSON schema type a custom field definition unfurls to."""
    definition_type = form_type(definition)
    if definition_type in MULTI_VALUE_FORM_TYPES:
        return th.ArrayType(th.StringType)
    if definition_type in DATE_FORM_TYPES:
        return th.DateTimeType
    return th.StringType


def custom_field_definitions_by_id(
    definitions: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Index custom field form definitions by form id."""
    by_id: dict[int, dict[str, Any]] = {}
    for definition in definitions:
        form_id = definition.get("id")
        if form_id is None:
            continue
        by_id[int(form_id)] = definition
    return by_id


def extend_properties_with_custom_fields(
    properties: list[Any],
    definitions: list[dict[str, Any]],
) -> list[Any]:
    """Append a property per custom field, skipping labels that collide with base fields."""
    extended = list(properties)
    existing_names = {prop.name for prop in extended}
    for definition in definitions:
        label = definition_label(definition)
        if not label or label in existing_names:
            continue
        extended.append(th.Property(label, property_type_for(definition)))
        existing_names.add(label)
    return extended


def fetch_definitions(
    stream: QomonStream,
    form_type_name: str = CUSTOM_FIELDS_FORM_TYPE,
) -> list[dict[str, Any]]:
    """Return custom field form definitions from the Qomon API."""
    payload = stream.request_json(
        "GET",
        f"{stream.url_base}/v1/forms/type/{form_type_name}",
    )
    forms = stream.unwrap_data(payload, "data", "forms")
    if isinstance(forms, list):
        return [form for form in forms if isinstance(form, dict)]
    return []


def _refvalue_label(definition: dict[str, Any], form_ref_id: Any) -> str | None:
    """Return the human readable label of the referenced predefined answer."""
    if form_ref_id is None:
        return None
    for refvalue in definition.get("refvalues") or []:
        if not isinstance(refvalue, dict) or refvalue.get("id") is None:
            continue
        if int(refvalue["id"]) != int(form_ref_id):
            continue
        label = refvalue.get("label")
        return str(label) if label else None
    return None


def answer_value(entry: dict[str, Any], definition: dict[str, Any]) -> str | None:
    """Return the value a single form answer unfurls to."""
    data = entry.get("data")
    if data is None:
        data = entry.get("value")
    if form_type(definition) not in FREE_INPUT_FORM_TYPES:
        label = _refvalue_label(definition, entry.get("form_ref_id"))
        if label:
            return label
    return None if data is None else str(data)


def flatten_custom_fields(
    row: dict[str, Any],
    definitions_by_id: dict[int, dict[str, Any]],
    reserved_names: set,
) -> None:
    """Promote custom field answers to top-level properties keyed by their label."""
    values_by_form_id: dict[int, list[str]] = {}
    for answer_key in FORM_ANSWER_KEYS:
        for entry in row.get(answer_key) or []:
            if not isinstance(entry, dict) or entry.get("form_id") is None:
                continue
            form_id = int(entry["form_id"])
            definition = definitions_by_id.get(form_id)
            if not definition:
                continue
            value = answer_value(entry, definition)
            if value in (None, ""):
                continue
            values_by_form_id.setdefault(form_id, []).append(value)

    for form_id, values in values_by_form_id.items():
        definition = definitions_by_id[form_id]
        label = definition_label(definition)
        if not label or label in reserved_names:
            continue
        if form_type(definition) in MULTI_VALUE_FORM_TYPES:
            row[label] = values
        else:
            row[label] = values[0]

    for answer_key in REPLACED_ANSWER_KEYS:
        row.pop(answer_key, None)
