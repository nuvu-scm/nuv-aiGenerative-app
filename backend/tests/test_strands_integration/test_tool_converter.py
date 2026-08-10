import unittest

from app.agents.tools.agent_tool import ToolRunResult
from app.repositories.models.conversation import (
    ImageToolResultModel,
    JsonToolResultModel,
    RelatedDocumentModel,
)
from app.strands_integration.converters.tool_converter import (
    tool_run_result_to_strands_tool_result,
)


def _json_doc(rank: int) -> RelatedDocumentModel:
    return RelatedDocumentModel(
        content=JsonToolResultModel(
            json={"content": f"chunk {rank}", "source_name": f"doc{rank}.pdf"}
        ),
        source_id=f"tooluse_test@{rank}",
        source_name="knowledge_base_tool",
        page_number=None,
    )


def _image_doc() -> RelatedDocumentModel:
    return RelatedDocumentModel(
        content=ImageToolResultModel(format="png", image=b"fake-image-bytes"),
        source_id="tooluse_test@img",
        source_name="knowledge_base_tool",
        page_number=None,
    )


def _run_result(docs: list[RelatedDocumentModel]) -> ToolRunResult:
    return ToolRunResult(
        tool_use_id="tooluse_test",
        status="success",
        related_documents=docs,
    )


class TestNovaToolResultMerging(unittest.TestCase):
    """Nova models break with multiple content blocks in a toolResult (empty
    answer, hallucinated transcript or invalid-sequence error), so the blocks
    must be merged into a single json block for them."""

    def test_nova_merges_multiple_blocks_into_one(self):
        result = tool_run_result_to_strands_tool_result(
            result=_run_result([_json_doc(0), _json_doc(1)]),
            display_citation=True,
            model_name="amazon-nova-lite",
        )
        self.assertEqual(len(result["content"]), 1)
        results = result["content"][0]["json"]["results"]
        self.assertEqual(len(results), 2)
        # source_id must stay visible so the model can cite [^source_id]
        self.assertEqual(results[0]["source_id"], "tooluse_test@0")
        self.assertEqual(results[1]["source_id"], "tooluse_test@1")

    def test_non_nova_models_keep_separate_blocks(self):
        result = tool_run_result_to_strands_tool_result(
            result=_run_result([_json_doc(0), _json_doc(1)]),
            display_citation=True,
            model_name="claude-v4.5-sonnet",
        )
        self.assertEqual(len(result["content"]), 2)

    def test_no_model_name_keeps_separate_blocks(self):
        result = tool_run_result_to_strands_tool_result(
            result=_run_result([_json_doc(0), _json_doc(1)]),
            display_citation=True,
        )
        self.assertEqual(len(result["content"]), 2)

    def test_nova_single_block_is_not_wrapped(self):
        result = tool_run_result_to_strands_tool_result(
            result=_run_result([_json_doc(0)]),
            display_citation=True,
            model_name="amazon-nova-pro",
        )
        self.assertEqual(len(result["content"]), 1)
        self.assertNotIn("results", result["content"][0]["json"])

    def test_nova_unmergeable_blocks_are_left_untouched(self):
        result = tool_run_result_to_strands_tool_result(
            result=_run_result([_json_doc(0), _image_doc()]),
            display_citation=True,
            model_name="amazon-nova-pro",
        )
        self.assertEqual(len(result["content"]), 2)


if __name__ == "__main__":
    unittest.main()
