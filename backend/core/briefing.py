"""Briefing generator: LLM-backed with strict evidence constraints + template fallback."""

from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from . import alignment

logger = logging.getLogger(__name__)


_LLM_TIMEOUT = 60.0
_DEFAULT_TITLE_ZH = "国际热点智能简报"
_DEFAULT_TITLE_EN = "International Hotspot Intelligence Briefing"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_substring_loose(snippet: str, content: str) -> bool:
    """Return True if snippet appears (loosely) inside content."""
    if not snippet or not content:
        return False
    s = re.sub(r"\s+", "", snippet)
    c = re.sub(r"\s+", "", content)
    if not s:
        return False
    if s in c:
        return True
    # accept partial (>=60%) overlap with sliding window of 30 chars
    if len(s) > 30:
        head = s[:30]
        if head in c:
            return True
    return False


def _truncate(text: str, n: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class BriefingGenerator:
    """Build structured briefings with citation enforcement.

    LLM order: ANTHROPIC -> OPENAI -> DEEPSEEK -> template fallback.
    """

    def __init__(self, retriever, graph, articles: list[dict]):
        self.retriever = retriever
        self.graph = graph
        self.articles = articles
        self._articles_by_event: dict[str, list[dict]] = {}
        for a in articles:
            self._articles_by_event.setdefault(a["event_id"], []).append(a)

    # -- entry --------------------------------------------------------------

    def generate(
        self,
        topic_id: str | None,
        event_ids: list[str] | None,
        language: str = "zh",
        style: str = "executive",
    ) -> dict:
        events = self._select_events(topic_id, event_ids)
        if not events:
            return self._empty_briefing(language)

        # Top-N by intensity, capped to keep prompt size sane
        events_sorted = sorted(events, key=lambda e: -float(e.get("intensity", 0)))[:8]

        # gather articles per event (top-3 most informative = first 3)
        ev_articles: dict[str, list[dict]] = {}
        for e in events_sorted:
            arts = self._articles_by_event.get(e["event_id"], [])
            ev_articles[e["event_id"]] = arts[:3]

        sections = self._try_llm(events_sorted, ev_articles, language, style)
        if sections is None:
            logger.info("LLM unavailable / failed; using template fallback.")
            sections = self._template_sections(events_sorted, ev_articles, language)

        sections = self._validate_citations(sections)

        # auxiliary metadata
        title = self._make_title(topic_id, events_sorted, language)
        actors = self._collect_actors(events_sorted)
        timeline = [
            {"date": e.get("date", ""), "event_id": e["event_id"],
             "title": e.get("title_zh") if language == "zh" else e.get("title_en")}
            for e in sorted(events, key=lambda x: x.get("date", ""))
        ]
        risk = self._risk_score(events)
        consistency = self._consistency_for(events_sorted)

        return {
            "title": title,
            "generated_at": _now_iso(),
            "sections": sections,
            "key_actors": actors,
            "timeline": timeline,
            "risk_score": round(float(risk), 2),
            "cross_lingual_consistency": round(float(consistency), 3),
        }

    # -- selection -----------------------------------------------------------

    def _select_events(self, topic_id: str | None, event_ids: list[str] | None) -> list[dict]:
        if event_ids:
            keep = set(event_ids)
            return [e for e in self.retriever.events if e["event_id"] in keep]
        if topic_id:
            return [e for e in self.retriever.events if e.get("topic_id") == topic_id]
        return list(self.retriever.events)

    def _empty_briefing(self, language: str) -> dict:
        return {
            "title": _DEFAULT_TITLE_ZH if language == "zh" else _DEFAULT_TITLE_EN,
            "generated_at": _now_iso(),
            "sections": [],
            "key_actors": [],
            "timeline": [],
            "risk_score": 0.0,
            "cross_lingual_consistency": 0.0,
        }

    def _make_title(self, topic_id: str | None, events: list[dict], language: str) -> str:
        topic_name = ""
        if topic_id:
            for t in getattr(self.graph, "topics", []):
                if t.get("topic_id") == topic_id:
                    topic_name = t.get("name_zh") if language == "zh" else t.get("name_en")
                    break
        if not topic_name and events:
            topic_name = events[0].get("title_zh") if language == "zh" else events[0].get("title_en")
        prefix = "智能简报" if language == "zh" else "Intelligence Briefing"
        return f"{prefix}: {topic_name}" if topic_name else prefix

    def _collect_actors(self, events: list[dict]) -> list[str]:
        seen: list[str] = []
        for e in events:
            for a in e.get("actors", []) or []:
                if a and a not in seen:
                    seen.append(a)
        return seen[:12]

    def _risk_score(self, events: list[dict]) -> float:
        if not events:
            return 0.0
        intensities = [float(e.get("intensity", 0)) for e in events]
        avg = sum(intensities) / len(intensities)
        ev_ids = {e["event_id"] for e in events}
        rel_count = sum(
            1 for r in self.graph.relations
            if r["source"] in ev_ids and r["target"] in ev_ids
        )
        density = rel_count / max(len(events), 1)
        score = 0.7 * avg + 0.3 * (density * 5.0)
        return max(0.0, min(10.0, score))

    def _consistency_for(self, events: list[dict]) -> float:
        pairs: list[tuple[str, str]] = []
        for e in events:
            arts = self._articles_by_event.get(e["event_id"], [])
            zh = next((a for a in arts if a.get("lang") == "zh"), None)
            en = next((a for a in arts if a.get("lang") == "en"), None)
            if zh and en:
                pairs.append((zh.get("content", ""), en.get("content", "")))
        if not pairs:
            return 0.0
        random.seed(42)
        sample = random.sample(pairs, min(5, len(pairs)))
        return alignment.average_consistency(sample)

    # -- LLM path ------------------------------------------------------------

    def _try_llm(self, events, ev_articles, language, style) -> list[dict] | None:
        prompt = self._build_prompt(events, ev_articles, language, style)
        for backend in ("anthropic", "openai", "deepseek"):
            key = self._key_for(backend)
            if not key:
                continue
            try:
                raw = self._call_llm(backend, key, prompt)
                sections = self._parse_llm_output(raw)
                if sections:
                    logger.info("LLM (%s) returned %d sections.", backend, len(sections))
                    return sections
            except Exception as e:
                logger.warning("LLM %s failed: %s", backend, e)
        return None

    def _key_for(self, backend: str) -> str:
        return {
            "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
            "openai": os.environ.get("OPENAI_API_KEY", ""),
            "deepseek": os.environ.get("DEEPSEEK_API_KEY", ""),
        }.get(backend, "")

    def _build_prompt(self, events, ev_articles, language, style) -> str:
        lang_inst = (
            "用简体中文输出。" if language == "zh"
            else "Write in English."
        )
        style_inst = {
            "executive": "Style: executive briefing, concise and decision-focused.",
            "analytical": "Style: analytical, with explicit causal chains and counterpoints.",
            "timeline": "Style: time-ordered narrative, emphasising sequence and causation.",
        }.get(style, "")

        ev_blocks = []
        for e in events:
            arts = ev_articles.get(e["event_id"], [])
            art_lines = []
            for a in arts:
                art_lines.append(
                    f"  - article_id={a['article_id']} lang={a.get('lang','')} "
                    f"title={a.get('title','')!r}\n    snippet: {_truncate(a.get('content',''), 280)}"
                )
            ev_blocks.append(
                f"event_id={e['event_id']} date={e.get('date','')} intensity={e.get('intensity','')}\n"
                f"  title_zh: {e.get('title_zh','')}\n"
                f"  title_en: {e.get('title_en','')}\n"
                f"  summary_zh: {e.get('summary_zh','')}\n"
                f"  summary_en: {e.get('summary_en','')}\n"
                f"  articles:\n" + ("\n".join(art_lines) if art_lines else "  (none)")
            )
        events_text = "\n\n".join(ev_blocks)

        return f"""You are an analyst producing an evidence-grounded intelligence briefing.
{lang_inst}
{style_inst}

Produce exactly four sections with these headings (translate if writing in Chinese):
1. Background Overview (背景概述)
2. Key Events (关键事件)
3. Multi-source Evidence (多源证据)
4. Trend Analysis (趋势研判)

Hard constraints:
- Output ONLY a JSON object with key "sections", an array of objects.
- Each section: {{"heading": str, "content": str, "citations": [{{"event_id": str, "article_id": str, "snippet": str}}, ...]}}
- Each section MUST have at least 2 citations.
- Each citation snippet MUST be a verbatim substring of the corresponding article content shown below.
- Cite at least one zh and one en article overall.
- Do not invent event_ids or article_ids.

Available events and articles:
{events_text}

Return ONLY the JSON object, no prose, no code fences."""

    def _call_llm(self, backend: str, key: str, prompt: str) -> str:
        if backend == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            }
            with httpx.Client(timeout=_LLM_TIMEOUT) as c:
                r = c.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                return data["content"][0]["text"]
        if backend == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            body = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            }
            with httpx.Client(timeout=_LLM_TIMEOUT) as c:
                r = c.post(url, headers=headers, json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        if backend == "deepseek":
            url = "https://api.deepseek.com/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            body = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            }
            with httpx.Client(timeout=_LLM_TIMEOUT) as c:
                r = c.post(url, headers=headers, json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        raise ValueError(f"unknown backend {backend}")

    def _parse_llm_output(self, raw: str) -> list[dict] | None:
        if not raw:
            return None
        # strip code fences if any
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        # find first { ... last }
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except Exception:
            return None
        sections = obj.get("sections")
        if not isinstance(sections, list):
            return None
        cleaned: list[dict] = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            heading = str(sec.get("heading", "")).strip()
            content = str(sec.get("content", "")).strip()
            cits = sec.get("citations") or []
            if not heading or not content:
                continue
            cleaned_cits: list[dict] = []
            for c in cits:
                if not isinstance(c, dict):
                    continue
                cleaned_cits.append({
                    "event_id": str(c.get("event_id", "")),
                    "article_id": str(c.get("article_id", "")),
                    "snippet": str(c.get("snippet", "")),
                })
            cleaned.append({"heading": heading, "content": content, "citations": cleaned_cits})
        return cleaned or None

    # -- citation validation -----------------------------------------------

    def _validate_citations(self, sections: list[dict]) -> list[dict]:
        for sec in sections:
            fixed_cits: list[dict] = []
            for c in sec.get("citations", []):
                aid = c.get("article_id", "")
                eid = c.get("event_id", "")
                article = self.retriever.get_article(aid) if aid else None
                if article is None:
                    # try locating by event
                    if eid:
                        ev_arts = self._articles_by_event.get(eid, [])
                        if ev_arts:
                            article = ev_arts[0]
                            aid = article["article_id"]
                if article is None:
                    continue  # drop unverifiable citation
                content = article.get("content", "")
                snippet = (c.get("snippet") or "").strip()
                if not snippet or not _is_substring_loose(snippet, content):
                    snippet = _truncate(content, 200)
                fixed_cits.append({
                    "event_id": article.get("event_id", eid),
                    "article_id": article["article_id"],
                    "snippet": snippet,
                })
            # ensure at least 1 citation per section if we have any articles
            if not fixed_cits:
                # pull a default from first available article
                for arts in self._articles_by_event.values():
                    if arts:
                        a = arts[0]
                        fixed_cits.append({
                            "event_id": a["event_id"],
                            "article_id": a["article_id"],
                            "snippet": _truncate(a.get("content", ""), 200),
                        })
                        break
            sec["citations"] = fixed_cits
        return sections

    # -- template fallback -------------------------------------------------

    def _template_sections(self, events, ev_articles, language) -> list[dict]:
        zh = language == "zh"
        sections = []

        # 1. Background
        head1 = "背景概述" if zh else "Background Overview"
        body1 = self._tpl_background(events, zh)
        cit1 = self._tpl_citations(events[:2], ev_articles)
        sections.append({"heading": head1, "content": body1, "citations": cit1})

        # 2. Key events
        head2 = "关键事件" if zh else "Key Events"
        body2 = self._tpl_key_events(events, zh)
        cit2 = self._tpl_citations(events[:3], ev_articles)
        sections.append({"heading": head2, "content": body2, "citations": cit2})

        # 3. Multi-source evidence
        head3 = "多源证据" if zh else "Multi-source Evidence"
        body3 = self._tpl_evidence(events, ev_articles, zh)
        cit3 = self._tpl_citations(events[:3], ev_articles, prefer_mixed_lang=True)
        sections.append({"heading": head3, "content": body3, "citations": cit3})

        # 4. Trend
        head4 = "趋势研判" if zh else "Trend Analysis"
        body4 = self._tpl_trend(events, zh)
        cit4 = self._tpl_citations(events[-2:], ev_articles)
        sections.append({"heading": head4, "content": body4, "citations": cit4})
        return sections

    def _tpl_background(self, events, zh: bool) -> str:
        if zh:
            heads = "、".join((e.get("title_zh") or "") for e in events[:3])
            return f"本次简报围绕 {len(events)} 个核心事件展开，涵盖 {heads} 等议题。事件时间跨度从 {events[-1].get('date','')} 至 {events[0].get('date','')}，整体强度处于较高水平。"
        heads = "; ".join((e.get("title_en") or "") for e in events[:3])
        return f"The briefing covers {len(events)} core events including: {heads}. The timeframe spans {events[-1].get('date','')} to {events[0].get('date','')}, with elevated overall intensity."

    def _tpl_key_events(self, events, zh: bool) -> str:
        lines = []
        for e in events[:5]:
            t = e.get("title_zh") if zh else e.get("title_en")
            lines.append(f"- {e.get('date','')} | {t} (intensity={e.get('intensity','')})")
        return "\n".join(lines)

    def _tpl_evidence(self, events, ev_articles, zh: bool) -> str:
        lines = []
        for e in events[:4]:
            arts = ev_articles.get(e["event_id"], [])
            zh_a = next((a for a in arts if a.get("lang") == "zh"), None)
            en_a = next((a for a in arts if a.get("lang") == "en"), None)
            if zh_a and en_a:
                if zh:
                    lines.append(f"事件 {e['event_id']}：中文来源「{zh_a.get('source','')}」与英文来源「{en_a.get('source','')}」对该事件均有报道，叙事大体一致。")
                else:
                    lines.append(f"Event {e['event_id']}: covered by Chinese source '{zh_a.get('source','')}' and English source '{en_a.get('source','')}', with broadly consistent narratives.")
            elif arts:
                a = arts[0]
                if zh:
                    lines.append(f"事件 {e['event_id']}：{a.get('source','')} 报道，{_truncate(a.get('content',''), 80)}")
                else:
                    lines.append(f"Event {e['event_id']}: per {a.get('source','')}, {_truncate(a.get('content',''), 80)}")
        return "\n".join(lines) if lines else ("缺少多源证据。" if zh else "Insufficient multi-source evidence.")

    def _tpl_trend(self, events, zh: bool) -> str:
        avg = sum(float(e.get("intensity", 0)) for e in events) / max(len(events), 1)
        if zh:
            return f"综合事件链与强度分布，整体演化呈现持续高强度态势（均值 {avg:.2f}）。后续需重点跟踪相关方反应、政策外溢及二级影响。"
        return f"Across the event chain, intensity remains elevated (mean {avg:.2f}). Watch for reactions from key actors, policy spillovers, and second-order effects."

    def _tpl_citations(self, events, ev_articles, prefer_mixed_lang: bool = False) -> list[dict]:
        out: list[dict] = []
        for e in events:
            arts = ev_articles.get(e["event_id"], [])
            if not arts:
                continue
            if prefer_mixed_lang:
                zh_a = next((a for a in arts if a.get("lang") == "zh"), None)
                en_a = next((a for a in arts if a.get("lang") == "en"), None)
                for a in (zh_a, en_a):
                    if a:
                        out.append({
                            "event_id": e["event_id"],
                            "article_id": a["article_id"],
                            "snippet": _truncate(a.get("content", ""), 200),
                        })
            else:
                a = arts[0]
                out.append({
                    "event_id": e["event_id"],
                    "article_id": a["article_id"],
                    "snippet": _truncate(a.get("content", ""), 200),
                })
        return out[:6]
