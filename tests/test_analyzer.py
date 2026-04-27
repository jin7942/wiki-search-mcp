"""분석 기능 테스트

고아 문서 감지, 유사 문서 추천 기능을 테스트합니다.
"""


class TestOrphanDetection:
    """고아 문서 감지 테스트."""

    def test_find_orphans_basic(self):
        """기본 고아 문서 감지."""
        graph = {
            "nodes": [
                {"id": "a.md"},
                {"id": "b.md"},
                {"id": "orphan.md"},
            ],
            "edges": [
                {"source": "a.md", "target": "b.md"},
            ],
        }

        all_paths = set(node["id"] for node in graph["nodes"])
        referenced_paths = set()
        for edge in graph["edges"]:
            referenced_paths.add(edge["target"])
            # .md 확장자 없는 버전도 추가
            target = edge["target"]
            if target.endswith(".md"):
                referenced_paths.add(target[:-3])

        orphan_paths = all_paths - referenced_paths

        # orphan.md와 a.md는 참조되지 않음 (a.md는 source로만 사용)
        assert "orphan.md" in orphan_paths
        assert "a.md" in orphan_paths
        assert "b.md" not in orphan_paths

    def test_no_orphans(self):
        """고아 문서 없음."""
        graph = {
            "nodes": [
                {"id": "a.md"},
                {"id": "b.md"},
            ],
            "edges": [
                {"source": "a.md", "target": "b.md"},
                {"source": "b.md", "target": "a.md"},
            ],
        }

        all_paths = set(node["id"] for node in graph["nodes"])
        referenced_paths = set(edge["target"] for edge in graph["edges"])
        orphan_paths = all_paths - referenced_paths

        # 양방향 참조이므로 고아 없음
        assert len(orphan_paths) == 0

    def test_all_orphans(self):
        """모두 고아 문서."""
        graph = {
            "nodes": [
                {"id": "a.md"},
                {"id": "b.md"},
            ],
            "edges": [],
        }

        all_paths = set(node["id"] for node in graph["nodes"])
        referenced_paths = set(edge["target"] for edge in graph.get("edges", []))
        orphan_paths = all_paths - referenced_paths

        # 엣지가 없으면 모두 고아
        assert len(orphan_paths) == 2


class TestSimilarDocuments:
    """유사 문서 추천 테스트."""

    def test_similarity_calculation(self):
        """유사도 계산."""
        # L2 거리 0이면 유사도 1
        distance = 0
        similarity = max(0, 1 - distance / 2)
        assert similarity == 1.0

        # L2 거리 2면 유사도 0
        distance = 2
        similarity = max(0, 1 - distance / 2)
        assert similarity == 0.0

        # L2 거리 1이면 유사도 0.5
        distance = 1
        similarity = max(0, 1 - distance / 2)
        assert similarity == 0.5

    def test_exclude_self(self):
        """자기 자신 제외."""
        results = [
            {"path": "source.md", "_distance": 0},
            {"path": "similar1.md", "_distance": 0.5},
            {"path": "similar2.md", "_distance": 0.8},
        ]

        source_path = "source.md"
        similar = [r for r in results if r["path"] != source_path]

        assert len(similar) == 2
        assert all(r["path"] != source_path for r in similar)

    def test_top_k_limit(self):
        """유사 문서 수 제한."""
        results = [
            {"path": f"doc{i}.md", "_distance": i * 0.1}
            for i in range(10)
        ]

        top_k = 3
        limited = results[:top_k]

        assert len(limited) == 3


class TestSortOptions:
    """정렬 옵션 테스트."""

    def test_sort_by_similarity_desc(self):
        """유사도 내림차순 정렬."""
        results = [
            {"similarity": 0.5},
            {"similarity": 0.9},
            {"similarity": 0.3},
        ]

        sorted_results = sorted(results, key=lambda x: x["similarity"], reverse=True)

        assert sorted_results[0]["similarity"] == 0.9
        assert sorted_results[1]["similarity"] == 0.5
        assert sorted_results[2]["similarity"] == 0.3

    def test_sort_by_confidence_desc(self):
        """신뢰도 내림차순 정렬."""
        results = [
            {"confidence": {"score": 40}},
            {"confidence": {"score": 80}},
            {"confidence": {"score": 20}},
        ]

        sorted_results = sorted(
            results, key=lambda x: x["confidence"]["score"], reverse=True
        )

        assert sorted_results[0]["confidence"]["score"] == 80
        assert sorted_results[1]["confidence"]["score"] == 40
        assert sorted_results[2]["confidence"]["score"] == 20

    def test_sort_by_title_asc(self):
        """제목 오름차순 정렬."""
        results = [
            {"title": "Zebra"},
            {"title": "Alpha"},
            {"title": "Mango"},
        ]

        sorted_results = sorted(results, key=lambda x: x["title"], reverse=False)

        assert sorted_results[0]["title"] == "Alpha"
        assert sorted_results[1]["title"] == "Mango"
        assert sorted_results[2]["title"] == "Zebra"

    def test_sort_by_updated(self):
        """업데이트 시간 정렬."""
        results = [
            {"updated": "2024-01-01"},
            {"updated": "2024-03-01"},
            {"updated": "2024-02-01"},
        ]

        sorted_results = sorted(
            results, key=lambda x: x.get("updated", ""), reverse=True
        )

        assert sorted_results[0]["updated"] == "2024-03-01"
        assert sorted_results[1]["updated"] == "2024-02-01"
        assert sorted_results[2]["updated"] == "2024-01-01"
