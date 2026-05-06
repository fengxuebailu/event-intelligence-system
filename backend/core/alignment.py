"""Cross-lingual alignment and consistency scoring."""

from __future__ import annotations

import numpy as np

from . import embedding as emb


def align_cross_lingual(zh_texts: list[str], en_texts: list[str]) -> list[tuple[int, int, float]]:
    """Greedy 1-1 alignment between zh and en text lists by cosine similarity.

    Returns list of (zh_idx, en_idx, similarity) sorted by similarity desc.
    """
    if not zh_texts or not en_texts:
        return []
    zh_emb = emb.embed_texts(zh_texts)
    en_emb = emb.embed_texts(en_texts)
    sim = zh_emb @ en_emb.T  # both L2-normalized

    pairs: list[tuple[int, int, float]] = []
    used_zh: set[int] = set()
    used_en: set[int] = set()
    flat = [
        (i, j, float(sim[i, j]))
        for i in range(sim.shape[0])
        for j in range(sim.shape[1])
    ]
    flat.sort(key=lambda x: -x[2])
    for i, j, s in flat:
        if i in used_zh or j in used_en:
            continue
        pairs.append((i, j, s))
        used_zh.add(i)
        used_en.add(j)
        if len(used_zh) == len(zh_texts) or len(used_en) == len(en_texts):
            break
    return pairs


def consistency_score(zh_text: str, en_text: str) -> float:
    """Cosine similarity between zh and en embeddings, clamped to [0,1]."""
    if not zh_text or not en_text:
        return 0.0
    e = emb.embed_texts([zh_text, en_text])
    s = float(e[0] @ e[1])
    if not np.isfinite(s):
        return 0.0
    return max(0.0, min(1.0, (s + 1.0) / 2.0)) if s < 0 else max(0.0, min(1.0, s))


def average_consistency(pairs: list[tuple[str, str]]) -> float:
    """Mean consistency over given (zh, en) text pairs."""
    if not pairs:
        return 0.0
    scores = [consistency_score(z, e) for z, e in pairs]
    return float(np.mean(scores)) if scores else 0.0
