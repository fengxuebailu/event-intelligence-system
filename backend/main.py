"""FastAPI app: events, graph, search, briefing, stats."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.briefing import BriefingGenerator
from core.graph import EventGraph
from core.retrieval import CrossLingualRetriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("event_intel")

# -- paths ------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "data")
_EMB_PATH = os.path.join(_DATA_DIR, "embeddings.npz")
_FRONTEND_DIR = os.path.normpath(os.path.join(_HERE, "..", "frontend"))


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# -- pydantic models --------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    lang: str = "auto"
    top_k: int = 10


class BriefingRequest(BaseModel):
    topic_id: Optional[str] = None
    event_ids: Optional[List[str]] = None
    language: str = "zh"
    style: str = "executive"


# -- app + state -----------------------------------------------------------

app = FastAPI(title="Event Intel API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

state: dict[str, Any] = {}


@app.on_event("startup")
def _startup() -> None:
    events_doc = _load_json(os.path.join(_DATA_DIR, "events.json"))
    articles_doc = _load_json(os.path.join(_DATA_DIR, "articles.json"))

    topics = events_doc.get("topics", [])
    events = events_doc.get("events", [])
    relations = events_doc.get("relations", [])
    articles = articles_doc.get("articles", [])

    retriever = CrossLingualRetriever(events, articles, _EMB_PATH)
    graph = EventGraph(events, relations, topics=topics)
    briefing = BriefingGenerator(retriever, graph, articles)

    state.update({
        "topics": topics,
        "events": events,
        "events_by_id": {e["event_id"]: e for e in events},
        "relations": relations,
        "articles": articles,
        "articles_by_id": {a["article_id"]: a for a in articles},
        "retriever": retriever,
        "graph": graph,
        "briefing": briefing,
    })
    logger.info("Loaded %d topics / %d events / %d articles.",
                len(topics), len(events), len(articles))


# -- API routes -------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "events_loaded": len(state.get("events", []))}


@app.get("/api/topics")
def list_topics() -> dict:
    counts: Counter[str] = Counter(e.get("topic_id", "") for e in state["events"])
    out = []
    for t in state["topics"]:
        out.append({**t, "event_count": int(counts.get(t["topic_id"], 0))})
    return {"topics": out}


@app.get("/api/events")
def list_events(
    topic: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> dict:
    items = state["events"]
    if topic:
        items = [e for e in items if e.get("topic_id") == topic]
    if date_from:
        items = [e for e in items if (e.get("date") or "") >= date_from]
    if date_to:
        items = [e for e in items if (e.get("date") or "") <= date_to]
    return {"events": items, "total": len(items)}


@app.get("/api/events/{event_id}")
def get_event(event_id: str) -> dict:
    ev = state["events_by_id"].get(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="event not found")
    arts = state["retriever"].articles_for_event(event_id)
    related = state["graph"].related_events(event_id)
    return {"event": ev, "articles": arts, "related_events": related}


@app.get("/api/articles/{article_id}")
def get_article(article_id: str) -> dict:
    a = state["articles_by_id"].get(article_id)
    if not a:
        raise HTTPException(status_code=404, detail="article not found")
    return {"article": a}


@app.get("/api/graph")
def get_graph(topic: Optional[str] = Query(default=None)) -> dict:
    return state["graph"].build_topic_subgraph(topic)


@app.post("/api/search")
def search(req: SearchRequest) -> dict:
    if not req.query.strip():
        return {"results": []}
    results = state["retriever"].search(req.query, top_k=max(1, req.top_k), lang=req.lang)
    return {"results": results}


@app.post("/api/briefing")
def briefing(req: BriefingRequest) -> dict:
    return state["briefing"].generate(
        topic_id=req.topic_id,
        event_ids=req.event_ids,
        language=req.language,
        style=req.style,
    )


@app.get("/api/stats")
def stats() -> dict:
    events = state["events"]
    articles = state["articles"]
    langs = Counter(a.get("lang", "") for a in articles)

    counts_by_topic: Counter[str] = Counter(e.get("topic_id", "") for e in events)
    topic_distribution = []
    for t in state["topics"]:
        topic_distribution.append({
            "topic_id": t["topic_id"],
            "name_zh": t.get("name_zh", ""),
            "count": int(counts_by_topic.get(t["topic_id"], 0)),
        })

    monthly: dict[str, int] = defaultdict(int)
    for e in events:
        m = (e.get("date") or "")[:7]
        if m:
            monthly[m] += 1
    timeline_density = [{"month": m, "count": c} for m, c in sorted(monthly.items())]

    intensity_avg = (
        sum(float(e.get("intensity", 0)) for e in events) / len(events)
        if events else 0.0
    )

    by_event: dict[str, dict[str, int]] = defaultdict(lambda: {"zh": 0, "en": 0})
    for a in articles:
        by_event[a["event_id"]][a.get("lang", "")] = by_event[a["event_id"]].get(a.get("lang", ""), 0) + 1
    cross_pairs = sum(1 for v in by_event.values() if v.get("zh", 0) > 0 and v.get("en", 0) > 0)

    return {
        "total_events": len(events),
        "total_articles": len(articles),
        "languages": {"zh": int(langs.get("zh", 0)), "en": int(langs.get("en", 0))},
        "topic_distribution": topic_distribution,
        "timeline_density": timeline_density,
        "intensity_avg": round(float(intensity_avg), 3),
        "cross_lingual_pairs": int(cross_pairs),
    }


# -- static frontend (mounted last so /api routes win) ----------------------

if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="static")
else:
    logger.warning("Frontend dir not found: %s (static mount skipped).", _FRONTEND_DIR)
