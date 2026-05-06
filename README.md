# Event Intelligence System

> 基于事件演化图谱与跨语言证据约束的国际热点智能简报系统
>
> An event-graph-driven, cross-lingual evidence-grounded briefing system for international hotspots.

本项目针对国际新闻数据规模大、语种异构、演化关系复杂的问题，构建一条从原始多语种新闻到结构化简报的端到端流水线：跨语言嵌入与检索、事件演化图谱挖掘、证据约束的 LLM 简报生成、可视化前端联动展示。课程作业版本随仓库内置 5 个主题、30 个事件、68 篇中英新闻原文，可在不调用外部 LLM 的前提下完整离线运行。

---

## 核心特性

- **跨语言检索**：中英双语查询统一映射到同一语义空间，结果同时返回中英证据片段，并强制至少一个反向语言证据，避免单语言信息茧房。
- **事件演化图谱**：以事件为节点、12 种演化关系为边，支持时间过滤、主题子图、PageRank 中心性与演化路径回放。
- **证据约束简报**：结构化生成的每一段都需要 `(event_id, article_id, snippet)` 三元组引用，未命中证据的段落会被模板降级替换，杜绝 LLM 凭空捏造。
- **离线降级链路**：嵌入模型、对齐器、简报生成都设计了降级路径——无 GPU、无 API key、无网络也能跑出可解释结果。
- **零构建前端**：单页 dashboard，Tailwind + Alpine.js + ECharts CDN，无 npm，无 webpack，刷新即可演示。
- **课程导向**：覆盖采集、嵌入、检索、挖掘、可视化五条线，对应"大数据处理"教学大纲。

---

## 系统架构

```
┌────────────────────────────────────────────────────────────────────┐
│                          Browser (Single Page)                     │
│   Overview · Event Graph · Cross-lingual Search · Briefing · Detail│
│             Tailwind CDN + Alpine.js + ECharts CDN                 │
└──────────────┬─────────────────────────────────────────────────────┘
               │  fetch / POST  (JSON)
               ▼
┌────────────────────────────────────────────────────────────────────┐
│                        FastAPI  (port 8000)                        │
│  /api/topics  /api/events  /api/graph  /api/search  /api/briefing  │
│                          /api/stats  /api/articles                 │
└──────────────┬─────────────────────────────────────────────────────┘
               │
       ┌───────┴────────┬───────────┬────────────┬──────────────┐
       ▼                ▼           ▼            ▼              ▼
 ┌───────────┐   ┌────────────┐ ┌────────┐ ┌───────────┐ ┌────────────┐
 │ embedding │──▶│ retrieval  │ │ graph  │ │ alignment │ │  briefing  │
 │  (multi-  │   │  (cross-   │ │ (event │ │  (zh ↔ en │ │  (LLM +    │
 │ lingual)  │   │   lingual) │ │ DAG +  │ │  bipartite│ │  evidence  │
 │           │   │            │ │ PageRk)│ │  matching)│ │  guard)    │
 └─────┬─────┘   └─────┬──────┘ └───┬────┘ └─────┬─────┘ └──────┬─────┘
       │               │            │            │              │
       └───────────────┴────────────┴────────────┴──────────────┘
                                    │
                                    ▼
                ┌──────────────────────────────────────┐
                │  data/events.json   data/articles.json│
                │  embeddings.npz (built on first run) │
                └──────────────────────────────────────┘
```

数据流（一次检索请求）：
`browser → POST /api/search → CrossLingualRetriever.search → embedding lookup → cosine top-k → 跨语言证据强制 → 返回中英对照 + 高亮片段 → 前端并排渲染`

---

## 快速开始

```bash
# Windows
scripts\run.bat

# Linux / macOS
bash scripts/run.sh
```

或手动三行启动：

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

服务起来后浏览器打开 <http://localhost:8000>，前端由 FastAPI 静态托管，无需另起 dev server。

烟雾测试：

```bash
python -m backend.scripts.smoke_test
```

预期：所有端点返回 200，简报包含 ≥ 3 条引用，跨语言搜索同时返回 zh + en 证据。

---

## 数据说明

仓库自带的语料覆盖近三年最具代表性的 5 个国际热点主题：

| topic_id          | 主题             | Topic                          | 事件数 |
|-------------------|------------------|--------------------------------|-------|
| `us_china_tech`   | 中美科技与贸易摩擦 | US-China Tech and Trade        | 10    |
| `russia_ukraine`  | 俄乌冲突         | Russia-Ukraine Conflict        | 6     |
| `israel_palestine`| 巴以冲突         | Israel-Palestine Conflict      | 5     |
| `ai_regulation`   | 全球 AI 治理     | Global AI Governance           | 5     |
| `climate_policy`  | 全球气候政策     | Global Climate Policy          | 4     |

总计 **30 个事件 / 27 条演化关系 / 68 篇新闻原文**（中文 31 / 英文 37），来源覆盖新华社、Reuters、WSJ、Bloomberg、FT、SCMP、财新、环球时报、官方部委公告等。每个事件至少配 2 个语种、≥ 2 个独立信源的证据。

详细 schema 与字段含义见 [`docs/data_schema.md`](docs/data_schema.md)。

---

## 技术栈

