"""Qomon tap class."""

from __future__ import annotations

from hotglue_singer_sdk import Stream, Tap
from hotglue_singer_sdk import typing as th

from tap_qomon.client import DEFAULT_API_BASE_URL
from tap_qomon.custom_fields import custom_field_definitions_by_id
from tap_qomon.streams import ContactsStream


class TapQomon(Tap):
    """Qomon tap class."""

    name = "tap-qomon"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "api_key",
            th.StringType,
            required=True,
            description="Qomon API key from space settings.",
        ),
        th.Property(
            "api_base_url",
            th.StringType,
            description=(
                "Qomon API base URL. If not provided, the default will be used. "
                f"{DEFAULT_API_BASE_URL}"
            ),
        ),
        th.Property(
            "start_date",
            th.DateTimeType,
            description="Earliest contact UpdatedAt to sync on the first run.",
        ),
    ).to_dict()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.custom_field_definitions_by_id: dict = {}

    def discover_streams(self) -> list[Stream]:
        """Return discovered streams with dynamic custom field schema properties."""
        definitions = ContactsStream.fetch_custom_field_definitions(self)
        self.custom_field_definitions_by_id = custom_field_definitions_by_id(definitions)
        return [
            ContactsStream(
                tap=self,
                schema=ContactsStream.build_schema(definitions),
            )
        ]


if __name__ == "__main__":
    TapQomon.cli()
