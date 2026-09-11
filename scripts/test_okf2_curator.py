"""Integration test for OKF 2.0 and Knowledge Curator Subsystem."""

from __future__ import annotations

import asyncio
import tempfile

from tars.domains.knowledge import (
    AutoAcceptReviewHandler,
    CurationProposal,
    FileStorageManager,
    InteractiveUserReviewHandler,
    KnowledgeCuratorAgent,
    MicroFactManager,
    OKF2Document,
    OKF2Metadata,
    extract_wikilinks,
    parse_okf_text,
    serialize_okf_document,
)


class MockLLM:
    async def agenerate(self, messages, temperature: float = 0.1):
        payload = """```json
{
  "micro_facts": [
    {"key": "favorite_editor", "value": "Neovim", "category": "preference"}
  ],
  "documents": [
    {
      "doc_id": "neovim-config-guide",
      "title": "Neovim Configuration Guide",
      "type": "procedure",
      "category": "tools",
      "tags": ["editor", "config"],
      "aliases": ["nvim-setup"],
      "importance": "high",
      "content": "Setup guide for Neovim. Check [[getting-started]] first."
    }
  ]
}
```"""
        return payload


async def test_suite() -> None:
    print("[1/4] Testing Tier 1 Micro Fact Layer...")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorageManager(base_dir=tmpdir)
        micro_mgr = MicroFactManager(storage_manager=storage)

        # 1. Test Micro Fact
        await micro_mgr.set_fact("user123", "coffee_taste", "콜드브루 산미 없음", category="preference")
        profile = await micro_mgr.get_profile("user123")
        assert "coffee_taste" in profile.facts
        print("  ✓ Micro Fact verified:")
        print(profile.format_for_prompt())

        # 2. Test OKF 2.0 & Wiki-Link
        print("[2/4] Testing OKF 2.0 Spec & Obsidian [[wiki-link]]...")
        sample_body = "Welcome to TARS. See [[k8s-infra|Kubernetes Guide]] and [[monitoring]]."
        meta = OKF2Metadata(
            id="getting-started",
            title="Getting Started with TARS",
            type="concept",
            aliases=["intro", "quickstart"],
            tags=["tars", "guide"],
        )
        doc = OKF2Document(metadata=meta, content=sample_body)
        assert len(doc.wikilinks) == 2
        assert doc.outgoing_link_ids == ["k8s-infra", "monitoring"]
        raw = serialize_okf_document(doc)
        parsed = parse_okf_text(raw)
        assert parsed.metadata.okf_version == "2.0"
        assert parsed.metadata.aliases == ["intro", "quickstart"]
        print("  ✓ OKF 2.0 & Wiki-Link serialization & parsing verified!")

        # 3. Test Curator Agent with Mock LLM
        print("[3/4] Testing Knowledge Curator Agent Autonomous Pipeline...")
        curator = KnowledgeCuratorAgent(
            llm_adapter=MockLLM(),
            storage_manager=storage,
            micro_fact_manager=micro_mgr,
        )
        result = await curator.curate("user123", "My editor is Neovim and here is my setup guide...")
        assert len(result["micro_facts"]) == 1
        assert len(result["curated_docs"]) == 1
        curated_doc = result["curated_docs"][0]
        assert curated_doc.id == "neovim-config-guide"
        assert curated_doc.outgoing_link_ids == ["getting-started"]
        print(f"  ✓ Curated document '{curated_doc.id}' created with links: {curated_doc.outgoing_link_ids}")

        # 4. Test InteractiveReviewHandler (rejected proposal)
        print("[4/4] Testing InteractiveUserReviewHandler Extensibility...")
        rejected_handler = InteractiveUserReviewHandler(callback=lambda p: False)
        curator_reject = KnowledgeCuratorAgent(
            llm_adapter=MockLLM(),
            storage_manager=storage,
            review_handler=rejected_handler,
        )
        res_reject = await curator_reject.curate("user123", "Some text")
        assert len(res_reject["curated_docs"]) == 0
        print("  ✓ InteractiveReviewHandler rejection tested successfully!")

    print("\n🎉 ALL OKF 2.0 & CURATOR TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(test_suite())
