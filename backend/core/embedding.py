"""Multilingual embedding with graceful fallback.

Tries sentence-transformers paraphrase-multilingual-MiniLM-L12-v2 first.
Falls back to a numpy-only character n-gram + hashed bag-of-words pseudo-embedding
so the project runs fully offline.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Iterable

import numpy as np

logger = logging.getLogger(__name__)

_FALLBACK_DIM = 128
_ST_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_state = {
    "backend": None,           # "st" | "fallback"
    "model": None,
    "dim": _FALLBACK_DIM,
}
_lock = threading.Lock()

_WORD_RE = re.compile(r"[\w一-鿿]+", flags=re.UNICODE)


def _try_load_sentence_transformer() -> bool:
    """Try to load sentence-transformers. Return True on success."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as e:  # ImportError or anything during import
        logger.warning("sentence-transformers unavailable (%s); using fallback embedding.", e)
        return False
    try:
        model = SentenceTransformer(_ST_MODEL_NAME)
    except Exception as e:
        logger.warning("Failed to load %s (%s); using fallback embedding.", _ST_MODEL_NAME, e)
        return False
    _state["model"] = model
    _state["backend"] = "st"
    _state["dim"] = int(model.get_sentence_embedding_dimension())
    logger.info("Loaded sentence-transformers model %s (dim=%d).", _ST_MODEL_NAME, _state["dim"])
    return True


def _ensure_loaded() -> None:
    if _state["backend"] is not None:
        return
    with _lock:
        if _state["backend"] is not None:
            return
        if not _try_load_sentence_transformer():
            _state["backend"] = "fallback"
            _state["dim"] = _FALLBACK_DIM
            logger.warning("Embedding backend = fallback (numpy hash, dim=%d).", _FALLBACK_DIM)


def get_embedding_dim() -> int:
    """Return current embedding dimension."""
    _ensure_loaded()
    return int(_state["dim"])


def get_backend() -> str:
    """Return active backend name."""
    _ensure_loaded()
    return str(_state["backend"])


# ---- fallback embedding ---------------------------------------------------

def _char_ngrams(text: str, n: int = 3) -> Iterable[str]:
    text = re.sub(r"\s+", " ", text.strip().lower())
    if len(text) < n:
        if text:
            yield text
        return
    for i in range(len(text) - n + 1):
        yield text[i : i + n]


def _hash_token(tok: str, dim: int) -> int:
    h = hashlib.md5(tok.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % dim


def _fallback_embed_one(text: str, dim: int) -> np.ndarray:
    """Hashed bag-of-features: char 3-grams + word tokens + char 4-grams."""
    vec = np.zeros(dim, dtype=np.float32)
    if not text:
        return vec
    text = text.strip()
    # word tokens (handles latin words and CJK runs)
    for tok in _WORD_RE.findall(text):
        vec[_hash_token("w:" + tok, dim)] += 1.0
        # for CJK, also add per-char unigrams
        if re.search(r"[一-鿿]", tok):
            for ch in tok:
                vec[_hash_token("c:" + ch, dim)] += 0.5
    # char n-grams
    for ng in _char_ngrams(text, 3):
        vec[_hash_token("3:" + ng, dim)] += 0.5
    for ng in _char_ngrams(text, 4):
        vec[_hash_token("4:" + ng, dim)] += 0.3
    # sublinear scaling, then L2-normalize
    vec = np.log1p(vec)
    n = np.linalg.norm(vec)
    if n > 0:
        vec = vec / n
    return vec


def _fallback_embed(texts: list[str], dim: int) -> np.ndarray:
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        out[i] = _fallback_embed_one(t or "", dim)
    return out


# ---- public API -----------------------------------------------------------

def embed_texts(texts: list[str], lang: str = "auto") -> np.ndarray:
    """Return (n, d) L2-normalized embedding matrix.

    Args:
        texts: list of strings (any language; mixed OK).
        lang: hint, currently unused but accepted for interface stability.
    """
    _ensure_loaded()
    if not texts:
        return np.zeros((0, _state["dim"]), dtype=np.float32)
    if _state["backend"] == "st":
        try:
            arr = _state["model"].encode(
                texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
            )
            return arr.astype(np.float32)
        except Exception as e:
            logger.warning("ST encode failed (%s); falling back for this batch.", e)
    return _fallback_embed(texts, _state["dim"])


def cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity for L2-normalized inputs (= dot product)."""
    if a.size == 0 or b.size == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float32)
    return a @ b.T


def detect_lang(text: str) -> str:
    """Very simple Chinese/English detector via CJK char ratio."""
    if not text:
        return "en"
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    total = sum(1 for c in text if not c.isspace())
    if total == 0:
        return "en"
    return "zh" if cjk / total > 0.2 else "en"
