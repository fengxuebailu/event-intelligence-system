"""Pre-compute embeddings.npz for events + articles."""

from __future__ import annotations

import json
import logging
import os
import sys

# allow running as `python backend/scripts/build_embeddings.py`
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from core.retrieval import CrossLingualRetriever  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_embeddings")


def main() -> int:
    data_dir = os.path.join(_BACKEND, "data")
    cache = os.path.join(data_dir, "embeddings.npz")

    with open(os.path.join(data_dir, "events.json"), "r", encoding="utf-8") as f:
        events = json.load(f)["events"]
    with open(os.path.join(data_dir, "articles.json"), "r", encoding="utf-8") as f:
        articles = json.load(f)["articles"]

    if os.path.exists(cache):
        os.remove(cache)
        logger.info("Removed stale cache.")

    retriever = CrossLingualRetriever(events, articles, cache)
    logger.info("Done. event_zh shape=%s, article shape=%s",
                retriever.event_zh.shape, retriever.article_emb.shape)
    if not os.path.exists(cache):
        logger.error("Cache not produced!")
        return 1
    size_kb = os.path.getsize(cache) / 1024.0
    logger.info("embeddings.npz written (%.1f KB).", size_kb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
