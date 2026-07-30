import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.repositories.models.conversation import SimpleMessageModel, TextContentModel
from app.routes.schemas.conversation import ChatInput, MessageInput, TextContent
from app.strands_integration.chat_strands import converse_with_strands
from app.strands_integration.converters.text_sanitizer import sanitize_agent_text
from app.strands_integration.observability import ObservabilityContext


class _FakeAgent:
    def __init__(self):
        self.callback_handler = None
        self.messages = []
        self.received_messages = None
        self.event_loop_metrics = SimpleNamespace(accumulated_usage={})

    def __call__(self, messages):
        self.received_messages = messages
        self.messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "text": (
                            "<thinking>Buscando informacion.</thinking>\n\n"
                            '<tool_results>{"secret": "internal"}</tool_results>\n\n'
                            "Hola, soy Nadia."
                        )
                    }
                ],
            }
        ]
        return SimpleNamespace(
            stop_reason="end_turn",
            message=self.messages[-1],
            metrics=SimpleNamespace(accumulated_usage={}),
        )


class TestConverseWithStrands(unittest.TestCase):
    @patch("app.strands_integration.chat_strands.complete_observability_context")
    @patch("app.strands_integration.chat_strands.create_strands_agent")
    @patch("app.strands_integration.chat_strands.create_observability_context")
    def test_normal_chat_without_bot_uses_fallback_trace_title(
        self,
        mock_create_observability_context,
        mock_create_strands_agent,
        _mock_complete_observability_context,
    ):
        mock_create_observability_context.return_value = ObservabilityContext(
            logger=None,
            agent_node=None,
        )
        mock_create_strands_agent.return_value = _FakeAgent()

        chat_input = ChatInput(
            conversation_id="conversation-1",
            message=MessageInput(
                role="user",
                content=[
                    TextContent(
                        content_type="text",
                        body="hola",
                    )
                ],
                model="amazon-nova-lite",
                parent_message_id=None,
                message_id=None,
            ),
            bot_id=None,
            continue_generate=False,
            enable_reasoning=False,
        )
        messages = [
            SimpleMessageModel(
                role="user",
                content=[
                    TextContentModel(
                        content_type="text",
                        body="hola",
                    )
                ],
            )
        ]

        result = converse_with_strands(
            bot=None,
            chat_input=chat_input,
            user_msg_id="user-message-1",
            instructions=[],
            generation_params=None,
            guardrail=None,
            display_citation=False,
            messages=messages,
            search_results=[],
        )

        self.assertEqual(result["message"].content[0].body, "Hola, soy Nadia.")
        mock_create_observability_context.assert_called_once()
        self.assertEqual(
            mock_create_observability_context.call_args.kwargs["title"],
            "Nadia",
        )
        self.assertEqual(
            mock_create_observability_context.call_args.kwargs["user_msg_id"],
            "user-message-1",
        )
        self.assertIsNone(mock_create_observability_context.call_args.kwargs["bot_id"])

    @patch("app.strands_integration.chat_strands.complete_observability_context")
    @patch("app.strands_integration.chat_strands.create_strands_agent")
    @patch("app.strands_integration.chat_strands.create_observability_context")
    def test_model_without_system_prompt_support_gets_instructions_in_user_message(
        self,
        mock_create_observability_context,
        mock_create_strands_agent,
        _mock_complete_observability_context,
    ):
        mock_create_observability_context.return_value = ObservabilityContext(
            logger=None,
            agent_node=None,
        )
        fake_agent = _FakeAgent()
        mock_create_strands_agent.return_value = fake_agent

        chat_input = ChatInput(
            conversation_id="conversation-1",
            message=MessageInput(
                role="user",
                content=[
                    TextContent(
                        content_type="text",
                        body="hola",
                    )
                ],
                model="mistral-7b-instruct",
                parent_message_id=None,
                message_id=None,
            ),
            bot_id=None,
            continue_generate=False,
            enable_reasoning=False,
        )
        messages = [
            SimpleMessageModel(
                role="user",
                content=[
                    TextContentModel(
                        content_type="text",
                        body="hola",
                    )
                ],
            )
        ]

        converse_with_strands(
            bot=None,
            chat_input=chat_input,
            user_msg_id="user-message-1",
            instructions=["Eres Nadia.", "Responde en espanol."],
            generation_params=None,
            guardrail=None,
            display_citation=False,
            messages=messages,
            search_results=[],
        )

        first_user_message = fake_agent.received_messages[0]
        self.assertEqual(first_user_message["role"], "user")
        self.assertEqual(
            first_user_message["content"][0],
            {"text": "Eres Nadia.\n\nResponde en espanol."},
        )
        self.assertEqual(first_user_message["content"][1]["text"], "hola")

    def test_agent_thought_keeps_inner_text_without_control_tags(self):
        self.assertEqual(
            sanitize_agent_text(
                "<thinking>I need to retrieve knowledge.</thinking>\n"
                '<tool_results>{"internal": true}</tool_results>'
            ),
            "I need to retrieve knowledge.",
        )


if __name__ == "__main__":
    unittest.main()
