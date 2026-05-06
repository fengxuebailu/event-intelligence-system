/* Event Intelligence Dashboard — vanilla + Alpine */
'use strict';

const API_BASE = ''; // same-origin; backend serves frontend via StaticFiles

async function apiCall(path, opts = {}) {
  const url = API_BASE + path;
  const init = { headers: { 'Content-Type': 'application/json' }, ...opts };
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json();
}

// ECharts axis/tooltip light theme defaults
const ECHARTS_TEXT = { color: '#374151', fontFamily: 'Inter, "Noto Sans SC", sans-serif' };
const ECHARTS_TOOLTIP_BASE = {
  backgroundColor: 'rgba(255,255,255,0.98)',
  borderColor: '#e5e7eb',
  borderWidth: 1,
  textStyle: { color: '#111827', fontSize: 12, fontFamily: ECHARTS_TEXT.fontFamily },
  extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.06); border-radius: 8px; padding: 8px 10px;'
};

// Edge-type → color map for graph edges
const EDGE_COLORS = {
  triggers: '#f97316',
  expands_to: '#0ea5e9',
  evolves_to: '#8b5cf6',
  leads_to: '#0ea5e9',
  leads_to_response: '#ef4444',
  precedes: '#94a3b8',
  contextualizes: '#64748b',
  complements: '#14b8a6',
  contrast: '#f43f5e',
  spillover: '#a3a3a3',
  questioned_by: '#eab308',
  escalates_to: '#dc2626'
};

