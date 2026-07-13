import unittest

from langchain_core.documents import Document

from main import _verify_citations, strip_reasoning_tokens


class Phase3GroundingTests(unittest.TestCase):
    def test_strip_reasoning_tokens_removes_reasoning_blocks(self):
        text = "Final answer<think>hidden</think> here"
        self.assertEqual(strip_reasoning_tokens(text), "Final answer here")

    def test_grounding_prompt_requires_citations_and_fallback(self):
        from prompt_library.prompt import PROMPT_TEMPLATES
        prompt = PROMPT_TEMPLATES["product_bot"]
        self.assertIn("citation", prompt.lower())
        self.assertIn("insufficient context", prompt.lower())

    def test_grounding_prompt_delimits_untrusted_context(self):
        from prompt_library.prompt import PROMPT_TEMPLATES
        prompt = PROMPT_TEMPLATES["product_bot"]
        self.assertIn("<doc", prompt)
        self.assertIn("untrusted", prompt.lower())


class CitationVerificationTests(unittest.TestCase):
    def test_passes_when_answer_has_no_citations(self):
        docs = [Document(page_content="x", metadata={"source_id": "row-1"})]
        self.assertTrue(_verify_citations("A generic answer with no citation.", docs))

    def test_passes_when_all_citations_match_retrieved_sources(self):
        docs = [
            Document(page_content="x", metadata={"source_id": "row-1"}),
            Document(page_content="y", metadata={"source_id": "row-2"}),
        ]
        answer = "Great pick [source:row-1] and also [source:row-2]."
        self.assertTrue(_verify_citations(answer, docs))

    def test_fails_when_citation_references_unretrieved_source(self):
        docs = [Document(page_content="x", metadata={"source_id": "row-1"})]
        answer = "Great pick [source:row-99]."
        self.assertFalse(_verify_citations(answer, docs))

    def test_fails_when_one_of_several_citations_is_fabricated(self):
        docs = [Document(page_content="x", metadata={"source_id": "row-1"})]
        answer = "See [source:row-1] and also [source:row-404]."
        self.assertFalse(_verify_citations(answer, docs))

    def test_passes_when_multiple_citations_are_bundled_in_one_bracket(self):
        """Regression test: some models (observed on Llama-3.3-70B-Instruct
        via the HuggingFace router) bundle several citations into a single
        bracket -- "[source:A, source:B]" -- instead of one bracket per
        citation. That must not be treated as one fabricated combined ID."""
        docs = [
            Document(page_content="x", metadata={"source_id": "row-1"}),
            Document(page_content="y", metadata={"source_id": "row-2"}),
        ]
        answer = "Great picks [source:row-1, source:row-2]."
        self.assertTrue(_verify_citations(answer, docs))


if __name__ == "__main__":
    unittest.main()
