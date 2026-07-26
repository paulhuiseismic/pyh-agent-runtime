"""T004: parse_extraction 结构化输出解析测试（含 category 归一化）。"""

import json

from kernel.memory.extraction import build_extraction_request, parse_extraction
from kernel.provider import Message


class TestParseExtraction:
    def test_valid_array_with_category(self):
        content = json.dumps([{"category": "food", "content": "喜欢辣的"}])
        result = parse_extraction(content)
        assert len(result.entries) == 1
        assert result.entries[0].content == "喜欢辣的"
        assert result.entries[0].category == "food"

    def test_valid_array_with_null_category(self):
        content = json.dumps([{"category": None, "content": "随手记的一件事"}])
        result = parse_extraction(content)
        assert result.entries[0].category is None

    def test_empty_array(self):
        assert parse_extraction("[]").entries == []

    def test_non_json_returns_empty(self):
        assert parse_extraction("not json").entries == []

    def test_json_object_not_array_returns_empty(self):
        assert parse_extraction(json.dumps({"content": "x"})).entries == []

    def test_element_missing_content_skipped(self):
        content = json.dumps([{"category": "x"}, {"category": "y", "content": "kept"}])
        result = parse_extraction(content)
        assert len(result.entries) == 1
        assert result.entries[0].content == "kept"

    def test_empty_string_category_normalized_to_none(self):
        content = json.dumps([{"category": "", "content": "x"}])
        assert parse_extraction(content).entries[0].category is None

    def test_whitespace_category_normalized_to_none(self):
        content = json.dumps([{"category": "   ", "content": "x"}])
        assert parse_extraction(content).entries[0].category is None

    def test_empty_content_skipped(self):
        content = json.dumps([{"category": "x", "content": "   "}])
        assert parse_extraction(content).entries == []


class TestBuildExtractionRequest:
    def test_includes_history_and_tenant(self):
        history = (Message(role="user", content="我喜欢简洁的回答"),)
        request = build_extraction_request(history, tenant_id="tenant-a", model="m")
        assert request.tenant_id == "tenant-a"
        assert request.model == "m"
        assert any("简洁的回答" in m.content for m in request.messages)
