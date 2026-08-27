from __future__ import annotations

import unittest

from thoughtlab.historicalTests.atomic_ground_truth_probe import (
    PARSE_EMPTY_RESPONSE,
    PARSE_INVALID_JSON,
    PARSE_NOT_ATTEMPTED,
    PARSE_VALID,
    exact,
    parse_json_value,
    parsed_value_matches,
    set_equal,
)


class JsonParseScoringTests(unittest.TestCase):
    def test_valid_json_null_is_distinct_from_parse_failure(self) -> None:
        status, value, error = parse_json_value("null")

        self.assertEqual(PARSE_VALID, status)
        self.assertIsNone(value)
        self.assertEqual("", error)
        self.assertTrue(
            parsed_value_matches(
                {"parse_status": status, "parsed": value},
                None,
                exact,
            )
        )

    def test_invalid_json_cannot_match_expected_null(self) -> None:
        status, value, error = parse_json_value("nul")

        self.assertEqual(PARSE_INVALID_JSON, status)
        self.assertIsNone(value)
        self.assertTrue(error)
        self.assertFalse(
            parsed_value_matches(
                {"parse_status": status, "parsed": value},
                None,
                exact,
            )
        )

    def test_invalid_json_cannot_match_expected_empty_set(self) -> None:
        status, value, _ = parse_json_value("not-json")

        self.assertFalse(
            parsed_value_matches(
                {"parse_status": status, "parsed": value},
                [],
                set_equal,
            )
        )

    def test_non_array_json_cannot_match_expected_empty_set(self) -> None:
        for text in ("null", "{}"):
            with self.subTest(text=text):
                status, value, _ = parse_json_value(text)
                self.assertEqual(PARSE_VALID, status)
                self.assertFalse(
                    parsed_value_matches(
                        {"parse_status": status, "parsed": value},
                        [],
                        set_equal,
                    )
                )

    def test_non_string_array_items_cannot_match_string_sets(self) -> None:
        cases = (
            ("[123]", ["123"]),
            ("[true]", ["True"]),
            ("[null]", []),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                status, value, _ = parse_json_value(text)
                self.assertEqual(PARSE_VALID, status)
                self.assertFalse(
                    parsed_value_matches(
                        {"parse_status": status, "parsed": value},
                        expected,
                        set_equal,
                    )
                )

    def test_empty_response_is_not_valid_json_null(self) -> None:
        for text in ("", "   ", "```json\n\n```"):
            with self.subTest(text=text):
                status, value, error = parse_json_value(text)
                self.assertEqual(PARSE_EMPTY_RESPONSE, status)
                self.assertIsNone(value)
                self.assertEqual("", error)

    def test_truncated_json_is_invalid(self) -> None:
        status, value, error = parse_json_value('"unfinished')

        self.assertEqual(PARSE_INVALID_JSON, status)
        self.assertIsNone(value)
        self.assertTrue(error)

    def test_not_attempted_parse_cannot_score(self) -> None:
        self.assertFalse(
            parsed_value_matches(
                {"parse_status": PARSE_NOT_ATTEMPTED, "parsed": None},
                None,
                exact,
            )
        )

    def test_fenced_json_remains_supported(self) -> None:
        status, value, error = parse_json_value("```json\n[]\n```")

        self.assertEqual(PARSE_VALID, status)
        self.assertEqual([], value)
        self.assertEqual("", error)


if __name__ == "__main__":
    unittest.main()
