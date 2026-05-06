"""Cross-lingual retrieval over events + articles."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from . import embedding as emb

logger = logging.getLogger(__name__)


def _snippet(text: str, max_chars: int = 220) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


class CrossLingualRetriever:
    """Encode events (zh / en) and articles, then rank by fused cosine similarity."""

    def __init__(self, events: list[dict], articles: list[dict], embeddings_cache_path: str):
        self.events = events
        self.articles = articles
        self.cache_path = embeddings_cache_path
        self.event_ids: list[str] = [e["event_id"] for e in events]
        self.article_ids: list[str] = [a["article_id"] for a in articles]

        self._event_id_to_idx = {eid: i for i, eid in enumerate(self.event_ids)}
        self._article_id_to_idx = {aid: i for i, aid in enumerate(self.article_ids)}
        self._articles_by_event: dict[str, list[int]] = {}
        for i, a in enumerate(articles):
            self._articles_by_event.setdefault(a["event_id"], []).append(i)

        self.event_zh: np.ndarray | None = None
        self.event_en: np.ndarray | None = None
        self.article_emb: np.ndarray | None = None

        self._load_or_build()

    # -- embedding cache ---------------------------------------------------

    def _event_zh_text(self, e: dict) -> str:
        return f"{e.get('title_zh','')} {e.get('summary_zh','')}".strip()

    def _event_en_text(self, e: dict) -> str:
        return f"{e.get('title_en','')} {e.get('summary_en','')}".strip()

    def _article_text(self, a: dict) -> str:
        return f"{a.get('title','')} {a.get('content','')}".strip()

    def _load_or_build(self) -> None:
        if os.path.exists(self.cache_path):
            try:
                data = np.load(self.cache_path, allow_pickle=False)
                cached_event_ids = list(data["event_ids"])
                cached_article_ids = list(data["article_ids"])
                if cached_event_ids == self.event_ids and cached_article_ids == self.article_ids:
                    self.event_zh = data["event_zh"].astype(np.float32)
                    self.event_en = data["event_en"].astype(np.float32)
                    self.article_emb = data["article"].astype(np.float32)
                    logger.info("Loaded embeddings cache (%s).", self.cache_path)
                    return
                logger.warning("Cache id mismatch; rebuilding embeddings.")
            except Exception as e:
                logger.warning("Cache load failed (%s); rebuilding.", e)
        self._build_and_save()

    def _build_and_save(self) -> None:
        logger.info("Computing embeddings (%d events, %d articles)...", len(self.events), len(self.articles))
        self.event_zh = emb.embed_texts([self._event_zh_text(e) for e in self.events])
        self.event_en = emb.embed_texts([self._event_en_text(e) for e in self.events])
        self.article_emb = emb.embed_texts([self._article_text(a) for a in self.articles])
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            np.savez(
                self.cache_path,
                event_zh=self.event_zh,
                event_en=self.event_en,
                article=self.article_emb,
                event_ids=np.array(self.event_ids, dtype=object),
                article_ids=np.array(self.article_ids, dtype=object),
            )
            logger.info("Saved embeddings cache to %s.", self.cache_path)
        except Exception as e:
            logger.warning("Cache save failed (%s).", e)

    # -- public --------------------------------------------------------------

    def search(self, query: str, top_k: int = 10, lang: str = "auto") -> list[dict]:
        """Search events fused by zh/en event similarity + best article similarity.

        evidence guarantees at least one zh + one en when both are available.
        """
        if not query.strip():
            return []
        if lang == "auto":
            lang = emb.detect_lang(query)

        q = emb.embed_texts([query])  # (1, d)
        q_vec = q[0]
        zh_sim = self.event_zh @ q_vec  # (n_events,)
        en_sim = self.event_en @ q_vec
        art_sim = self.article_emb @ q_vec  # (n_articles,)

        # per-event best article score
        ev_top_art_score = np.zeros(len(self.events), dtype=np.float32)
        ev_top_art_idx: list[int] = [-1] * len(self.events)
        for i, eid in enumerate(self.event_ids):
            idxs = self._articles_by_event.get(eid, [])
            if not idxs:
                continue
            best = max(idxs, key=lambda j: art_sim[j])
            ev_top_art_score[i] = float(art_sim[best])
            ev_top_art_idx[i] = best

        ev_text_score = np.maximum(zh_sim, en_sim)
        fused = 0.6 * ev_text_score + 0.4 * ev_top_art_score
        order = np.argsort(-fused)[: max(top_k, 1)]

        results: list[dict] = []
        for i in order:
            i = int(i)
            if fused[i] <= 0:
                break
            evidence = self._collect_evidence(i, art_sim, top_k_per_event=3)
            event = self.events[i]
            results.append({
                "event_id": event["event_id"],
                "score": float(fused[i]),
                "evidence": evidence,
                # convenience copies (used by /api/search route)
                "title_zh": event.get("title_zh", ""),
                "title_en": event.get("title_en", ""),
                "summary_zh": event.get("summary_zh", ""),
                "summary_en": event.get("summary_en", ""),
            })
        return results

    def _collect_evidence(self, event_idx: int, art_sim: np.ndarray, top_k_per_event: int = 3) -> list[dict]:
        """Pick top articles for this event; ensure at least one zh + one en if available."""
        eid = self.event_ids[event_idx]
        idxs = self._articles_by_event.get(eid, [])
        if not idxs:
            return []
        ranked = sorted(idxs, key=lambda j: -float(art_sim[j]))
        chosen: list[int] = []
        # pre-pick best zh and best en if any exists
        best_zh = next((j for j in ranked if self.articles[j].get("lang") == "zh"), None)
        best_en = next((j for j in ranked if self.articles[j].get("lang") == "en"), None)
        for j in (best_zh, best_en):
            if j is not None and j not in chosen:
                chosen.append(j)
        for j in ranked:
            if len(chosen) >= top_k_per_event:
                break
            if j not in chosen:
                chosen.append(j)

        out: list[dict] = []
        for j in chosen[:top_k_per_event]:
            a = self.articles[j]
            out.append({
                "article_id": a["article_id"],
                "lang": a.get("lang", ""),
                "snippet": _snippet(a.get("content", "")),
                "score": float(art_sim[j]),
            })
        return out

    def find_evidence(self, claim: str, candidate_event_ids: list[str], top_k: int = 3) -> list[dict]:
        """Find article-level evidence for a claim restricted to given events."""
        if not claim.strip() or not candidate_event_ids:
            return []
        q = emb.embed_texts([claim])[0]
        cand_article_idxs: list[int] = []
        for eid in candidate_event_ids:
            cand_article_idxs.extend(self._articles_by_event.get(eid, []))
        if not cand_article_idxs:
            return []
        sims = self.article_emb[cand_article_idxs] @ q
        order = np.argsort(-sims)
        # ensure mixed languages when possible
        chosen: list[int] = []
        for want_lang in ("zh", "en"):
            for k in order:
                j = cand_article_idxs[int(k)]
                if self.articles[j].get("lang") == want_lang and j not in chosen:
                    chosen.append(j)
                    break
        for k in order:
            if len(chosen) >= top_k:
                break
            j = cand_article_idxs[int(k)]
            if j not in chosen:
                chosen.append(j)
        out: list[dict] = []
        for j in chosen[:top_k]:
            a = self.articles[j]
            sim = float(self.article_emb[j] @ q)
            out.append({
                "article_id": a["article_id"],
                "event_id": a["event_id"],
                "lang": a.get("lang", ""),
                "snippet": _snippet(a.get("content", "")),
                "score": sim,
            })
        return out

    # -- helpers used by other modules --------------------------------------

    def get_article(self, article_id: str) -> dict | None:
        idx = self._article_id_to_idx.get(article_id)
        return self.articles[idx] if idx is not None else None

    def articles_for_event(self, event_id: str) -> list[dict]:
        return [self.articles[i] for i in self._articles_by_event.get(event_id, [])]

    def article_embedding(self, article_id: str) -> np.ndarray | None:
        idx = self._article_id_to_idx.get(article_id)
        if idx is None or self.article_emb is None:
            return None
        return self.article_emb[idx]
