# 接口契约（前后端共享，不许偏离）

## 项目根目录

`d:/Shortcut/new_file/thirdgradedown/大数据处理/event_intel_system/`

## 数据文件（已就绪）

- `backend/data/events.json` — `{ topics: [...], events: [...], relations: [...] }`
- `backend/data/articles.json` — `{ articles: [...] }`

详细字段见这两个 JSON 文件的实际内容。**事件 id 形如 `E001` / `R001` / `I001` / `A001` / `C001`**，文章 id 形如 `A_E001_zh1`。

## REST API 端点（FastAPI，端口 8000）

```
GET  /api/topics
  → { topics: [{topic_id, name_zh, name_en, color, description_zh, description_en, event_count}] }

GET  /api/events?topic=<topic_id>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
  → { events: [...events...], total: int }

GET  /api/events/{event_id}
  → { event: {...}, articles: [...], related_events: [{event_id, title_zh, title_en, relation_type, label_zh, label_en, direction}] }

GET  /api/graph?topic=<topic_id>
  → {
      nodes: [{id, label_zh, label_en, date, topic_id, color, intensity, category}],
      edges: [{source, target, type, label_zh, label_en}],
      timeline: [{date, count, intensity_avg}]
    }

POST /api/search
  body: { query: str, lang: "zh"|"en"|"auto", top_k: int=10 }
  → { results: [{event_id, title_zh, title_en, summary_zh, summary_en, score, evidence: [{article_id, lang, snippet, score}]}] }

POST /api/briefing
  body: { topic_id?: str, event_ids?: [str], language: "zh"|"en"="zh", style: "executive"|"analytical"|"timeline"="executive" }
  → {
      title: str,
      generated_at: str (ISO datetime),
      sections: [
        { heading: str, content: str, citations: [{event_id, article_id, snippet}] }
      ],
      key_actors: [str],
      timeline: [{date, event_id, title}],
      risk_score: float (0-10),
      cross_lingual_consistency: float (0-1)
    }

GET  /api/stats
  → {
      total_events: int,
      total_articles: int,
      languages: {zh: int, en: int},
      topic_distribution: [{topic_id, name_zh, count}],
      timeline_density: [{month: "YYYY-MM", count}],
      intensity_avg: float,
      cross_lingual_pairs: int
    }

GET  /api/articles/{article_id}
  → { article: {...} }
```

## 后端 Python 模块（位于 `backend/core/`）

```python
# embedding.py
def embed_texts(texts: list[str], lang: str = "auto") -> np.ndarray:
    """返回 (n, d) 嵌入矩阵。优先用 sentence-transformers paraphrase-multilingual-MiniLM-L12-v2；
    若不可用，降级使用基于 TF-IDF + 哈希的多语言伪嵌入（保证项目能离线运行）。"""

def get_embedding_dim() -> int: ...

# retrieval.py
class CrossLingualRetriever:
    def __init__(self, events, articles, embeddings_cache_path: str): ...
    def search(self, query: str, top_k: int = 10, lang: str = "auto") -> list[dict]:
        """返回 [{event_id, score, evidence: [{article_id, lang, snippet, score}]}]"""
    def find_evidence(self, claim: str, candidate_event_ids: list[str], top_k: int = 3) -> list[dict]: ...

# alignment.py
def align_cross_lingual(zh_texts: list[str], en_texts: list[str]) -> list[tuple[int, int, float]]:
    """返回 [(zh_idx, en_idx, similarity)] 跨语言对齐结果。"""
def consistency_score(zh_text: str, en_text: str) -> float: ...

# graph.py
class EventGraph:
    def __init__(self, events, relations): ...
    def build_topic_subgraph(self, topic_id: str | None) -> dict:
        """返回 {nodes, edges, timeline} 用于前端 ECharts 渲染。"""
    def get_evolution_path(self, event_id: str) -> list[dict]:
        """返回该事件的演化路径（前置→当前→后续）。"""
    def compute_centrality(self) -> dict[str, float]: ...

# briefing.py
class BriefingGenerator:
    def __init__(self, retriever, graph, articles): ...
    def generate(self, topic_id: str | None, event_ids: list[str] | None,
                 language: str, style: str) -> dict:
        """返回结构化简报（见 API /briefing 响应）。
        强约束：每个 section 必须有 citations，引用必须能从 articles 中找到。
        优先尝试 LLM (Anthropic / OpenAI / DeepSeek API)，失败时降级到模板生成。"""
```

## 前端要求

- 单页 dashboard，技术栈：Tailwind CDN + Alpine.js + ECharts CDN，**不引入构建工具**。
- 设计语言：现代专业，**浅色主题**（白底 + 深灰文字 + teal/orange 点缀），参考 Linear / Vercel / Stripe Dashboard。
- 字体：Inter（西文）+ 思源黑体（中文）通过 Google Fonts CDN 引入。
- 视觉层次：克制留白、卡片式布局、清晰的 typography hierarchy。
- 主要 view：
  1. **Overview**（顶部统计卡片 + 全局事件密度热力图 + 主题分布饼图）
  2. **Event Graph**（ECharts force-directed 图，节点按 topic 着色，边按类型）
  3. **Cross-lingual Search**（搜索框 + 中英文结果并排展示 + 证据高亮）
  4. **Briefing Generator**（选 topic/事件 → 生成结构化简报，引用可点击跳到原文）
  5. **Event Detail Drawer**（点击节点弹出，显示中英对照标题/摘要 + 多源证据 + 相关事件）
- 颜色规范：主色 `#0ea5e9`（teal），强调色 `#f97316`（orange），背景 `#fafafa`，卡片 `#ffffff`，边框 `#e5e7eb`，文字 `#111827`。
- 所有页面间通过 tab 切换，无路由。
- 图表标题、控件、提示文案必须中英双语支持（按右上角语言切换）。

## 启动方式

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# 浏览器访问 http://localhost:8000  (FastAPI 静态托管前端)
```

## 测试入口

```bash
python -m backend.scripts.smoke_test
# 预期：所有端点返回 200，简报包含 ≥3 个引用，跨语言搜索能同时返回 zh+en 证据
```
