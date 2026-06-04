from __future__ import annotations

"""Wiki Indexer - 문서를 벡터 DB에 인덱싱

이 모듈은 Markdown 문서를 파싱하고 임베딩을 생성하여
LanceDB에 저장합니다. Wikilink 관계도 graph.json으로 저장합니다.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb

from wiki_search_mcp.core.config import DEFAULT_EMBEDDING_MODEL, WikiConfig
from wiki_search_mcp.core.logging import get_logger
from wiki_search_mcp.core.metrics import record
from wiki_search_mcp.core.types import ConfidenceDict, FrontmatterDict
from wiki_search_mcp.core.utils import (
    load_graph_safely,
    parse_frontmatter,
    resolve_pages_path,
    tokenize,
)
from wiki_search_mcp.infrastructure.daemon.paths import reindex_lock_file
from wiki_search_mcp.infrastructure.daemon.pidfile import cross_process_lock
from wiki_search_mcp.infrastructure.embedding.model_provider import get_model
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.infrastructure.storage.lancedb_compat import has_table

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

    def __init__(
        self,
        wiki_path: str,
        model_name: str | None = None,
        ignore_patterns: tuple[str, ...] = (),
    ):
        """WikiIndexer 초기화.

        Args:
            wiki_path: wiki 루트 경로. pages/ 하위 디렉토리가 있으면 사용,
                       없으면 wiki_path 자체를 문서 루트로 사용.
            model_name: 사용할 임베딩 모델명. None이면 기본값 사용.
                        "fast" 또는 "accurate"로 프리셋 선택 가능.
            ignore_patterns: CLI ``--ignore``로 전달된 추가 무시 패턴
        """
        self.wiki_path = Path(wiki_path)

        # reindex 파일 쓰기 구간을 프로세스 간에 직렬화하는 cross-process flock 경로.
        # serve / daemon / CLI 가 같은 vault 에 동시에 reindex 해도 LanceDB 매니페스트
        # race / JSON 부분 손상을 막는다. daemon paths 헬퍼와 같은 state_dir 를 쓴다.
        self._reindex_lock_path = reindex_lock_file(self.wiki_path)

        # 런타임 설정 로드 (현재는 기본값 dataclass 반환)
        self.wiki_config = WikiConfig.load(self.wiki_path)

        # 무시 패턴 매처 (dot-prefix + .gitignore + extra_patterns)
        self.ignore_matcher = IgnoreMatcher.from_wiki(
            self.wiki_path,
            extra_patterns=tuple(ignore_patterns),
        )

        # pages 디렉토리 탐지 (utils.resolve_pages_path 사용)
        self.pages_path = resolve_pages_path(self.wiki_path)

        self.db_path = self.wiki_path / ".vectordb"
        self.db_path.mkdir(parents=True, exist_ok=True)

        # 모델 로드 — 싱글톤 provider 사용.
        # 우선순위: 인자 > WikiConfig.embedding_model > 기본값.
        # 과거에는 SentenceTransformer 를 직접 생성해 Searcher 의 모델과 별도
        # 인스턴스가 메모리에 중복 로드됐다. get_model() 은 모델 경로별 전역
        # 캐시라, 같은 모델은 프로세스당 한 번만 로드된다.
        model_key = (
            model_name
            or self.wiki_config.embedding_model
            or DEFAULT_EMBEDDING_MODEL
        )
        self.model = get_model(model_key)

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

    def _get_file_hash(self, path: Path) -> str:
        """파일 내용의 SHA-256 해시(hex) 반환.

        mtime 만으로는 ``touch`` / ``git checkout`` 처럼 내용이 그대로인데
        수정 시간만 바뀌는 경우를 거르지 못한다. 내용 해시를 병행해
        '실제로 바뀐 파일' 만 재임베딩한다.
        """
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _is_unchanged(self, stored: Any, page: Path, mtime: float) -> tuple[bool, str | None]:
        """``page`` 가 기존 인덱스 대비 변경되지 않았는지 판정.

        성능을 위해 mtime 을 먼저 본다(파일 읽기 없음). mtime 이 같으면
        내용도 같다고 보고 즉시 미변경 처리한다. mtime 이 다를 때만 내용
        해시를 계산해, 해시가 같으면(= 내용은 그대로) 미변경으로 판정한다.

        Args:
            stored: ``meta["files"][rel_path]`` 에 저장된 값. 신규 포맷은
                ``{"mtime": float, "hash": str}`` 딕셔너리, 구버전은 float
                (mtime 단독). ``None`` 이면 신규 파일.
            page: 검사할 파일 경로.
            mtime: 이미 계산해 둔 현재 mtime (중복 stat 회피).

        Returns:
            ``(unchanged, current_hash)`` 튜플. ``unchanged`` 가 True 면
            재처리 불필요. ``current_hash`` 는 해시를 계산했을 때만 채워지며
            (mtime 갱신 저장에 사용), 계산하지 않았으면 ``None``.
        """
        # 신규 파일
        if stored is None:
            return False, None

        # 구버전 포맷(float): 해시 정보가 없으므로 mtime 으로만 판정.
        # 다음 번 처리 시 자연히 신규 포맷으로 승격된다.
        if not isinstance(stored, dict):
            return stored == mtime, None

        stored_mtime = stored.get("mtime")
        stored_hash = stored.get("hash")

        # 빠른 경로: mtime 일치 → 내용도 동일하다고 간주(읽기 없음)
        if stored_mtime == mtime:
            return True, None

        # mtime 이 다르면 내용 해시로 실제 변경 여부 확인
        current_hash = self._get_file_hash(page)
        return current_hash == stored_hash, current_hash

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

    def _create_or_replace_table(self, records: list[dict[str, Any]]) -> None:
        """``wiki`` 테이블을 records 로 덮어쓴다 (overwrite 회귀 대응).

        반드시 cross-process reindex flock 안에서 호출해야 한다 (drop+create
        사이에 다른 프로세스가 끼어들지 않음을 락이 보장).

        1. ``mode="overwrite"`` 로 단일 호출 시도 (정상 경로).
        2. ``Table ... already exists`` 류 예외가 나면 명시적으로 drop 후 재생성.
        3. drop 자체가 "테이블 없음" 으로 실패하면 무시하고 create 재시도.
        """
        try:
            self.db.create_table("wiki", records, mode="overwrite")
            return
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise
            logger.warning(
                "create_table(overwrite) hit 'already exists'; "
                "falling back to drop+create: %s",
                e,
            )

        # 폴백: 명시적 drop 후 재생성.
        try:
            self.db.drop_table("wiki")
        except Exception as drop_err:
            # 이미 없거나 drop 미지원 — create 로 진행.
            logger.debug("drop_table('wiki') ignored: %s", drop_err)
        self.db.create_table("wiki", records)

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
        if not full and has_table(self.db, "wiki"):
            table = self.db.open_table("wiki")
            for row in table.to_arrow().to_pylist():
                existing_records[row["path"]] = row

        # 기존 그래프 로드 (증분 인덱싱용)
        existing_graph: dict[str, Any] = {"nodes": [], "edges": []}
        graph_path = self.db_path / "graph.json"
        if not full and graph_path.exists():
            # 손상(부분쓰기/키누락) 시 빈 그래프로 폴백 → 증분이 안전하게
            # 전체 재구축처럼 동작. 키 누락 항목은 로더가 걸러내므로
            # 아래 n["id"]/e["source"] 접근은 KeyError 안전하다.
            existing_graph = load_graph_safely(graph_path)

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

            # 증분 체크: mtime+내용해시 병행. mtime 이 같으면 즉시 재사용,
            # 다르면 해시로 실제 변경 여부 확인.
            unchanged, current_hash = (
                (False, None)
                if full
                else self._is_unchanged(meta["files"].get(rel_path), page, mtime)
            )
            if unchanged:
                # 기존 레코드 복원
                if rel_path in existing_records:
                    records.append(existing_records[rel_path])

                # 기존 그래프 노드/엣지 복원
                if rel_path in existing_nodes:
                    graph_nodes.append(existing_nodes[rel_path])
                if rel_path in existing_edges_by_source:
                    graph_edges.extend(existing_edges_by_source[rel_path])

                # mtime 만 바뀌고 내용은 동일한 경우(touch/checkout):
                # 저장된 mtime 을 갱신해 다음 reindex 에서 재해시를 피한다.
                if current_hash is not None:
                    meta["files"][rel_path] = {"mtime": mtime, "hash": current_hash}
            else:
                # 변경된 파일: 처리 대상에 추가 (이미 계산한 해시 재사용)
                pages_to_process.append((page, rel_path, mtime))

        # 2단계: 변경된 파일들의 텍스트 수집
        texts_for_embedding: list[str] = []
        page_data: list[tuple[str, dict, str, list[str], float, str]] = []
        # (rel_path, page_meta, body, links, mtime, content_hash)

        for page, rel_path, mtime in pages_to_process:
            content = page.read_text(encoding="utf-8")
            # 내용 해시: 반드시 _get_file_hash(read_bytes 기반)와 동일 방식이어야
            # 빠른 경로의 해시 비교가 일치한다. read_text 는 개행 정규화(CRLF→LF)를
            # 하므로 content.encode 로 계산하면 불일치가 생길 수 있어 raw 바이트로 해싱.
            content_hash = self._get_file_hash(page)
            page_meta, body = parse_frontmatter(content)
            title = page_meta.get("title", page.stem)
            links = self.extract_wikilinks(content)

            texts_for_embedding.append(f"{title} {body[:2000]}")
            page_data.append((rel_path, page_meta, body, links, mtime, content_hash))

        # 3단계: 배치 임베딩 (한 번에 처리)
        embeddings = []
        embed_ms = 0.0
        if texts_for_embedding:
            # show_progress_bar: 대용량 Wiki에서 진행 상황 표시
            _embed_start = time.perf_counter()
            embeddings = self.model.encode(
                texts_for_embedding,
                show_progress_bar=len(texts_for_embedding) > 10,
            )
            embed_ms = round((time.perf_counter() - _embed_start) * 1000, 1)

        # 4단계: 레코드 생성
        for i, (rel_path, page_meta, body, links, mtime, content_hash) in enumerate(page_data):
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

            # 메타 업데이트 (신규 포맷: mtime + 내용 해시)
            meta["files"][rel_path] = {"mtime": mtime, "hash": content_hash}
            updated_count += 1

        # 삭제된 파일 메타에서 제거
        deleted_paths = set(meta["files"].keys()) - current_paths
        for deleted_path in deleted_paths:
            del meta["files"][deleted_path]

        # 파일 쓰기 구간 — cross-process flock 으로 직렬화.
        # serve / daemon / CLI 가 같은 vault 에 동시에 reindex 해도 LanceDB
        # 매니페스트 race / JSON 부분 손상을 막는다. 임베딩 계산(위)은 느리지만
        # 락 밖에 두어 임계구역을 파일 쓰기 4종으로 최소화한다.
        _write_start = time.perf_counter()
        with cross_process_lock(self._reindex_lock_path) as locked:
            if not locked:
                # timeout: 다른 프로세스가 장시간 reindex 중.
                # 과거에는 경고 후 강행했으나, 그러면 이 블록의 쓰기 4종이
                # 무보호로 실행돼 LanceDB 매니페스트 race / JSON 부분 손상
                # 위험이 있었다(주석상 "전체가 flock 안"이 이 경로에서 거짓).
                # 강행 대신 쓰기를 건너뛴다. 다른 프로세스가 reindex 중이므로
                # 인덱스는 그쪽이 갱신하며, 우리가 놓친 변경분은 다음 reindex
                # 또는 호출자의 pending 처리로 흡수된다. (영구 미갱신 우려는
                # cross_process_lock 의 30s timeout 으로 정상 경로에선 거의
                # 발생하지 않는다.)
                logger.warning(
                    "reindex lock timeout; skipping writes to avoid corruption "
                    "(another process is reindexing): %s",
                    self._reindex_lock_path,
                )
                write_ms = round((time.perf_counter() - _write_start) * 1000, 1)
                duration_ms = int((time.time() - start_time) * 1000)
                record(
                    "reindex",
                    mode=mode,
                    duration_ms=duration_ms,
                    embed_ms=embed_ms,
                    write_ms=write_ms,
                    indexed=0,
                    changed=len(texts_for_embedding),
                    updated=0,
                    deleted=0,
                    skipped="lock_timeout",
                )
                return {
                    "indexed": 0,
                    "updated": 0,
                    "duration_ms": duration_ms,
                    "skipped": "lock_timeout",
                }

            # LanceDB 테이블 생성/갱신.
            # ``mode="overwrite"`` 단일 호출이 정석이지만, lancedb 일부 버전
            # (특히 0.4~0.30 범위)에서 매니페스트 상태에 따라 overwrite 인데도
            # ``Table 'wiki' already exists`` 를 던지는 회귀가 있다. 운영 로그상
            # 이 예외가 reindex 를 수천 건 막아 인덱스가 영영 갱신되지 않았다.
            #
            # 이 블록 전체가 cross-process reindex flock 안에서 실행되므로
            # drop_table + create_table 을 분리해도 다중 프로세스 race 가 없다
            # (락이 없던 과거에는 drop 직후 다른 worker 가 끼어드는 문제가 있었다).
            # 따라서 overwrite 를 먼저 시도하고, already-exists 류 실패 시
            # 명시적 drop 후 재생성으로 폴백한다.
            if records:
                self._create_or_replace_table(records)

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

        write_ms = round((time.perf_counter() - _write_start) * 1000, 1)
        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Reindex completed: indexed={len(records)}, updated={updated_count}, "
            f"deleted={len(deleted_paths)}, duration={duration_ms}ms"
        )

        # 구조화 메트릭: 단계별 timing 으로 reindex 성능을 분석 가능하게 한다.
        # changed = 이번에 실제로 재인코딩된 문서 수 (증분에서 핵심 지표).
        record(
            "reindex",
            mode=mode,
            duration_ms=duration_ms,
            embed_ms=embed_ms,
            write_ms=write_ms,
            indexed=len(records),
            changed=len(texts_for_embedding),
            updated=updated_count,
            deleted=len(deleted_paths),
        )

        return {
            "indexed": len(records),
            "updated": updated_count,
            "duration_ms": duration_ms,
        }
