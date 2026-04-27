from __future__ import annotations

"""Wiki Indexer - 문서를 벡터 DB에 인덱싱

이 모듈은 Markdown 문서를 파싱하고 임베딩을 생성하여
LanceDB에 저장합니다. Wikilink 관계도 graph.json으로 저장합니다.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb
from sentence_transformers import SentenceTransformer

from wiki_search_mcp.core.config import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODELS, WikiConfig
from wiki_search_mcp.core.logging import get_logger
from wiki_search_mcp.core.types import ConfidenceDict, FrontmatterDict
from wiki_search_mcp.core.utils import parse_frontmatter, resolve_pages_path, tokenize
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher

logger = get_logger("indexer")


class WikiIndexer:
    """Wiki 페이지를 벡터 DB에 인덱싱하는 클래스.

    Attributes:
        wiki_path: wiki 루트 경로
        pages_path: 페이지가 저장된 경로 (wiki/pages)
        db_path: 벡터 DB 저장 경로 (wiki/.vectordb)
        model: sentence-transformers 임베딩 모델
        db: LanceDB 연결 객체
    """

    def __init__(self, wiki_path: str, model_name: str | None = None):
        """WikiIndexer 초기화.

        Args:
            wiki_path: wiki 루트 경로. pages/ 하위 디렉토리가 있으면 사용,
                       없으면 wiki_path 자체를 문서 루트로 사용.
            model_name: 사용할 임베딩 모델명. None이면 환경변수 또는 기본값 사용.
                        "fast" 또는 "accurate"로 프리셋 선택 가능.
        """
        self.wiki_path = Path(wiki_path)

        # 런타임 설정 로드
        self.wiki_config = WikiConfig.load(self.wiki_path)

        # 무시 패턴 매처 (dot-prefix + .gitignore + WIKI_IGNORE)
        self.ignore_matcher = IgnoreMatcher.from_wiki(self.wiki_path)

        # pages 디렉토리 탐지 (utils.resolve_pages_path 사용)
        self.pages_path = resolve_pages_path(self.wiki_path)

        self.db_path = self.wiki_path / ".vectordb"
        self.db_path.mkdir(parents=True, exist_ok=True)

        # 모델 로드 (첫 실행 시 다운로드)
        # 우선순위: 인자 > WikiConfig.embedding_model (env 반영됨) > 기본값
        model_key = (
            model_name
            or self.wiki_config.embedding_model
            or os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        )
        model_to_use = EMBEDDING_MODELS.get(model_key, model_key)
        self.model = SentenceTransformer(model_to_use)

        # LanceDB 연결
        self.db = lancedb.connect(str(self.db_path))

        # 메타데이터 캐시 경로
        self._meta_path = self.db_path / "meta.json"

    def extract_wikilinks(self, content: str) -> list[str]:
        """[[link]] 형태의 wikilink 추출.

        Args:
            content: Markdown 내용

        Returns:
            wikilink 목록 (대괄호 제거됨)
        """
        return re.findall(r"\[\[([^\]]+)\]\]", content)

    def calculate_confidence(self, meta: FrontmatterDict) -> ConfidenceDict:
        """4-Factor Confidence 점수 계산.

        Args:
            meta: frontmatter 데이터

        Returns:
            ConfidenceDict: {level, score, factors}

        Note:
            잘못된 타입의 factor 값은 무시하고 기본값을 사용합니다.
            예: tested: "yes" (문자열) → 무시됨 (bool 기대)
        """
        conf = meta.get("confidence", {})

        if isinstance(conf, str):
            # 기존 형식 (단순 문자열) 지원
            return {"level": conf, "score": 50, "factors": {}}

        # dict가 아닌 경우 기본값 반환
        if not isinstance(conf, dict):
            logger.warning(f"Invalid confidence type: {type(conf).__name__}, using default")
            return {"level": "medium", "score": 50, "factors": {}}

        score = 0
        factors = {}

        # tested: +30 (bool 타입 검증)
        tested = conf.get("tested")
        if isinstance(tested, bool) and tested:
            score += 30
            factors["tested"] = True
        elif tested is not None and not isinstance(tested, bool):
            logger.warning(f"Invalid tested type: {type(tested).__name__}, ignoring")

        # production: +30 (bool 타입 검증)
        production = conf.get("production")
        if isinstance(production, bool) and production:
            score += 30
            factors["production"] = True
        elif production is not None and not isinstance(production, bool):
            logger.warning(f"Invalid production type: {type(production).__name__}, ignoring")

        # sources: primary +20, secondary +10 (str 타입 검증)
        sources = conf.get("sources", "")
        if isinstance(sources, str):
            if sources == "primary":
                score += 20
                factors["sources"] = "primary"
            elif sources == "secondary":
                score += 10
                factors["sources"] = "secondary"
        elif sources:
            logger.warning(f"Invalid sources type: {type(sources).__name__}, ignoring")

        # freshness: current +20, recent +10 (str 타입 검증)
        freshness = conf.get("freshness", "")
        if isinstance(freshness, str):
            if freshness == "current":
                score += 20
                factors["freshness"] = "current"
            elif freshness == "recent":
                score += 10
                factors["freshness"] = "recent"
        elif freshness:
            logger.warning(f"Invalid freshness type: {type(freshness).__name__}, ignoring")

        # 레벨 판정
        if score >= 70:
            level = "high"
        elif score >= 40:
            level = "medium"
        else:
            level = "low"

        return {"level": level, "score": score, "factors": factors}

    def _get_file_mtime(self, path: Path) -> float:
        """파일 수정 시간 반환."""
        return path.stat().st_mtime

    def _load_meta(self) -> dict[str, Any]:
        """메타데이터 로드."""
        if self._meta_path.exists():
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        return {"files": {}, "last_indexed": None}

    def _save_meta(self, meta: dict[str, Any]) -> None:
        """메타데이터 저장."""
        self._meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def reindex(self, full: bool = False) -> dict[str, Any]:
        """전체 또는 증분 인덱싱.

        Args:
            full: True면 전체 재구축, False면 변경분만

        Returns:
            {"indexed": 전체수, "updated": 갱신수, "duration_ms": 소요시간}
        """
        import time

        start_time = time.time()
        mode = "full" if full else "incremental"
        logger.info(f"Starting {mode} reindex: {self.pages_path}")

        all_pages = list(self.pages_path.rglob("*.md"))
        # IgnoreMatcher로 dot-prefix + .gitignore + WIKI_IGNORE 적용
        pages = [p for p in all_pages if not self.ignore_matcher.should_ignore(p)]
        logger.debug(f"Found {len(pages)} markdown files (filtered from {len(all_pages)})")
        meta = self._load_meta()

        # full이면 캐시 무시
        if full:
            meta["files"] = {}

        # 기존 테이블에서 레코드 로드 (증분 인덱싱용)
        existing_records: dict[str, dict] = {}
        if not full and "wiki" in self.db.list_tables():
            table = self.db.open_table("wiki")
            for row in table.to_arrow().to_pylist():
                existing_records[row["path"]] = row

        # 기존 그래프 로드 (증분 인덱싱용)
        existing_graph: dict[str, Any] = {"nodes": [], "edges": []}
        graph_path = self.db_path / "graph.json"
        if not full and graph_path.exists():
            existing_graph = json.loads(graph_path.read_text(encoding="utf-8"))

        # 기존 그래프를 path 기준으로 인덱싱
        existing_nodes: dict[str, dict] = {
            n["id"]: n for n in existing_graph.get("nodes", [])
        }
        existing_edges_by_source: dict[str, list[dict]] = {}
        for e in existing_graph.get("edges", []):
            src = e["source"]
            if src not in existing_edges_by_source:
                existing_edges_by_source[src] = []
            existing_edges_by_source[src].append(e)

        records = []
        graph_nodes = []
        graph_edges = []
        updated_count = 0

        # 현재 존재하는 파일 경로 추적 (삭제된 파일 감지용)
        current_paths: set[str] = set()

        # 1단계: 변경된 파일과 미변경 파일 분류
        pages_to_process: list[tuple[Path, str, float]] = []  # (page, rel_path, mtime)

        for page in pages:
            # Path traversal 방어: resolve() 후 pages_path 하위인지 검증
            page_resolved = page.resolve()
            pages_resolved = self.pages_path.resolve()
            try:
                rel_path = str(page_resolved.relative_to(pages_resolved))
            except ValueError:
                # pages_path 외부 파일 접근 시도
                continue
            if ".." in rel_path:
                # 상대 경로에 .. 포함 시 스킵
                continue

            current_paths.add(rel_path)
            mtime = self._get_file_mtime(page)

            # 증분 체크: 수정 시간이 같으면 기존 데이터 재사용
            if not full and meta["files"].get(rel_path) == mtime:
                # 기존 레코드 복원
                if rel_path in existing_records:
                    records.append(existing_records[rel_path])

                # 기존 그래프 노드/엣지 복원
                if rel_path in existing_nodes:
                    graph_nodes.append(existing_nodes[rel_path])
                if rel_path in existing_edges_by_source:
                    graph_edges.extend(existing_edges_by_source[rel_path])
            else:
                # 변경된 파일: 처리 대상에 추가
                pages_to_process.append((page, rel_path, mtime))

        # 2단계: 변경된 파일들의 텍스트 수집
        texts_for_embedding: list[str] = []
        page_data: list[tuple[str, dict, str, list[str], float]] = []
        # (rel_path, page_meta, body, links, mtime)

        for page, rel_path, mtime in pages_to_process:
            content = page.read_text(encoding="utf-8")
            page_meta, body = parse_frontmatter(content)
            title = page_meta.get("title", page.stem)
            links = self.extract_wikilinks(content)

            texts_for_embedding.append(f"{title} {body[:2000]}")
            page_data.append((rel_path, page_meta, body, links, mtime))

        # 3단계: 배치 임베딩 (한 번에 처리)
        embeddings = []
        if texts_for_embedding:
            # show_progress_bar: 대용량 Wiki에서 진행 상황 표시
            embeddings = self.model.encode(
                texts_for_embedding,
                show_progress_bar=len(texts_for_embedding) > 10,
            )

        # 4단계: 레코드 생성
        for i, (rel_path, page_meta, body, links, mtime) in enumerate(page_data):
            title = page_meta.get("title", Path(rel_path).stem)
            embedding = embeddings[i].tolist() if i < len(embeddings) else []

            # Confidence 계산
            confidence = self.calculate_confidence(page_meta)

            records.append(
                {
                    "id": rel_path,
                    "path": rel_path,
                    "title": title,
                    "category": page_meta.get("category", "uncategorized"),
                    "tags": page_meta.get("tags", []),
                    "state": page_meta.get("state", "stable"),
                    "confidence_level": confidence["level"],
                    "confidence_score": confidence["score"],
                    "summary": body[:300],
                    "created": str(page_meta.get("created", "")),
                    "updated": str(page_meta.get("updated", "")),
                    "vector": embedding,
                }
            )

            # 그래프 노드
            graph_nodes.append(
                {
                    "id": rel_path,
                    "title": title,
                    "category": page_meta.get("category", "uncategorized"),
                }
            )

            # 그래프 엣지 (중복 제거)
            seen_targets = set()
            for link in links:
                # link가 .md 확장자 없이 올 수 있음
                target = link if link.endswith(".md") else f"{link}.md"
                if target not in seen_targets:
                    graph_edges.append({"source": rel_path, "target": target})
                    seen_targets.add(target)

            # 메타 업데이트
            meta["files"][rel_path] = mtime
            updated_count += 1

        # 삭제된 파일 메타에서 제거
        deleted_paths = set(meta["files"].keys()) - current_paths
        for deleted_path in deleted_paths:
            del meta["files"][deleted_path]

        # LanceDB 테이블 생성/갱신
        if records:
            if "wiki" in self.db.list_tables():
                self.db.drop_table("wiki")
            self.db.create_table("wiki", records)

        # 그래프 저장
        graph_path.write_text(
            json.dumps(
                {"nodes": graph_nodes, "edges": graph_edges},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # BM25 인덱스 구축 및 저장
        if records:
            bm25_data = {
                "tokens": [
                    tokenize(f"{r['title']} {r['summary']}") for r in records
                ],
                "paths": [r["path"] for r in records],
            }
            bm25_path = self.db_path / "bm25_index.json"
            bm25_path.write_text(
                json.dumps(bm25_data, ensure_ascii=False), encoding="utf-8"
            )

        # 메타 저장
        meta["last_indexed"] = datetime.now().isoformat()
        self._save_meta(meta)

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Reindex completed: indexed={len(records)}, updated={updated_count}, "
            f"deleted={len(deleted_paths)}, duration={duration_ms}ms"
        )

        return {
            "indexed": len(records),
            "updated": updated_count,
            "duration_ms": duration_ms,
        }
