# 数据 Schema 说明

数据全部以 JSON 形式存放在 `backend/data/` 下，编码 UTF-8，时间字段统一 `YYYY-MM-DD`。

---

## 1. 文件总览

| 文件                          | 内容                                | 规模                       |
|------------------------------|------------------------------------|---------------------------|
| `data/events.json`           | `topics[]` · `events[]` · `relations[]` | 5 / 30 / 27               |
| `data/articles.json`         | `articles[]`                        | 68（zh 31 / en 37）        |
| `data/embeddings.npz` (生成) | 嵌入向量缓存（events + articles）   | 自动构建，约 200 KB         |

---

## 2. `events.json`

### 2.1 顶层结构

```json
{
  "topics":    [ Topic, ... ],
  "events":    [ Event, ... ],
  "relations": [ Relation, ... ]
}
```

### 2.2 `Topic` 字段

| 字段              | 类型   | 含义                                | 示例                                          |
|------------------|--------|------------------------------------|----------------------------------------------|
| `topic_id`       | string | 主题唯一标识（小写下划线）            | `us_china_tech`                              |
| `name_zh`        | string | 中文主题名                          | `中美科技与贸易摩擦`                          |
| `name_en`        | string | 英文主题名                          | `US-China Tech and Trade Tensions`           |
| `color`          | string | ECharts 渲染主色 (#RRGGBB)          | `#FF6B6B`                                    |
| `description_zh` | string | 主题中文一句话描述                   | `围绕半导体、AI、出口管制和关税的中美科技博弈演化`|
| `description_en` | string | 主题英文一句话描述                   | `Evolution of US-China rivalry over chips...`|

### 2.3 `Event` 字段

| 字段        | 类型     | 含义                                                | 示例                                              |
|-------------|---------|----------------------------------------------------|--------------------------------------------------|
| `event_id`  | string  | 事件唯一标识，前缀对应主题：`E`/`R`/`I`/`A`/`C`        | `E001`、`R003`、`I005`、`A002`、`C004`            |
| `topic_id`  | string  | 所属主题                                            | `us_china_tech`                                  |
| `title_zh`  | string  | 中文标题                                            | `美国发布对华半导体出口管制新规`                   |
| `title_en`  | string  | 英文标题                                            | `US issues new semiconductor export controls...` |
| `summary_zh`| string  | 中文摘要（≈ 100-150 字）                            | `美国商务部宣布扩大对华半导体设备和先进芯片的出口管制...`|
| `summary_en`| string  | 英文摘要                                            | `The US Commerce Department expanded export...`  |
| `date`      | string  | 事件发生日期 `YYYY-MM-DD`                           | `2022-10-07`                                     |
| `location`  | string  | 主要地点（自由文本，可包含多地）                       | `Washington D.C.` / `Baltic Sea`                 |
| `actors`    | string[]| 主要行为者（机构 / 国家 / 人物，中英混排）              | `["美国商务部 BIS", "中国半导体企业"]`             |
| `category`  | string  | 事件类别枚举：`policy` / `diplomatic` / `conflict` / `technology` / `political` / `corporate` / `legal` / `infrastructure` / `energy` | `policy`                                          |
| `intensity` | float   | 事件强度 0-10，反映冲击规模与全球关注度                | `8.5`                                            |

`event_id` 前缀与主题对应：

| 前缀 | 主题             |
|------|------------------|
| `E`  | `us_china_tech`  |
| `R`  | `russia_ukraine` |
| `I`  | `israel_palestine` |
| `A`  | `ai_regulation`  |
| `C`  | `climate_policy` |

### 2.4 `Relation` 字段

| 字段        | 类型   | 含义                                            |
|-------------|--------|------------------------------------------------|
| `source`    | string | 起点 `event_id`                                 |
| `target`    | string | 终点 `event_id`                                 |
| `type`      | string | 关系类型枚举（见下表）                            |
| `label_zh`  | string | 中文标签（用于图边渲染）                          |
| `label_en`  | string | 英文标签                                         |

#### 关系类型枚举

| 类型                | 中文       | English             | 含义                                       |
|---------------------|-----------|---------------------|-------------------------------------------|
| `triggers`          | 引发       | triggers            | A 直接引发 B（短时间因果）                   |
| `evolves_to`        | 演化为     | evolves to          | A 长时间演变后形成 B                         |
| `expands_to`        | 扩展至     | expands to          | A 的范围/规模扩大至 B                        |
| `escalates_to`      | 升级为     | escalates to        | A 在烈度上升级为 B                           |
| `leads_to`          | 导向       | leads to            | A 是 B 的间接前提                            |
| `leads_to_response` | 引发反制   | leads to countermeasure | A 引来对手的反向措施 B                    |
| `complements`       | 强化       | complements         | A 与 B 是同向叠加关系                        |
| `contrast`          | 对照       | contrasts with      | A 与 B 形成对立或对比                        |
| `contextualizes`    | 背景化     | contextualizes      | A 为理解 B 提供必要背景                      |
| `precedes`          | 之前为     | precedes            | A 先于 B（弱因果）                           |
| `spillover`         | 外溢       | spillover           | A 跨主题/跨地域溢出影响到 B                   |
| `questioned_by`     | 被质疑     | questioned by       | A 的有效性被 B 所质疑                        |

实际仓库中 27 条关系覆盖以上全部 12 种类型。

---

## 3. `articles.json`

### 3.1 顶层结构

```json
{ "articles": [ Article, ... ] }
```

### 3.2 `Article` 字段

| 字段           | 类型   | 含义                                                | 示例                                          |
|----------------|--------|----------------------------------------------------|----------------------------------------------|
| `article_id`   | string | 文章唯一标识，格式 `A_<event_id>_<lang><idx>`        | `A_E001_zh1`、`A_E001_en2`                   |
| `event_id`     | string | 关联事件                                            | `E001`                                       |
| `lang`         | string | `"zh"` / `"en"`                                    | `"zh"`                                       |
| `source`       | string | 信源名称                                            | `新华社` / `Reuters` / `Wall Street Journal` |
| `source_type`  | string | 信源类别：`official` / `wire` / `newspaper` / `magazine` / `thinktank` / `social` | `wire`            |
| `title`        | string | 文章标题                                            | `U.S. unveils sweeping export controls...`   |
| `content`      | string | 文章正文（≈ 150-250 字 / 词，已改写避免版权问题）      | `The U.S. Commerce Department's...`          |
| `date`         | string | 发表日期 `YYYY-MM-DD`                               | `2022-10-08`                                 |
| `url`          | string | 占位 URL（仅用于前端跳转展示，非真实链接）             | `https://www.reuters.com/example/E001-en1`   |

### 3.3 文章覆盖

- 每个事件至少 2 篇配套文章，平均 2.27 篇 / 事件。
- 每个事件保证 zh 与 en 各至少 1 篇。
- 信源覆盖：新华社、人民日报、环球时报、财新、SCMP、Reuters、Bloomberg、WSJ、Financial Times、AP、AFP、官方部委公告、CSIS / RAND 等智库类。

---

## 4. 五个主题速览

| 主题             | 事件数 | 时间跨度                  | 演化主线                                      |
|------------------|--------|---------------------------|---------------------------------------------|
| 中美科技与贸易摩擦 | 10     | 2022-10 ~ 2025-01         | 出口管制 → 反制 → 关税升级 → 国产 7nm 突破 → DeepSeek 冲击 |
| 俄乌冲突         | 6      | 2022-02 ~ 2023-12         | 特别军事行动 → 西方制裁 → 北溪爆炸 → 反攻 → 瓦格纳兵变 → 援乌僵局 |
| 巴以冲突         | 5      | 2023-10 ~ 2024-04         | 哈马斯袭击 → 加沙地面行动 → 红海航运危机 → ICJ 案 → 伊以直接对峙 |
| 全球 AI 治理     | 5      | 2023-07 ~ 2024-03         | 中国管理办法 → 美国行政令 → 布莱切利峰会 → OpenAI 治理风波 → 欧盟 AI 法案 |
| 全球气候政策     | 4      | 2022-08 ~ 2024-06         | IRA 补贴 → CBAM 过渡 → COP28 共识 → 中国可再生超过煤电 |

跨主题关联示例：`E007` (美对华清洁能源关税) → `C002` (CBAM)，体现地缘政治与气候政策的交叉外溢。
