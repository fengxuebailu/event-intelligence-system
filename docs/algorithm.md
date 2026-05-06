# 核心算法说明

本文档解释 Event Intelligence System 中四块核心算法的实现细节：跨语言嵌入、检索融合、事件图谱、证据约束生成，以及跨语言一致性的度量。

---

## 1. 跨语言嵌入

### 1.1 模型选型

默认模型：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

- 多语言对齐质量在 STS-Multilingual 与 Tatoeba 上均接近 LaBSE，但参数量小一个量级；
- CPU 推理 ~30 ms/句，30 事件 + 68 篇文章约 100 个文本，冷启动嵌入构建 < 5 秒；
- 输出维度 **384**，远低于 LaBSE / mpnet-base，存盘 + 内存友好。

降级链：

```
ImportError or model download fail
    ↓
TfidfVectorizer (analyzer='char_wb', ngram=(1,3))  → 字符级 n-gram
    ↓ HashingVectorizer 哈希到 384 维
    ↓ L2 归一化
```

降级嵌入对单语言检索仍有效，跨语言能力大幅退化但不会让 API 报错——这是为了在评阅环境无法联网时也能演示。

### 1.2 输入构造

| 对象     | 嵌入文本                                    |
|----------|--------------------------------------------|
| 事件     | `"{title_zh} {title_en} | {summary_zh} {summary_en}"` |
| 文章     | `"{title} {content[:512]}"`                 |
| 查询     | 用户原始 query 串                            |

事件级嵌入混合中英文本，让一个事件向量同时在中文 / 英文查询下都可被检索到，避免维护两份事件向量。

### 1.3 归一化

所有向量在写入缓存前 `v / ‖v‖_2`，相似度即 `q · v`，统一为内积运算。

---

## 2. 多维融合检索

### 2.1 评分公式

对查询 `q` 和候选事件 `e`：

```
sim_zh(q, e)   = max over (q, zh-articles of e)  cos
sim_en(q, e)   = max over (q, en-articles of e)  cos
event_sim(q,e) = cos(q, event_emb_e)
top1_article_sim(q,e) = max(sim_zh, sim_en)

Score(q, e) = 0.6 · event_sim(q, e)
            + 0.4 · top1_article_sim(q, e)
```

`0.6 / 0.4` 的权重让事件级语义占主导，但保留文章级细节决定排名分歧；权重写死在 `retrieval.py` 中，不暴露为配置以避免课程作业过度配置化。

### 2.2 跨语言证据强制约束

排序拿到 top-k 事件后，逐事件构造证据列表：

```
def gather_evidence(event_id, q):
    cands = articles_of(event_id)
    by_lang = {"zh": top_n(cands.zh, by_sim=q, n=2),
               "en": top_n(cands.en, by_sim=q, n=2)}
    if cands.zh and cands.en:
        # 强制至少 1 zh + 1 en
        evidence = by_lang["zh"][:1] + by_lang["en"][:1] + remaining_top
    else:
        evidence = top_n(cands, by_sim=q, n=3)
    return evidence
```

这条约束把"跨语言"从可有可无的副产品变成排序阶段的硬性输出契约：用户用中文查询也能看到英文证据，反之亦然。

### 2.3 复杂度

事件 30 + 文章 68 + 查询 1，朴素 cos 全量打分 `O(N · d)` ≈ 100 × 384 = 3.8 万次乘加，远低于 1 ms。无需 FAISS / HNSW 索引。

---

## 3. 事件演化图谱

### 3.1 图构建

```
G = (V, E)
V = events                              (n=30)
E = relations,  type ∈ {triggers, evolves_to, ..., spillover}  (m=27)
属性: 节点颜色 = topics[topic_id].color
      节点大小 ∝ intensity
      边样式   = 按 type 映射 (实线 / 虚线 / 颜色)
```

12 种关系类型用于刻画语义粒度 —— `triggers` 与 `escalates_to` 在前端会用不同颜色与箭头样式渲染。

### 3.2 PageRank 重要性

```
PR(v) = (1-d)/n + d · Σ_{u ∈ in(v)} PR(u) / |out(u)|
d = 0.85, 迭代 30 步, ε = 1e-6
```

输出按 topic 标准化（同主题内 max-min scaling），用于：

- 简报生成时挑选"中心事件"；
- 前端节点尺寸缩放（PageRank 与 intensity 各占一半权重）。

