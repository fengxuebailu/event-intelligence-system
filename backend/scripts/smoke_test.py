"""Smoke test — assumes service already running on :8000."""

from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8000"


def _check(name: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f"  -- {detail}"
    print(line)
    return ok


def main() -> int:
    failed = 0
    with httpx.Client(timeout=120.0, base_url=BASE) as c:
        # 1. health
        try:
            r = c.get("/api/health")
            ok = r.status_code == 200 and r.json().get("status") == "ok"
            failed += 0 if _check("GET /api/health", ok, f"status={r.status_code}") else 1
        except Exception as e:
            failed += 1
            _check("GET /api/health", False, str(e))

        # 2. topics
        try:
            r = c.get("/api/topics")
            data = r.json()
            ok = r.status_code == 200 and len(data.get("topics", [])) >= 1
            failed += 0 if _check("GET /api/topics", ok, f"topics={len(data.get('topics',[]))}") else 1
        except Exception as e:
            failed += 1
            _check("GET /api/topics", False, str(e))

        # 3. events
        try:
            r = c.get("/api/events")
            data = r.json()
            ok = r.status_code == 200 and data.get("total", 0) >= 1
            failed += 0 if _check("GET /api/events", ok, f"total={data.get('total')}") else 1
        except Exception as e:
            failed += 1
            _check("GET /api/events", False, str(e))

        # 4. graph
        try:
            r = c.get("/api/graph", params={"topic": "us_china_tech"})
            data = r.json()
            ok = r.status_code == 200 and len(data.get("nodes", [])) >= 1 and "timeline" in data
            failed += 0 if _check("GET /api/graph?topic=us_china_tech", ok,
                                  f"nodes={len(data.get('nodes',[]))} edges={len(data.get('edges',[]))}") else 1
        except Exception as e:
            failed += 1
            _check("GET /api/graph", False, str(e))

        # 5. search
        try:
            r = c.post("/api/search", json={"query": "美国对中国半导体的出口管制", "top_k": 5})
            data = r.json()
            results = data.get("results", [])
            ok = r.status_code == 200 and len(results) >= 1
            # check cross-lingual evidence in top result
            mixed = False
            if results:
                langs = {ev.get("lang") for ev in results[0].get("evidence", [])}
                mixed = "zh" in langs and "en" in langs
            detail = f"results={len(results)} cross_lingual_top={mixed}"
            failed += 0 if _check("POST /api/search", ok, detail) else 1
        except Exception as e:
            failed += 1
            _check("POST /api/search", False, str(e))

        # 6. briefing
        try:
            r = c.post("/api/briefing", json={"topic_id": "us_china_tech", "language": "zh", "style": "executive"})
            data = r.json()
            sections = data.get("sections", [])
            citations = sum(len(s.get("citations", [])) for s in sections)
            ok = r.status_code == 200 and len(sections) >= 4 and citations >= 3
            detail = f"sections={len(sections)} citations={citations} risk={data.get('risk_score')} consistency={data.get('cross_lingual_consistency')}"
            failed += 0 if _check("POST /api/briefing", ok, detail) else 1
        except Exception as e:
            failed += 1
            _check("POST /api/briefing", False, str(e))

    print()
    if failed:
        print(f"FAILED: {failed} step(s).")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
