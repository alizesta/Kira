"""Evidence retrieval policy; performs read-only selection over storage and indexing contracts."""
from __future__ import annotations
import time
from .evidence_memory_index import needs_recall
from .evidence_memory_models import EvidenceFact

class EvidenceRetriever:
    def __init__(self, *, db_factory, lock, is_enabled, settings_getter, document_tokens, query_tokens,
                 bm25, semantic_search, embedding_config, logger, default_top_k=6, pinned_max=3,
                 min_bm25_ratio=0.35, embedding_min_cosine=0.45, rrf_k=60,
                 single_valued=(), pinned_predicates=(), uncertain_weight=0.7):
        self.db_factory, self.lock = db_factory, lock
        self.is_enabled, self.settings_getter = is_enabled, settings_getter
        self.document_tokens, self.query_tokens, self.bm25 = document_tokens, query_tokens, bm25
        self.semantic_search, self.embedding_config, self.logger = semantic_search, embedding_config, logger
        self.default_top_k, self.pinned_max = default_top_k, pinned_max
        self.min_bm25_ratio, self.embedding_min_cosine, self.rrf_k = min_bm25_ratio, embedding_min_cosine, rrf_k
        self.single_valued, self.pinned_predicates = frozenset(single_valued), frozenset(pinned_predicates)
        self.uncertain_weight = uncertain_weight

    def retrieve(self, query, limit=None, now=None) -> list[dict]:
        """Return current facts ranked by lexical/semantic relevance; no writes occur here."""
        if not self.is_enabled():
            return []
        now = time.time() if now is None else now
        settings = self.settings_getter()
        limit = int(limit or settings.get("memory_top_k") or self.default_top_k)
        query = " ".join(str(query or "").split())[:500]
        try:
            with self.lock, self.db_factory() as connection:
                rows = [
                    EvidenceFact.from_row(row).as_mapping()
                    for row in connection.execute(
                        "SELECT * FROM facts WHERE status IN ('active','uncertain') AND (valid_to IS NULL OR valid_to > ?)",
                        (now,),
                    ).fetchall()
                ]
                if not rows:
                    return []
                quotes = {
                    row["fact_id"]: row["quote"]
                    for row in connection.execute("SELECT fact_id, MIN(quote) AS quote FROM evidence GROUP BY fact_id")
                }
                changed = {}
                for row in connection.execute(
                    "SELECT subject, predicate, value FROM facts WHERE status='superseded' AND updated_at > ? ORDER BY updated_at",
                    (now - 14 * 86400,),
                ):
                    changed[(row["subject"], row["predicate"])] = row["value"]

            active_predicates = {(row["subject"], row["predicate"]) for row in rows if row["status"] == "active"}
            rows = [row for row in rows if not (
                row["status"] == "uncertain" and row["predicate"] in self.single_valued
                and (row["subject"], row["predicate"]) in active_predicates
            )]
            pinned = sorted(
                (row for row in rows if row["predicate"] in self.pinned_predicates and row["status"] == "active"),
                key=lambda row: -row["created_at"],
            )[:self.pinned_max]
            chosen = []
            if needs_recall(query):
                query_features = self.query_tokens(query)
                if query_features:
                    by_id = {row["id"]: row for row in rows}
                    documents = {row["id"]: self.document_tokens(row, quotes.get(row["id"], "")) for row in rows}
                    lexical = self.bm25(documents, query_features)
                    lexical_rank = sorted(lexical, key=lexical.get, reverse=True)
                    best = lexical[lexical_rank[0]] if lexical_rank else 0.0
                    lexical_rank = [fid for fid in lexical_rank if lexical[fid] >= self.min_bm25_ratio * best][:limit * 2]
                    semantic = self.semantic_search(query, list(by_id), self.embedding_config())
                    semantic_rank = []
                    if semantic:
                        floor = max(self.embedding_min_cosine, max(semantic.values()) - 0.15)
                        semantic_rank = [fid for fid in sorted(semantic, key=semantic.get, reverse=True)
                                         if semantic[fid] >= floor][:limit * 2]
                    fused = {}
                    for ranking in (lexical_rank, semantic_rank):
                        for position, fact_id in enumerate(ranking):
                            fused[fact_id] = fused.get(fact_id, 0.0) + 1.0 / (self.rrf_k + position + 1)
                    for fact_id in fused:
                        if by_id[fact_id]["status"] == "uncertain":
                            fused[fact_id] *= self.uncertain_weight
                    chosen = [by_id[fid] for fid in sorted(fused, key=fused.get, reverse=True)]

            output, seen = [], set()
            for row in list(pinned) + chosen:
                if row["id"] in seen or len(output) >= limit + len(pinned):
                    continue
                seen.add(row["id"])
                earlier = (
                    changed.get((row["subject"], row["predicate"]))
                    if row["predicate"] in self.single_valued and now - row["created_at"] < 14 * 86400 else None
                )
                output.append(EvidenceFact.from_row(row).retrieval_item(
                    pinned=row["predicate"] in self.pinned_predicates, earlier=earlier
                ))
            return output
        except Exception:
            self.logger.warning("Evidence-memory retrieval failed", exc_info=True)
            return []
