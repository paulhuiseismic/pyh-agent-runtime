"""T006: prompting 单元测试——结构化输出解析。"""

import json

from kernel.react.prompting import build_thought_messages, parse_thought
from kernel.react.models import Observation


class TestParseThought:
    def test_final_answer_parsed(self):
        decision = parse_thought(json.dumps({"action": "final_answer", "content": "42"}))
        assert decision.action == "final_answer"
        assert decision.content == "42"

    def test_call_tool_parsed(self):
        decision = parse_thought(
            json.dumps({"action": "call_tool", "tool": "search", "arguments": {"q": "x"}})
        )
        assert decision.action == "call_tool"
        assert decision.tool == "search"
        assert decision.arguments == {"q": "x"}

    def test_non_json_is_malformed(self):
        assert parse_thought("not json at all").action == "malformed"

    def test_missing_action_is_malformed(self):
        assert parse_thought(json.dumps({"content": "x"})).action == "malformed"

    def test_invalid_action_value_is_malformed(self):
        assert parse_thought(json.dumps({"action": "do_something_else"})).action == "malformed"

    def test_final_answer_without_content_is_malformed(self):
        assert parse_thought(json.dumps({"action": "final_answer"})).action == "malformed"

    def test_call_tool_without_tool_name_is_malformed(self):
        assert parse_thought(json.dumps({"action": "call_tool", "arguments": {}})).action == "malformed"

    def test_json_array_is_malformed(self):
        assert parse_thought(json.dumps([1, 2, 3])).action == "malformed"


class TestBuildThoughtMessages:
    def test_includes_goal_and_tools(self):
        messages = build_thought_messages("找到答案", {"search": "搜索工具"}, [])
        assert messages[0].role == "system"
        assert "search" in messages[0].content
        assert "找到答案" in messages[1].content

    def test_includes_history(self):
        history = [("call_tool: search", Observation(success=True, content="结果"))]
        messages = build_thought_messages("目标", {}, history)
        contents = [m.content for m in messages]
        assert any("结果" in c for c in contents)

    def test_no_tools_shows_placeholder(self):
        messages = build_thought_messages("目标", {}, [])
        assert "无可用工具" in messages[0].content
