"""Stream type classes for tap-qomon."""

from __future__ import annotations

from datetime import timezone
from typing import Any, ClassVar

import requests
from hotglue_singer_sdk import Tap
from hotglue_singer_sdk import typing as th

from tap_qomon.client import QomonStream
from tap_qomon.custom_fields import (
    PROBE_SCHEMA,
    extend_properties_with_custom_fields,
    fetch_definitions,
    flatten_custom_fields,
)

# The Qomon search API caps `per_page` at 1000.
MAX_PAGE_SIZE = 1000


class ContactsStream(QomonStream):
    """Contacts stream with dynamically discovered custom field properties.

    Qomon has no contact listing endpoint; contacts are read through the search API
    (`POST /search`), which also drives incremental replication via `UpdatedAt`.
    """

    name = "contacts"
    path = "/search"
    rest_method = "POST"
    records_jsonpath = "$.data.contacts[*]"
    primary_keys: ClassVar[list[str]] = ["id"]
    replication_key = "UpdatedAt"
    page_size = MAX_PAGE_SIZE
    # Search attribute holding the contact's last change date, used to page in a
    # stable order. One of surname, firstname, birthdate, gender, lastchange, mail,
    # married_name, city.
    sort_attr = "lastchange"

    @classmethod
    def base_properties(cls) -> list[Any]:
        return [
            th.Property("id", th.IntegerType),
            th.Property("group_id", th.IntegerType),
            th.Property("CreatedAt", th.DateTimeType),
            th.Property("UpdatedAt", th.DateTimeType),
            th.Property("firstname", th.StringType),
            th.Property("surname", th.StringType),
            th.Property("married_name", th.StringType),
            th.Property("mail", th.StringType),
            th.Property("phone", th.StringType),
            th.Property("phone_invalid", th.BooleanType),
            th.Property("mobile", th.StringType),
            th.Property("mobile_invalid", th.BooleanType),
            th.Property("gender", th.StringType),
            th.Property("birthdate", th.DateTimeType),
            th.Property("age_category", th.IntegerType),
            th.Property("birth_city", th.StringType),
            th.Property("birth_country", th.StringType),
            th.Property("birth_dept", th.StringType),
            th.Property("nationality", th.StringType),
            th.Property("black_list", th.BooleanType),
            th.Property("external_id", th.StringType),
            th.Property("membership_code", th.StringType),
            th.Property("membership_number", th.IntegerType),
            th.Property("nationbuilderid", th.IntegerType),
            th.Property("user_contact_id", th.IntegerType),
            th.Property("lastchange", th.DateTimeType),
            th.Property("lastchangeuserid", th.IntegerType),
            th.Property("action_ids", th.ArrayType(th.IntegerType)),
            th.Property(
                "address",
                th.ObjectType(
                    th.Property("id", th.IntegerType),
                    th.Property("street", th.StringType),
                    th.Property("housenumber", th.StringType),
                    th.Property("addition", th.StringType),
                    th.Property("door", th.StringType),
                    th.Property("floor", th.StringType),
                    th.Property("building", th.StringType),
                    th.Property("building_type", th.StringType),
                    th.Property("city", th.StringType),
                    th.Property("postalcode", th.StringType),
                    th.Property("county", th.StringType),
                    th.Property("state", th.StringType),
                    th.Property("country", th.StringType),
                    th.Property("infos", th.StringType),
                    th.Property("pollingstation", th.StringType),
                    th.Property("latitude", th.StringType),
                    th.Property("longitude", th.StringType),
                    th.Property("location", th.StringType),
                    th.Property("score", th.IntegerType),
                ),
            ),
            th.Property(
                "tags",
                th.ArrayType(th.ObjectType(th.Property("name", th.StringType))),
            ),
            th.Property(
                "custom_fields",
                th.ArrayType(
                    th.ObjectType(
                        th.Property("id", th.IntegerType),
                        th.Property("form_id", th.IntegerType),
                        th.Property("form_ref_id", th.IntegerType),
                        th.Property("data", th.StringType),
                    ),
                ),
            ),
            th.Property(
                "formdatas",
                th.ArrayType(
                    th.ObjectType(
                        th.Property("id", th.IntegerType),
                        th.Property("form_id", th.IntegerType),
                        th.Property("form_ref_id", th.IntegerType),
                        th.Property("contact_id", th.IntegerType),
                        th.Property("group_id", th.IntegerType),
                        th.Property("survey_id", th.IntegerType),
                        th.Property("data", th.StringType),
                        th.Property("date", th.DateTimeType),
                    ),
                ),
            ),
        ]

    @classmethod
    def fetch_custom_field_definitions(cls, tap: Tap) -> list[dict[str, Any]]:
        return fetch_definitions(cls(tap=tap, schema=PROBE_SCHEMA))

    @classmethod
    def build_schema(cls, definitions: list[dict[str, Any]]) -> dict:
        properties = extend_properties_with_custom_fields(
            cls.base_properties(),
            definitions,
        )
        return th.PropertiesList(*properties).to_dict()

    def get_url_params(
        self, context: dict | None, next_page_token: Any | None
    ) -> dict[str, Any]:
        return {}

    def prepare_request_payload(
        self, context: dict | None, next_page_token: Any | None
    ) -> dict | None:
        """Build the advanced search body, filtered from the replication bookmark."""
        conditions: list[dict[str, Any]] = []
        start_timestamp = self.get_starting_timestamp(context)
        if start_timestamp:
            conditions.append(
                {
                    "$condition": {
                        "attr": "UpdatedAt",
                        "ope": "gte",
                        "value": start_timestamp.astimezone(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                        ),
                    },
                },
            )
        return {
            "data": {
                "advanced_search": {
                    "page": next_page_token or 0,
                    "per_page": self.page_size,
                    "sort_attr": self.sort_attr,
                    "sort_asc": True,
                    # The API rejects bare conditions at the top level; they have to
                    # be wrapped in a nested group.
                    "query": {"$all": [{"$all": conditions}] if conditions else []},
                },
            },
        }

    def get_next_page_token(
        self,
        response: requests.Response,
        previous_token: Any | None,
    ) -> Any | None:
        """Page until a short page arrives; the search API returns no total count."""
        contacts = self.unwrap_data(response.json(), "data", "contacts") or []
        if len(contacts) < self.page_size:
            return None
        return (previous_token or 0) + 1

    def post_process(self, row: dict[str, Any], context: dict | None = None) -> dict | None:
        row = super().post_process(row, context)
        if row is None:
            return None
        reserved_names = {prop.name for prop in self.base_properties()}
        flatten_custom_fields(
            row,
            self._tap.custom_field_definitions_by_id,
            reserved_names,
        )
        return row