| 层级       | 选型                                                                  |
|------------|----------------------------------------------------------------------|
| 前端       | Tailwind CSS (CDN) · Alpine.js · ECharts · Inter / Noto Sans SC       |
| 后端       | FastAPI 0.115 · Uvicorn · Pydantic v2                                 |
| 数据/算法  | NumPy · scikit-learn · sentence-transformers (paraphrase-MPNet/MiniLM)|
| LLM 接入   | Anthropic / OpenAI / DeepSeek HTTP API（可选，全部失败时降级模板）       |
| 存储       | 纯 JSON + 缓存的 `embeddings.npz`，无需数据库                            |

---

## 核心算法（详见 [`docs/algorithm.md`](docs/algorithm.md)）

- **跨语言嵌入**：默认 `paraphrase-multilingual-MiniLM-L12-v2`（384 维），不可用时降级为 TF-IDF + 哈希伪嵌入。所有向量 L2 归一化后用点积近似余弦相似度。
- **多维融合检索**：
  ```
  Score(query, event) = 0.6 · max(sim_zh, sim_en) + 0.4 · top1_article_sim
  s.t.  evidence 必须同时包含 zh 与 en 两种语言（若该事件存在两种语言文章）
  ```
- **事件演化图谱**：以事件为节点、12 种关系类型为有向边，PageRank 计算重要性排序，子图按 topic 切分，演化路径用 BFS 回溯前驱与后继。
- **LLM 证据约束生成**：prompt 中先注入候选事件 + 文章 snippet，要求 structured JSON 输出 `{heading, content, citations[]}`；后置校验每个 citation 必须能在 articles.json 中找到匹配的子串，否则该段降级为模板生成。

---

## API 端点速查

| 方法 | 路径                       | 用途                              |
|------|----------------------------|----------------------------------|
| GET  | `/api/topics`              | 列出全部主题                       |
| GET  | `/api/events`              | 按 `topic` / `date_from` / `date_to` 过滤事件 |
| GET  | `/api/events/{event_id}`   | 单事件详情、文章、关联事件          |
| GET  | `/api/graph?topic=...`     | 事件图（节点 + 边 + 时间线密度）     |
| POST | `/api/search`              | 跨语言检索，返回事件 + 证据片段      |
| POST | `/api/briefing`            | 生成结构化简报（含引用与一致性分）   |
| GET  | `/api/stats`               | 全局统计与时间线密度                |
| GET  | `/api/articles/{id}`       | 单篇文章原文                       |

完整请求/响应字段见 [`INTERFACE.md`](INTERFACE.md)。

---

## 项目结构

```
event_intel_system/
├── README.md
├── INTERFACE.md                 # 接口契约（前后端共享）
├── .gitignore
├── docs/
│   ├── architecture.md          # 系统架构设计
│   ├── data_schema.md           # 数据 schema 说明
│   ├── algorithm.md             # 核心算法细节
│   └── presentation.md          # 答辩讲稿（12 分钟）
├── scripts/
│   ├── run.bat                  # Windows 一键启动
│   └── run.sh                   # Linux / macOS 一键启动
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── requirements.txt
│   ├── core/
│   │   ├── embedding.py         # 多语言嵌入 + 降级
│   │   ├── retrieval.py         # 跨语言检索
│   │   ├── alignment.py         # zh ↔ en 对齐与一致性
│   │   ├── graph.py             # 事件图谱与中心性
│   │   └── briefing.py          # 证据约束简报生成
│   ├── data/
│   │   ├── events.json          # 主题 / 事件 / 关系
│   │   └── articles.json        # 中英新闻原文
│   └── scripts/
│       ├── build_embeddings.py  # 离线构建嵌入缓存
│       └── smoke_test.py        # 端到端冒烟测试
└── frontend/
    ├── index.html
    └── assets/                  # 自定义样式与图标
```

---

## 课程结合点

围绕"大数据处理"课程的五条主线对应实现：

- **采集**：跨主题多源（官媒 / 通讯社 / 财经 / 智库）的中英文新闻原文，模拟真实情报场景下的非结构化输入。
- **预处理与嵌入**：多语言 sentence transformer 把异构语种映射到同一稠密向量空间，离线降级保证可复现。
- **检索**：跨语言融合打分 + 证据强制约束，回应"如何在大数据中找到对的那一条"。
- **挖掘**：事件演化图谱 + PageRank 中心性 + 子图抽取，把零散事件织成可解释的演化网络。
- **可视化**：force-directed 图、热力日历、跨语言并排列表、引用回链原文，呈现"看得见的数据洞察"。

---

## 致谢

本项目作为北京理工大学计算机学院"大数据处理"课程作业完成，特别感谢张华平老师在情报智能分析、大数据搜索与挖掘、多语种信息处理方向的课程指导。系统设计在"以事件为单位组织非结构化文本"这一思路上参考了 NLPIR-Parser 关于实体抽取与关系挖掘的工程经验。

引用风格上预留 `[Zhang et al., YYYY]` 占位符，实际答辩前请补充对应论文的完整出处。

---

## License

仓库内容供课程评阅使用，新闻原文片段经过改写以避免版权问题，URL 字段为示例占位。如需再分发请保留致谢与本说明文件。
