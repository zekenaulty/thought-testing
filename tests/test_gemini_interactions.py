import copy
import unittest

from thoughtlab.gemini_interactions import (
    build_interaction_body,
    output_text,
    response_steps,
    select_steps,
    thought_signature_metadata,
    user_step,
)


class InteractionHelpersTests(unittest.TestCase):
    def test_request_body_is_stateless_and_copies_inputs(self):
        steps = [user_step("hello")]
        config = {
            "thinking_level": "high",
            "thinking_summaries": "none",
            "seed": 123,
        }
        response_format = {"type": "text", "mime_type": "application/json"}

        body = build_interaction_body(
            model="gemini-3.7-flash",
            input_steps=steps,
            generation_config=config,
            response_format=response_format,
        )

        self.assertEqual(body["model"], "gemini-3.7-flash")
        self.assertIs(body["store"], False)
        self.assertIs(body["stream"], False)
        self.assertIs(body["background"], False)
        self.assertNotIn("previous_interaction_id", body)
        self.assertEqual(body["input"], steps)
        steps[0]["content"][0]["text"] = "mutated"
        config["seed"] = 999
        response_format["type"] = "mutated"
        self.assertEqual(body["input"][0]["content"][0]["text"], "hello")
        self.assertEqual(body["generation_config"]["seed"], 123)
        self.assertEqual(body["response_format"]["type"], "text")

    def test_response_steps_preserve_provider_order_and_are_copied(self):
        payload = {
            "steps": [
                {"type": "thought", "signature": "sig-one"},
                {"type": "model_output", "content": "first"},
                {"type": "thought", "signature": "sig-two"},
            ]
        }
        extracted = response_steps(payload)
        self.assertEqual(extracted, payload["steps"])
        extracted[0]["signature"] = "changed"
        self.assertEqual(payload["steps"][0]["signature"], "sig-one")

        thoughts = select_steps(payload["steps"], {"thought"})
        self.assertEqual(
            [step["signature"] for step in thoughts], ["sig-one", "sig-two"]
        )

    def test_response_steps_reject_missing_or_non_object_steps(self):
        with self.assertRaisesRegex(ValueError, "steps array"):
            response_steps({})
        with self.assertRaisesRegex(ValueError, "non-object"):
            response_steps({"steps": [{"type": "thought"}, None]})

    def test_output_text_handles_list_and_string_content(self):
        payload = {
            "steps": [
                {"type": "thought", "signature": "private"},
                {
                    "type": "model_output",
                    "content": [
                        {"type": "text", "text": "  {\"ack\":"},
                        {"type": "ignored", "text": "not included"},
                    ],
                },
                {"type": "model_output", "content": "true}  "},
            ]
        }
        self.assertEqual(output_text(payload), '{"ack":true}')

    def test_signature_metadata_never_contains_raw_signature(self):
        signature = "sensitive-provider-artifact"
        steps = [
            {"type": "thought", "signature": signature},
            {"type": "thought", "signature": ""},
            {"type": "model_output", "content": "ok"},
        ]
        metadata = thought_signature_metadata(steps)
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["signature_chars"], len(signature))
        self.assertNotIn(signature, repr(metadata))


if __name__ == "__main__":
    unittest.main()
