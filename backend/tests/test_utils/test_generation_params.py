import unittest

from app.bedrock import generation_params_to_converse_configuration
from app.repositories.models.custom_bot import GenerationParamsModel


class TestAdditionalModelRequestFields(unittest.TestCase):
    """Each model family names top_k differently in additionalModelRequestFields.

    Verified against Bedrock: Mistral rejects `topK` with
    "Validation Error: ... topK Extra inputs are not permitted".
    """

    MISTRAL_MODELS = ["mistral-7b-instruct", "mixtral-8x7b-instruct", "mistral-large"]

    def setUp(self):
        self.params = GenerationParamsModel(top_k=128)

    def _additional_fields(self, model):
        return generation_params_to_converse_configuration(
            model=model,
            generation_params=self.params,
        ).get("additionalModelRequestFields")

    def test_mistral_uses_snake_case_top_k(self):
        for model in self.MISTRAL_MODELS:
            with self.subTest(model=model):
                self.assertEqual(self._additional_fields(model), {"top_k": 128})

    def test_mistral_caps_top_k_at_200(self):
        # 250 is the app-wide default and is out of Mistral's 1..200 range
        self.params = GenerationParamsModel(top_k=250)
        for model in self.MISTRAL_MODELS:
            with self.subTest(model=model):
                self.assertEqual(self._additional_fields(model), {"top_k": 200})

    def test_mistral_omits_top_k_when_below_one(self):
        self.params = GenerationParamsModel(top_k=0)
        for model in self.MISTRAL_MODELS:
            with self.subTest(model=model):
                self.assertIsNone(self._additional_fields(model))

    def test_anthropic_uses_snake_case_top_k(self):
        self.assertEqual(
            self._additional_fields("claude-v3.5-sonnet"),
            {"top_k": 128},
        )

    def test_nova_nests_camel_case_top_k_under_inference_config(self):
        self.assertEqual(
            self._additional_fields("amazon-nova-lite"),
            {"inferenceConfig": {"topK": 128}},
        )


if __name__ == "__main__":
    unittest.main()
