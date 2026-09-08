"""Tests standard tap features using the built-in SDK tests library."""

import json
import os
from unittest.mock import Mock

import pytest
from hotglue_singer_sdk.testing import get_standard_tap_tests

from tap_qomon.tap import TapQomon

_SECRETS_CONFIG = os.path.join(os.path.dirname(__file__), "../../.secrets/config.json")


@pytest.fixture
def sample_config():
    if not os.path.exists(_SECRETS_CONFIG):
        pytest.skip("Secrets file not found; skipping integration tests.")
    with open(_SECRETS_CONFIG) as config_file:
        return json.load(config_file)


@pytest.fixture
def discovered_stream(sample_config):
    return TapQomon(config=sample_config).discover_streams()[0]


def test_standard_tap_tests(sample_config):
    tests = get_standard_tap_tests(TapQomon, config=sample_config)
    for test in tests:
        test()


def test_discovered_schema_includes_custom_fields(sample_config):
    tap = TapQomon(config=sample_config)
    stream = tap.discover_streams()[0]

    definitions = tap.custom_field_definitions_by_id.values()
    labels = {definition["label"] for definition in definitions if definition.get("label")}

    assert labels, "Expected at least one custom field definition in the test space"
    assert labels.issubset(stream.schema["properties"])


def test_contacts_records_unfurl_custom_fields(discovered_stream):
    records = list(discovered_stream.get_records(None))
    record_ids = [record["id"] for record in records]

    assert records
    assert len(record_ids) == len(set(record_ids))

    labels = {
        definition["label"]
        for definition in discovered_stream._tap.custom_field_definitions_by_id.values()
        if definition.get("label")
    }
    unfurled = [record for record in records if labels & set(record)]

    assert unfurled, "Expected at least one contact with a custom field value"


def test_contacts_pagination(discovered_stream):
    discovered_stream.page_size = 1

    records = list(discovered_stream.get_records(None))
    record_ids = [record["id"] for record in records]

    assert len(records) > 1
    assert len(record_ids) == len(set(record_ids))


def test_request_payload_without_bookmark_has_no_filter(discovered_stream):
    payload = discovered_stream.prepare_request_payload(None, None)
    advanced_search = payload["data"]["advanced_search"]

    assert advanced_search["page"] == 0
    assert advanced_search["per_page"] == discovered_stream.page_size
    assert advanced_search["query"] == {"$all": []}


def test_get_next_page_token_increments_until_short_page(discovered_stream):
    discovered_stream.page_size = 2
    full_page = Mock()
    full_page.json.return_value = {"data": {"contacts": [{"id": 1}, {"id": 2}]}}
    short_page = Mock()
    short_page.json.return_value = {"data": {"contacts": [{"id": 3}]}}

    assert discovered_stream.get_next_page_token(full_page, None) == 1
    assert discovered_stream.get_next_page_token(full_page, 1) == 2
    assert discovered_stream.get_next_page_token(short_page, 2) is None


def test_request_payload_filters_on_replication_bookmark(discovered_stream):
    discovered_stream.stream_state["replication_key"] = "UpdatedAt"
    discovered_stream.stream_state["replication_key_value"] = "2026-01-02T03:04:05Z"
    # Promotes the bookmark to the starting value the SDK reads during a sync.
    discovered_stream._write_starting_replication_value(None)

    payload = discovered_stream.prepare_request_payload(None, 3)
    advanced_search = payload["data"]["advanced_search"]

    assert advanced_search["page"] == 3
    assert advanced_search["query"] == {
        "$all": [
            {
                "$all": [
                    {
                        "$condition": {
                            "attr": "UpdatedAt",
                            "ope": "gte",
                            "value": "2026-01-02T03:04:05Z",
                        },
                    },
                ],
            },
        ],
    }


def test_invalid_credentials_raise_credential_error(sample_config):
    from hotglue_etl_exceptions import InvalidCredentialsError

    tap = TapQomon(config={**sample_config, "api_key": "not-a-real-key"})

    with pytest.raises(InvalidCredentialsError):
        tap.discover_streams()


def test_custom_field_unfurling_skips_reserved_labels_and_groups_multi_values():
    from tap_qomon.custom_fields import (
        custom_field_definitions_by_id,
        extend_properties_with_custom_fields,
        flatten_custom_fields,
    )
    from tap_qomon.streams import ContactsStream

    base_properties = ContactsStream.base_properties()
    reserved_names = {prop.name for prop in base_properties}
    definitions = [
        {"id": 1, "label": "mail", "type": "text", "refvalues": [{"id": 11}]},
        {"id": 2, "label": "Job", "type": "text", "refvalues": [{"id": 21}]},
        {
            "id": 3,
            "label": "Interests",
            "type": "checkbox",
            "refvalues": [
                {"id": 31, "label": "Climate", "value": "climate"},
                {"id": 32, "label": "Housing", "value": "housing"},
            ],
        },
    ]

    extended = extend_properties_with_custom_fields(base_properties, definitions)
    property_names = {prop.name for prop in extended}

    # "mail" collides with a base contact field, so it does not add a property.
    assert property_names == reserved_names | {"Job", "Interests"}

    row = {
        "mail": "standard@hotglue.test",
        "custom_fields": [
            {"form_id": 1, "form_ref_id": 11, "data": "custom@hotglue.test"},
            {"form_id": 2, "form_ref_id": 21, "data": "Data Engineer"},
        ],
        "formdatas": [
            {"form_id": 3, "form_ref_id": 31, "data": "climate"},
            {"form_id": 3, "form_ref_id": 32, "data": "housing"},
        ],
    }
    flatten_custom_fields(row, custom_field_definitions_by_id(definitions), reserved_names)

    assert row["mail"] == "standard@hotglue.test"
    assert row["Job"] == "Data Engineer"
    # Predefined answers unfurl to their readable label, not the stored slug.
    assert row["Interests"] == ["Climate", "Housing"]
