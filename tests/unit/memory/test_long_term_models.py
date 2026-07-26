"""T004: MemoryEntry / ExtractionResult 数据结构测试。"""

from kernel.memory.long_term_models import ExtractionResult, MemoryEntry


def test_memory_entry_defaults():
    entry = MemoryEntry(content="likes concise answers")
    assert entry.content == "likes concise answers"
    assert entry.category is None


def test_memory_entry_with_category():
    entry = MemoryEntry(content="likes concise answers", category="response_style")
    assert entry.category == "response_style"


def test_extraction_result_defaults_to_empty():
    result = ExtractionResult()
    assert result.entries == []


def test_extraction_result_with_entries():
    entries = [MemoryEntry(content="a"), MemoryEntry(content="b", category="c")]
    result = ExtractionResult(entries=entries)
    assert result.entries == entries