function dashboard() {
  return {
    // ----- state -----
    lang: 'zh',
    dark: false,
    apiOk: true,
    view: 'overview',
    tabs: [
      { id: 'overview', label_zh: '总览', label_en: 'Overview', title_zh: '总览', title_en: 'Overview', desc_zh: '事件情报全局视图：主题分布、密度趋势与重大事件。', desc_en: 'Global view: topic mix, density trend and major events.' },
      { id: 'graph', label_zh: '事件图谱', label_en: 'Event Graph', title_zh: '事件演化图谱', title_en: 'Event Evolution Graph', desc_zh: '按主题查看事件之间的因果与演化关系。', desc_en: 'Explore causal and evolutionary relations by topic.' },
      { id: 'search', label_zh: '跨语言搜索', label_en: 'Search', title_zh: '跨语言证据搜索', title_en: 'Cross-lingual Evidence Search', desc_zh: '用一种语言查询，同时返回中英文证据片段。', desc_en: 'Query once, retrieve aligned Chinese & English evidence.' },
      { id: 'briefing', label_zh: '智能简报', label_en: 'Briefing', title_zh: '证据约束智能简报', title_en: 'Evidence-grounded Briefing', desc_zh: '由检索到的事实生成结构化简报，每条结论可追溯。', desc_en: 'Structured briefings grounded in retrieved evidence.' }
    ],
    get currentTab() { return this.tabs.find(t => t.id === this.view) || this.tabs[0]; },

    // overview
    stats: null,
    topics: [],
    topEvents: [],

    // graph
    selectedTopic: null,
    graphLoading: false,
    _graphChart: null,
    _timelineChart: null,
    _pieChart: null,
    _heatChart: null,

    // search
    searchQuery: '',
    searchLoading: false,
    searchResults: [],
    sampleQueries: {
      zh: ['半导体出口管制', 'DeepSeek 与算力封锁', 'AI 监管立法', '俄乌制裁'],
      en: ['semiconductor export controls', 'DeepSeek and compute', 'AI regulation', 'Russia sanctions']
    },

    // briefing
    brief: { topic: null, language: 'zh', style: 'executive' },
    briefLoading: false,
    briefResult: null,

    // drawer
    drawer: { open: false, loading: false, event: null, articles: [], related: [], summaryTab: 'zh' },

    // ----- computed -----
    get statCards() {
      const s = this.stats || {};
      return [
        { label_zh: '总事件数', label_en: 'Total events', icon: 'activity', value: s.total_events ?? '—', hint_zh: '已结构化的事件节点', hint_en: 'structured event nodes' },
        { label_zh: '总文章数', label_en: 'Total articles', icon: 'file-text', value: s.total_articles ?? '—', hint_zh: '中英多源原文', hint_en: 'multi-source articles' },
        { label_zh: '中英语言对', label_en: 'ZH / EN pairs', icon: 'languages', value: s.cross_lingual_pairs ?? '—', hint_zh: '跨语言对齐数量', hint_en: 'aligned cross-lingual pairs' },
        { label_zh: '主题数', label_en: 'Topics', icon: 'layers', value: (s.topic_distribution?.length ?? this.topics.length) || '—', hint_zh: '事件主题集合', hint_en: 'topic clusters' }
      ];
    },

    // ----- init -----
    async init() {
      const validViews = this.tabs.map(t => t.id);
      const parseHash = () => {
        const raw = (location.hash || '').replace(/^#/, '');
        const [view, qs] = raw.split('?');
        const params = new URLSearchParams(qs || '');
        return { view, params };
      };
      const initial = parseHash();
      if (validViews.includes(initial.view)) this.view = initial.view;
      this._pendingHashParams = initial.params;
      this.$watch('view', (v) => { history.replaceState(null, '', '#' + v); this.afterTabChange(); });
      this.$watch('lang', () => { this.refreshIcons(); this.rerenderActiveCharts(); });
      window.addEventListener('hashchange', () => {
        const h = parseHash();
        if (validViews.includes(h.view) && h.view !== this.view) {
          this._pendingHashParams = h.params;
          this.view = h.view;
        }
      });
      await this.checkHealth();
      if (this.apiOk) await this.loadOverview();
      if (this.view !== 'overview') this.$nextTick(() => this.afterTabChange());
      else this.applyHashParams();
      this.refreshIcons();
    },

    applyHashParams() {
      const p = this._pendingHashParams;
      if (!p) return;
      this._pendingHashParams = null;
      if (this.view === 'search' && p.get('q')) {
        this.searchQuery = p.get('q');
        this.runSearch();
      } else if (this.view === 'briefing' && (p.get('topic') || p.get('auto'))) {
        if (p.get('topic')) this.brief.topic = p.get('topic');
        if (p.get('lang')) this.brief.language = p.get('lang');
        if (p.get('style')) this.brief.style = p.get('style');
        this.generateBriefing();
      } else if (this.view === 'graph' && p.get('topic')) {
        this.selectedTopic = p.get('topic');
      }
      if (p.get('event')) this.openDetail(p.get('event'));
    },

    refreshIcons() { this.$nextTick(() => { try { window.lucide?.createIcons(); } catch (e) {} }); },

    async checkHealth() {
      try {
        const s = await apiCall('/api/stats');
        this.stats = s;
        this.apiOk = true;
        return true;
      } catch (e) {
        console.warn('API not reachable:', e.message);
        this.apiOk = false;
        return false;
      }
    },

    async afterTabChange() {
      this.refreshIcons();
      if (!this.apiOk) await this.checkHealth();
      if (!this.apiOk) return;
      if (this.view === 'overview') {
        if (!this.topics.length) await this.loadOverview();
        this.$nextTick(() => this.renderOverviewCharts());
      } else if (this.view === 'graph') {
        if (!this.topics.length) await this.loadOverview();
        this.$nextTick(() => this.renderGraph());
      }
      this.applyHashParams();
    },

    // ----- data loading -----
    async loadOverview() {
      try {
        const [stats, topicsResp, eventsResp] = await Promise.all([
          this.stats ? Promise.resolve(this.stats) : apiCall('/api/stats'),
          apiCall('/api/topics'),
          apiCall('/api/events')
        ]);
        this.stats = stats;
        this.topics = topicsResp.topics || [];
        const events = (eventsResp.events || []).slice().sort((a, b) => (b.intensity || 0) - (a.intensity || 0));
        this.topEvents = events.slice(0, 8);
        this.$nextTick(() => { this.renderOverviewCharts(); this.refreshIcons(); });
      } catch (e) {
        this.apiOk = false;
      }
    },

    topicColor(id) { return (this.topics.find(t => t.topic_id === id) || {}).color || '#9ca3af'; },
    topicName(id) { const t = this.topics.find(x => x.topic_id === id); if (!t) return id || ''; return this.lang === 'zh' ? t.name_zh : t.name_en; },

    // ----- overview charts -----
    renderOverviewCharts() {
      this.renderTopicPie();
      this.renderDensityHeat();
    },

    renderTopicPie() {
      const el = document.getElementById('topic-pie');
      if (!el || !this.stats) return;
      this._pieChart?.dispose();
      this._pieChart = echarts.init(el, null, { renderer: 'canvas' });
      const dist = this.stats.topic_distribution || [];
      const data = dist.map(d => {
        const t = this.topics.find(x => x.topic_id === d.topic_id);
        return { name: this.lang === 'zh' ? d.name_zh : (t?.name_en || d.topic_id), value: d.count, itemStyle: { color: t?.color || '#9ca3af' } };
      });
      this._pieChart.setOption({
        textStyle: ECHARTS_TEXT,
        tooltip: { trigger: 'item', ...ECHARTS_TOOLTIP_BASE, formatter: '{b}: <b>{c}</b> ({d}%)' },
        series: [{
          type: 'pie', radius: ['52%', '76%'], center: ['50%', '50%'],
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          label: { fontSize: 11, color: '#374151', formatter: '{b}\n{d|{d}%}', rich: { d: { color: '#9ca3af', fontSize: 10 } } },
          labelLine: { length: 8, length2: 8, lineStyle: { color: '#d1d5db' } },
          data
        }]
      });
    },

    renderDensityHeat() {
      const el = document.getElementById('density-heat');
      if (!el || !this.stats) return;
      this._heatChart?.dispose();
      this._heatChart = echarts.init(el, null, { renderer: 'canvas' });
      // build last 36 months grid: x = month index, y = year row
      const series = (this.stats.timeline_density || []).slice();
      const map = {}; series.forEach(s => { map[s.month] = s.count; });
      const today = new Date(); const months = [];
      for (let i = 35; i >= 0; i--) {
        const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
        const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        months.push({ ym, year: d.getFullYear(), month: d.getMonth(), count: map[ym] || 0 });
      }
      const years = Array.from(new Set(months.map(m => m.year))).sort();
      const data = months.map(m => [m.month, years.indexOf(m.year), m.count]);
      const max = Math.max(1, ...data.map(d => d[2]));
      this._heatChart.setOption({
        textStyle: ECHARTS_TEXT,
        tooltip: { ...ECHARTS_TOOLTIP_BASE, formatter: p => `${months[months.findIndex(m => m.month === p.value[0] && years.indexOf(m.year) === p.value[1])]?.ym || ''}<br/><b>${p.value[2]}</b> ${this.lang === 'zh' ? '事件' : 'events'}` },
        grid: { left: 40, right: 20, top: 20, bottom: 50 },
        xAxis: {
          type: 'category', data: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
          axisLine: { lineStyle: { color: '#e5e7eb' } }, axisTick: { show: false }, axisLabel: { color: '#6b7280', fontSize: 11 }, splitArea: { show: false }
        },
        yAxis: {
          type: 'category', data: years.map(String),
          axisLine: { lineStyle: { color: '#e5e7eb' } }, axisTick: { show: false }, axisLabel: { color: '#6b7280', fontSize: 11 }, splitArea: { show: false }
        },
        visualMap: { min: 0, max, calculable: false, show: false, inRange: { color: ['#f1f5f9', '#bae6fd', '#0ea5e9', '#0369a1'] } },
        series: [{
          type: 'heatmap', data,
          label: { show: false },
          itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
          emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.10)' } }
        }]
      });
    },

    // ----- graph -----
    async renderGraph(reset = false) {
      const el = document.getElementById('event-graph');
      if (!el) return;
      this.graphLoading = true;
      try {
        const path = '/api/graph' + (this.selectedTopic ? `?topic=${this.selectedTopic}` : '');
        const data = await apiCall(path);
        const nodes = (data.nodes || []).map(n => {
          const color = n.color || this.topicColor(n.topic_id);
          return {
            id: n.id, name: this.lang === 'zh' ? n.label_zh : n.label_en,
            symbolSize: 10 + (n.intensity || 5) * 2.6,
            itemStyle: { color, borderColor: '#fff', borderWidth: 1.5 },
            label: { show: true, position: 'right', fontSize: 11, color: '#374151' },
            _raw: n
          };
        });
        const edges = (data.edges || []).map(e => ({
          source: e.source, target: e.target,
          lineStyle: { color: EDGE_COLORS[e.type] || '#cbd5e1', width: 1.5, opacity: 0.7, curveness: 0.12 },
          label: { show: false, formatter: this.lang === 'zh' ? e.label_zh : e.label_en, fontSize: 10, color: '#6b7280' },
          symbol: ['none', 'arrow'], symbolSize: 6
        }));
        if (!this._graphChart || reset) {
          this._graphChart?.dispose();
          this._graphChart = echarts.init(el, null, { renderer: 'canvas' });
        }
        this._graphChart.setOption({
          textStyle: ECHARTS_TEXT,
          tooltip: {
            ...ECHARTS_TOOLTIP_BASE,
            formatter: (p) => {
              if (p.dataType === 'edge') {
                const e = (data.edges || []).find(x => x.source === p.data.source && x.target === p.data.target) || {};
                return `<span style="color:#6b7280">${e.source} → ${e.target}</span><br/><b>${this.lang === 'zh' ? e.label_zh : e.label_en}</b>`;
              }
              const r = p.data._raw || {};
              return `<div style="max-width:280px"><div style="font-size:11px;color:#9ca3af">${r.date} · ${r.category || ''}</div><div style="font-weight:600;margin-top:2px">${r.label_zh || ''}</div><div style="color:#6b7280;font-size:11px;margin-top:2px">${r.label_en || ''}</div></div>`;
            }
          },
          series: [{
            type: 'graph', layout: 'force', roam: true, draggable: true,
            force: { repulsion: 220, edgeLength: 110, gravity: 0.08 },
            edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 7,
            emphasis: { focus: 'adjacency', label: { fontWeight: 600 } },
            data: nodes, links: edges,
            lineStyle: { opacity: 0.65 }
          }]
        }, true);
        this._graphChart.off('click');
        this._graphChart.on('click', (p) => { if (p.dataType === 'node') this.openDetail(p.data.id); });
        this.renderGraphTimeline(data.timeline || []);
      } catch (e) {
        console.error('graph load failed', e); this.apiOk = false;
      } finally {
        this.graphLoading = false;
      }
    },

    renderGraphTimeline(timeline) {
      const el = document.getElementById('graph-timeline');
      if (!el) return;
      this._timelineChart?.dispose();
      this._timelineChart = echarts.init(el, null, { renderer: 'canvas' });
      const data = (timeline || []).slice().sort((a, b) => a.date.localeCompare(b.date));
      this._timelineChart.setOption({
        textStyle: ECHARTS_TEXT,
        tooltip: { trigger: 'axis', ...ECHARTS_TOOLTIP_BASE },
        grid: { top: 12, left: 38, right: 16, bottom: 24 },
        xAxis: { type: 'category', data: data.map(d => d.date), axisLine: { lineStyle: { color: '#e5e7eb' } }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f3f4f6' } }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 } },
        series: [{
          type: 'bar', data: data.map(d => d.intensity_avg || d.count || 0),
          itemStyle: { color: '#0ea5e9', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18
        }]
      });
    },

    // ----- search -----
    async runSearch() {
      const q = (this.searchQuery || '').trim();
      if (!q) { this.searchResults = []; return; }
      this.searchLoading = true;
      try {
        const data = await apiCall('/api/search', { method: 'POST', body: { query: q, lang: 'auto', top_k: 10 } });
        this.searchResults = data.results || [];
        this.refreshIcons();
      } catch (e) { console.error(e); this.apiOk = false; }
      finally { this.searchLoading = false; }
    },

    searchEvidenceFor(language) {
      // flatten one row per (event, evidence-of-lang)
      const out = [];
      (this.searchResults || []).forEach(r => {
        (r.evidence || []).forEach((ev, idx) => {
          if (ev.lang !== language) return;
          out.push({
            event_id: r.event_id, title_zh: r.title_zh, title_en: r.title_en,
            date: (r.date || ev.date || ''), score: ev.score ?? r.score ?? 0,
            snippet: ev.snippet || '', evIdx: idx, article_id: ev.article_id
          });
        });
      });
      out.sort((a, b) => b.score - a.score);
      return out;
    },

    highlightSnippet(text, query) {
      if (!text) return '';
      const escaped = String(text).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      const terms = (query || '').split(/\s+/).filter(t => t.length > 1);
      let html = escaped;
      terms.forEach(t => {
        const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
        html = html.replace(re, m => `<mark class="qhit">${m}</mark>`);
      });
      return html;
    },

    // ----- briefing -----
    async generateBriefing() {
      this.briefLoading = true; this.briefResult = null;
      try {
        const body = { language: this.brief.language, style: this.brief.style };
        if (this.brief.topic) body.topic_id = this.brief.topic;
        const data = await apiCall('/api/briefing', { method: 'POST', body });
        this.briefResult = data;
        this.$nextTick(() => { this.bindCitationHovers(); this.refreshIcons(); });
      } catch (e) { console.error(e); this.apiOk = false; }
      finally { this.briefLoading = false; }
    },

    timelinePct(timeline, idx) {
      if (!timeline?.length) return 0;
      if (timeline.length === 1) return 50;
      return (idx / (timeline.length - 1)) * 100;
    },

    riskColor(score) {
      if (score >= 7) return '#f97316';
      if (score >= 4) return '#0ea5e9';
      return '#10b981';
    },

    renderCitations(content, citations) {
      if (!content) return '';
      const escaped = String(content).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      // Replace [1] [2] etc. with clickable pills
      return escaped.replace(/\[(\d+)\]/g, (_m, n) => {
        const idx = parseInt(n, 10) - 1;
        const cit = (citations || [])[idx];
        if (!cit) return `[${n}]`;
        return `<span class="cite-pill" data-event="${cit.event_id || ''}" data-article="${cit.article_id || ''}" data-snippet="${(cit.snippet || '').replace(/"/g, '&quot;')}">[${n}]</span>`;
      });
    },

    bindCitationHovers() {
      document.querySelectorAll('.cite-pill').forEach(el => {
        el.addEventListener('click', () => {
          const ev = el.dataset.event;
          if (ev) this.openDetail(ev);
        });
        let tip;
        el.addEventListener('mouseenter', (e) => {
          tip = document.createElement('div');
          tip.className = 'cite-tooltip';
          tip.innerHTML = `<span class="src">${el.dataset.article || ''}</span>${el.dataset.snippet || ''}`;
          document.body.appendChild(tip);
          const r = el.getBoundingClientRect();
          tip.style.top = (window.scrollY + r.bottom + 6) + 'px';
          tip.style.left = Math.max(8, window.scrollX + r.left - 8) + 'px';
        });
        el.addEventListener('mouseleave', () => { tip?.remove(); tip = null; });
      });
    },

    copyBriefingMarkdown() {
      if (!this.briefResult) return;
      const b = this.briefResult;
      let md = `# ${b.title}\n\n_${new Date(b.generated_at).toLocaleString()} · risk ${b.risk_score?.toFixed?.(1)} · consistency ${(b.cross_lingual_consistency * 100).toFixed(0)}%_\n\n`;
      if (b.key_actors?.length) md += `**Key actors:** ${b.key_actors.join(', ')}\n\n`;
      (b.sections || []).forEach(s => { md += `## ${s.heading}\n\n${s.content}\n\n`; });
      navigator.clipboard.writeText(md).then(() => {
        // tiny inline feedback
        const btns = document.querySelectorAll('button'); // best-effort, no toast lib
      });
    },

    downloadBriefingJson() {
      if (!this.briefResult) return;
      const blob = new Blob([JSON.stringify(this.briefResult, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `briefing_${Date.now()}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },

    // ----- detail drawer -----
    async openDetail(eventId) {
      if (!eventId) return;
      this.drawer.open = true; this.drawer.loading = true;
      this.drawer.event = null; this.drawer.articles = []; this.drawer.related = [];
      try {
        const data = await apiCall(`/api/events/${eventId}`);
        this.drawer.event = data.event;
        this.drawer.articles = (data.articles || []).map(a => ({ ...a, _open: false }));
        this.drawer.related = data.related_events || [];
        this.refreshIcons();
      } catch (e) { console.error(e); this.apiOk = false; }
      finally { this.drawer.loading = false; }
    },
    closeDetail() { this.drawer.open = false; },

    // ----- rerender on lang flip / resize -----
    rerenderActiveCharts() {
      if (this.view === 'overview') this.$nextTick(() => this.renderOverviewCharts());
      if (this.view === 'graph') this.$nextTick(() => this.renderGraph());
    }
  };
}

// Resize ECharts instances on window resize
window.addEventListener('resize', () => {
  ['topic-pie', 'density-heat', 'event-graph', 'graph-timeline'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const inst = echarts.getInstanceByDom(el);
    inst?.resize();
  });
});

// expose to Alpine global scope
window.dashboard = dashboard;
