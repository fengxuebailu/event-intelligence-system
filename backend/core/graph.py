"""Event evolution graph: build subgraph + timeline + centrality."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


_DEFAULT_TOPIC_COLOR = "#94A3B8"


class EventGraph:
    """Graph over events with topic + temporal metadata.

    Designed for direct ECharts consumption.
    """

    def __init__(self, events: list[dict], relations: list[dict], topics: list[dict] | None = None):
        self.events = events
        self.relations = relations
        self.topics = topics or []
        self._by_id: dict[str, dict] = {e["event_id"]: e for e in events}
        self._topic_color: dict[str, str] = {t["topic_id"]: t.get("color", _DEFAULT_TOPIC_COLOR) for t in self.topics}

        self._out: dict[str, list[dict]] = defaultdict(list)
        self._in: dict[str, list[dict]] = defaultdict(list)
        for r in relations:
            self._out[r["source"]].append(r)
            self._in[r["target"]].append(r)

    # -- subgraph -------------------------------------------------------------

    def build_topic_subgraph(self, topic_id: str | None) -> dict:
        """Return ECharts-friendly {nodes, edges, timeline} for a topic (or all)."""
        if topic_id:
            ev_list = [e for e in self.events if e.get("topic_id") == topic_id]
        else:
            ev_list = list(self.events)
        ev_ids = {e["event_id"] for e in ev_list}

        nodes = []
        for e in ev_list:
            tid = e.get("topic_id", "")
            color = self._topic_color.get(tid, _DEFAULT_TOPIC_COLOR)
            intensity = float(e.get("intensity", 5.0))
            nodes.append({
                "id": e["event_id"],
                "label_zh": e.get("title_zh", ""),
                "label_en": e.get("title_en", ""),
                "date": e.get("date", ""),
                "topic_id": tid,
                "color": color,
                "intensity": intensity,
                "category": e.get("category", ""),
                "symbolSize": 10 + intensity * 3,
            })

        edges = []
        for r in self.relations:
            if topic_id and (r["source"] not in ev_ids or r["target"] not in ev_ids):
                continue
            edges.append({
                "source": r["source"],
                "target": r["target"],
                "type": r.get("type", ""),
                "label_zh": r.get("label_zh", ""),
                "label_en": r.get("label_en", ""),
            })

        timeline = self._monthly_timeline(ev_list)
        return {"nodes": nodes, "edges": edges, "timeline": timeline}

    def _monthly_timeline(self, events: list[dict]) -> list[dict]:
        bucket: dict[str, list[float]] = defaultdict(list)
        for e in events:
            d = (e.get("date") or "")[:7]  # YYYY-MM
            if not d:
                continue
            bucket[d].append(float(e.get("intensity", 5.0)))
        out = []
        for d in sorted(bucket.keys()):
            vals = bucket[d]
            out.append({
                "date": d,
                "count": len(vals),
                "intensity_avg": round(float(np.mean(vals)), 3),
            })
        return out

    # -- evolution path -------------------------------------------------------

    def get_evolution_path(self, event_id: str) -> list[dict]:
        """Predecessors -> current -> successors, sorted by date."""
        if event_id not in self._by_id:
            return []
        preds = [self._by_id[r["source"]] for r in self._in.get(event_id, []) if r["source"] in self._by_id]
        succs = [self._by_id[r["target"]] for r in self._out.get(event_id, []) if r["target"] in self._by_id]
        seen = set()
        path: list[dict] = []
        for e in sorted(preds, key=lambda x: x.get("date", "")):
            if e["event_id"] not in seen:
                path.append({**e, "role": "predecessor"})
                seen.add(e["event_id"])
        if event_id not in seen:
            path.append({**self._by_id[event_id], "role": "current"})
            seen.add(event_id)
        for e in sorted(succs, key=lambda x: x.get("date", "")):
            if e["event_id"] not in seen:
                path.append({**e, "role": "successor"})
                seen.add(e["event_id"])
        return path

    def related_events(self, event_id: str) -> list[dict]:
        """Direct neighbors with relation metadata."""
        out: list[dict] = []
        for r in self._out.get(event_id, []):
            other = self._by_id.get(r["target"])
            if other:
                out.append({
                    "event_id": other["event_id"],
                    "title_zh": other.get("title_zh", ""),
                    "title_en": other.get("title_en", ""),
                    "relation_type": r.get("type", ""),
                    "label_zh": r.get("label_zh", ""),
                    "label_en": r.get("label_en", ""),
                    "direction": "out",
                })
        for r in self._in.get(event_id, []):
            other = self._by_id.get(r["source"])
            if other:
                out.append({
                    "event_id": other["event_id"],
                    "title_zh": other.get("title_zh", ""),
                    "title_en": other.get("title_en", ""),
                    "relation_type": r.get("type", ""),
                    "label_zh": r.get("label_zh", ""),
                    "label_en": r.get("label_en", ""),
                    "direction": "in",
                })
        return out

    # -- centrality (PageRank via numpy power iteration) ----------------------

    def compute_centrality(self, damping: float = 0.85, iters: int = 10) -> dict[str, float]:
        ids = [e["event_id"] for e in self.events]
        n = len(ids)
        if n == 0:
            return {}
        idx = {eid: i for i, eid in enumerate(ids)}
        # build column-stochastic transition matrix M (column j: outgoing from j)
        M = np.zeros((n, n), dtype=np.float32)
        for src, edges in self._out.items():
            j = idx.get(src)
            if j is None:
                continue
            targets = [idx[r["target"]] for r in edges if r["target"] in idx]
            if not targets:
                continue
            w = 1.0 / len(targets)
            for i in targets:
                M[i, j] += w
        # dangling nodes (no out-edges) distribute uniformly
        dangling = np.array([1.0 if M[:, j].sum() == 0 else 0.0 for j in range(n)], dtype=np.float32)
        v = np.full(n, 1.0 / n, dtype=np.float32)
        teleport = np.full(n, (1.0 - damping) / n, dtype=np.float32)
        for _ in range(iters):
            v = damping * (M @ v + (dangling @ v) * (np.ones(n) / n)) + teleport
            s = v.sum()
            if s > 0:
                v = v / s
        return {ids[i]: float(v[i]) for i in range(n)}
