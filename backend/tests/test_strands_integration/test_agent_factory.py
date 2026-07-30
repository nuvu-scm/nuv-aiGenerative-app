import unittest
from unittest.mock import patch

from app.bedrock import is_system_prompt_supported
from app.strands_integration.agent.factory import create_strands_agent


class TestSystemPromptSupport(unittest.TestCase):
    def test_mistral_7b_and_mixtral_do_not_support_system_prompts(self):
        self.assertFalse(is_system_prompt_supported("mistral-7b-instruct"))
        self.assertFalse(is_system_prompt_supported("mixtral-8x7b-instruct"))

    def test_other_models_support_system_prompts(self):
        self.assertTrue(is_system_prompt_supported("mistral-large-2"))
        self.assertTrue(is_system_prompt_supported("claude-v3.7-sonnet"))
        self.assertTrue(is_system_prompt_supported("amazon-nova-lite"))


class TestCreateStrandsAgent(unittest.TestCase):
    def _create_agent(self, model_name):
        with (
            patch(
                "app.strands_integration.agent.factory.get_strands_tools",
                return_value=[],
            ),
            patch("app.strands_integration.agent.factory.BedrockModel"),
            patch("app.strands_integration.agent.factory.Agent") as mock_agent,
        ):
            create_strands_agent(
                bot=None,
                instructions=["Eres Nadia.", "Responde en espanol."],
                model_name=model_name,
            )
            return mock_agent.call_args.kwargs

    def test_system_prompt_is_dropped_for_models_without_support(self):
        self.assertIsNone(self._create_agent("mistral-7b-instruct")["system_prompt"])

    def test_system_prompt_is_kept_for_supported_models(self):
        self.assertEqual(
            self._create_agent("claude-v3.7-sonnet")["system_prompt"],
            "Eres Nadia.\n\nResponde en espanol.",
        )


if __name__ == "__main__":
    unittest.main()