### 3.3 子图与演化路径

- `build_topic_subgraph(topic_id)`：保留指定 topic 内的节点 + 至少一端在该 topic 的关系。`topic_id=None` 时返回全图，但跨 topic 边会被前端用虚线标注（如 `E007 → C002` 的 spillover）。
- `get_evolution_path(event_id)`：BFS 向前 / 向后各扩展两层，返回时间轴上的事件列表（同时包含 `pre[]`、`current`、`post[]`），前端用于 Detail Drawer 的"前因后果"区块。

### 3.4 时间线密度

```
timeline = group_by_month(events)
        → [{date: "YYYY-MM",
            count: int,
            intensity_avg: float}]
```

供 Overview 页热力图与图谱页的时间筛选条用。

---

## 4. LLM 证据约束生成

### 4.1 Prompt 设计

prompt 由四块组成（按顺序拼）：

```
[SYSTEM]
You are an analyst writing a structured intelligence briefing.
Every claim MUST cite an event_id and an article_id from the given pool.
Output strict JSON matching the schema below. No extra text.

[STYLE]
- "executive": 摘要 + 关键趋势 + 风险提示  3 节
- "analytical": 背景 + 演化 + 多视角 + 推断  4 节
- "timeline": 按时间排序逐事件解读

[POOL]
events:
  - {event_id, title, date, intensity, summary}
articles (snippets ≤ 240 chars):
  - {article_id, event_id, lang, source, snippet}

[USER]
Generate a {language} briefing.
```

### 4.2 结构化输出

要求 LLM 返回：

```json
{
  "title": "...",
  "sections": [
    {
      "heading": "...",
      "content": "...",
      "citations": [
        {"event_id": "E001", "article_id": "A_E001_en1",
         "snippet": "..."}
      ]
    }
  ],
  "key_actors": ["..."],
  "timeline": [{"date": "...", "event_id": "...", "title": "..."}]
}
```

不解析 markdown / 不接受自由文本——LLM 输出无法 parse 即视作失败，走降级。

### 4.3 Snippet 校验

```
def verify(citations):
    ok = []
    for c in citations:
        article = articles_by_id.get(c["article_id"])
        if not article: continue
        # 子串匹配（去空白 / 去标点 / 去全半角）
        if normalize(c["snippet"]) in normalize(article["content"]):
            ok.append(c)
    return ok
```

校验未通过的 citation 直接丢弃；某 section 全部 citations 失效 → 该 section 整段降级为模板生成。

### 4.4 模板降级

模板按 style 写死骨架（标题 + 占位符），从 retrieval 拿 top 事件 + 第一段证据填空：

```
heading: "中美科技博弈演化"
content: "{event.title_zh}（{date}）是该主题中近期最具代表性的节点之一。"
         + "{evidence.snippet_zh}"
citations: [{event_id, article_id, snippet}]
```

模板段落自然带 citations，因此降级路径仍满足"每段必有引用"的硬性要求。

### 4.5 LLM 端点降级

```
try Anthropic     → except → try OpenAI → except → try DeepSeek → except → 模板
```

每次调用 5 秒 timeout。任何端点 401 / 429 / 网络错误立即跳到下一个，不阻塞主流程。

---

## 5. 跨语言一致性度量

### 5.1 定义

对一对中英摘要 `(z, e)`：

```
consistency(z, e) = cos(emb(z), emb(e))   ∈ [-1, 1]
clip 到 [0, 1] 后作为对该事件的一致性分。
```

### 5.2 简报级别

简报涵盖的所有事件取均值：

```
cross_lingual_consistency
  = mean over events_in_briefing  consistency(summary_zh, summary_en)
```

- > 0.8：中英摘要高度一致；
- 0.6 ~ 0.8：表述存在偏差但事实核心一致；
- < 0.6：明显视角差异，前端会高亮该事件并提示"中英叙事分歧大"。

### 5.3 双语事件对齐（`align_cross_lingual`）

```
zh_vecs = embed(zh_texts)
en_vecs = embed(en_texts)
sim     = zh_vecs @ en_vecs.T          # (Nz, Ne)
matches = []
for i in range(Nz):
    j = argmax(sim[i])
    if sim[i, j] > 0.55:
        matches.append((i, j, sim[i, j]))
```

对外输出 `(zh_idx, en_idx, similarity)` 三元组，可用于跨语言去重与"同一事件不同语种报道"聚合。
