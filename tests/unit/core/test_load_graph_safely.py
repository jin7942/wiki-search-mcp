"""load_graph_safely 손상 강건성 테스트.

graph.json 부분쓰기/키누락/형식오류에서도 reindex/검증이 죽지 않아야 한다.
"""

import json

from wiki_search_mcp.core.utils import load_graph_safely


def test_missing_file_returns_empty(tmp_path):
    """파일 없으면 빈 그래프."""
    result = load_graph_safely(tmp_path / "graph.json")
    assert result == {"nodes": [], "edges": []}


def test_valid_graph_passthrough(tmp_path):
    """정상 그래프는 그대로 통과."""
    p = tmp_path / "graph.json"
    data = {
        "nodes": [{"id": "a.md", "title": "A"}],
        "edges": [{"source": "a.md", "target": "b.md"}],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    result = load_graph_safely(p)
    assert result["nodes"] == [{"id": "a.md", "title": "A"}]
    assert result["edges"] == [{"source": "a.md", "target": "b.md"}]


def test_corrupt_json_returns_empty(tmp_path):
    """JSON 파싱 실패(부분쓰기) → 빈 그래프."""
    p = tmp_path / "graph.json"
    p.write_text('{"nodes": [{"id": "a.md"', encoding="utf-8")  # 잘린 JSON
    result = load_graph_safely(p)
    assert result == {"nodes": [], "edges": []}


def test_non_dict_top_level_returns_empty(tmp_path):
    """최상위가 dict 아니면 빈 그래프."""
    p = tmp_path / "graph.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_graph_safely(p) == {"nodes": [], "edges": []}


def test_node_missing_id_filtered(tmp_path):
    """id 없는 node 는 제거(KeyError 방지)."""
    p = tmp_path / "graph.json"
    data = {
        "nodes": [{"id": "ok.md"}, {"title": "no-id"}, "string-node"],
        "edges": [],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    result = load_graph_safely(p)
    assert result["nodes"] == [{"id": "ok.md"}]


def test_edge_missing_keys_filtered(tmp_path):
    """source/target 누락 edge 는 제거(KeyError 방지)."""
    p = tmp_path / "graph.json"
    data = {
        "nodes": [],
        "edges": [
            {"source": "a.md", "target": "b.md"},  # ok
            {"source": "a.md"},  # target 누락
            {"target": "b.md"},  # source 누락
            "string-edge",  # dict 아님
        ],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    result = load_graph_safely(p)
    assert result["edges"] == [{"source": "a.md", "target": "b.md"}]


def test_missing_keys_default_empty(tmp_path):
    """nodes/edges 키 자체가 없어도 빈 리스트."""
    p = tmp_path / "graph.json"
    p.write_text("{}", encoding="utf-8")
    assert load_graph_safely(p) == {"nodes": [], "edges": []}
