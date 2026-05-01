"""Unit tests for id_gen helpers."""

from __future__ import annotations

import re
import time

from vagg_license.core.id_gen import new_license_key, uuid7


class TestUUID7:
    def test_version_is_7(self) -> None:
        u = uuid7()
        assert u.version == 7

    def test_variant_is_rfc4122(self) -> None:
        u = uuid7()
        assert u.variant == "specified in RFC 4122"

    def test_time_ordered(self) -> None:
        first = uuid7()
        time.sleep(0.005)
        second = uuid7()
        assert first.bytes < second.bytes

    def test_uniqueness(self) -> None:
        ids = {uuid7() for _ in range(1000)}
        assert len(ids) == 1000


class TestNewLicenseKey:
    def test_format(self) -> None:
        key = new_license_key()
        assert re.fullmatch(r"VAGG-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", key)

    def test_no_ambiguous_chars(self) -> None:
        # 0/O/1/I/L excluded for printability (id_gen._LICENSE_KEY_ALPHABET).
        for _ in range(100):
            key = new_license_key()
            for forbidden in "01IOL":
                assert forbidden not in key.replace("VAGG-", "").replace("-", "")

    def test_uniqueness(self) -> None:
        keys = {new_license_key() for _ in range(1000)}
        assert len(keys) == 1000
