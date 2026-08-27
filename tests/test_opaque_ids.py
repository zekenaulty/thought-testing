from __future__ import annotations

import random
import unittest

from thoughtlab.opaque_ids import (
    CROCKFORD_BASE32_ALPHABET,
    OPAQUE_ID_BITS,
    OPAQUE_ID_BODY_LENGTH,
    OPAQUE_ID_PREFIX,
    generate_opaque_id,
    is_opaque_id,
)


class OpaqueIdTests(unittest.TestCase):
    def test_generated_id_has_canonical_type_neutral_form(self) -> None:
        value = generate_opaque_id(rng=random.Random(8675309))
        body = value.removeprefix(OPAQUE_ID_PREFIX)

        self.assertTrue(is_opaque_id(value))
        self.assertEqual(OPAQUE_ID_PREFIX, value[: len(OPAQUE_ID_PREFIX)])
        self.assertEqual(OPAQUE_ID_BODY_LENGTH, len(body))
        self.assertEqual(130, OPAQUE_ID_BITS)
        self.assertTrue(set(body) <= set(CROCKFORD_BASE32_ALPHABET))
        self.assertTrue(set(body).isdisjoint("ILOU"))

    def test_seeded_generation_is_reproducible(self) -> None:
        first = generate_opaque_id(rng=random.Random(42))
        second = generate_opaque_id(rng=random.Random(42))

        self.assertEqual(first, second)

    def test_semantic_prefixes_and_noncanonical_forms_are_rejected(self) -> None:
        valid_body = "7" * OPAQUE_ID_BODY_LENGTH
        alphabetic_body = "A" * OPAQUE_ID_BODY_LENGTH

        self.assertFalse(is_opaque_id(f"PLAN_{valid_body}"))
        self.assertFalse(is_opaque_id(f"FACT_{valid_body}"))
        self.assertFalse(is_opaque_id(f"ID_{alphabetic_body.lower()}"))
        self.assertFalse(is_opaque_id(f"ID_{'I' * OPAQUE_ID_BODY_LENGTH}"))
        self.assertFalse(is_opaque_id(f"ID_{valid_body[:-1]}"))


if __name__ == "__main__":
    unittest.main()
