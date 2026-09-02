import json
import os

import requests
import streamlit as st


API = os.getenv("KP_API_BASE_URL", "http://127.0.0.1:8000")
st.set_page_config(page_title="KnowledgePilot", page_icon="K", layout="wide")
st.title("KnowledgePilot")
st.caption("真实科研数据论文检索、证据问答与趋势分析 Agent")


def api_get(path, timeout=20):
    try:
        return requests.get(f"{API}{path}", timeout=timeout)
    except requests.exceptions.ConnectionError:
        st.error("API 服务未启动，请先运行 python -m uvicorn app.api.main:app --port 8000")
        return None
    except requests.exceptions.Timeout:
        st.warning("请求超时，可能正在调用 LLM 或数据源繁忙。请稍后重试。")
        return None


def api_post(path, json_data, timeout=180):
    try:
        return requests.post(f"{API}{path}", json=json_data, timeout=timeout)
    except requests.exceptions.ConnectionError:
        st.error("API 服务未启动，请先运行 python -m uvicorn app.api.main:app --port 8000")
        return None
    except requests.exceptions.Timeout:
        st.warning("请求超时，可能正在调用 LLM 或数据源繁忙。面试演示建议先运行 python scripts/warmup_demo.py 预热缓存。")
        return None


with st.sidebar:
    st.subheader("数据管理")
    try:
        model_status = requests.get(f"{API}/api/model/status", timeout=5).json()
        st.caption(f"模型：{model_status.get('provider')} / {model_status.get('model')}")
        st.caption(model_status.get("message", ""))
    except Exception:
        st.caption("模型状态：API 尚未连接")
    st.divider()
    sync_query = st.text_input("同步主题", "retrieval augmented generation")
    if st.button("同步真实论文", type="primary"):
        with st.spinner("正在从 OpenAlex 获取论文..."):
            response = api_post("/api/sync", {"query": sync_query, "pages": 1, "per_page": 50}, timeout=60)
        if response and response.ok:
            data = response.json()
            if data.get("source") == "local_fallback":
                st.info(data.get("message", "使用本地缓存"))
            else:
                st.success(f"同步完成：获取 {data['fetched']} 篇，去重后 {data['unique']} 篇")
        elif response:
            st.error(response.text)
    st.divider()
    if st.button("查看系统状态"):
        response = api_get("/health")
        if response and response.ok:
            st.json(response.json())
    st.divider()
    st.caption("面试演示前请运行：python scripts/warmup_demo.py")

tab_chat, tab_search, tab_detail, tab_compare, tab_trend, tab_eval, tab_tools = st.tabs(
    ["中文 Agent 对话", "论文搜索", "详情/全文", "论文对比", "主题趋势", "评测报告", "MCP 工具"]
)

with tab_chat:
    query = st.text_area("输入问题", "请介绍 Attention Is All You Need 这篇论文提出的方法，详细从原理分析。", height=100)
    if st.button("运行 Agent", type="primary"):
        with st.spinner("Agent 正在规划、调用工具并校验证据..."):
            response = api_post("/api/chat", {"query": query, "session_id": "ui"}, timeout=180)
        if response and response.ok:
            data = response.json()
            st.markdown("### 中文回答")
            st.write(data["answer"])
            cols = st.columns(4)
            cols[0].metric("置信度", f"{data['confidence']:.2f}")
            cols[1].metric("耗时", f"{data['latency_ms']:.0f} ms")
            cols[2].metric("迭代轮数", data.get("iterations", 1))
            cols[3].metric("Judge 判定", data.get("judge_verdict", "pass"))
            st.markdown("### 来源证据")
            for citation in data.get("citations", []):
                st.write(f"**{citation['title']}**")
                st.caption(f"DOI: {citation.get('doi') or '无'} | {citation.get('url') or '无链接'}")
                st.info(citation.get("evidence", ""))
            with st.expander("查看 ReAct / Tool Calling 轨迹"):
                st.json(data.get("trace", []))
        elif response:
            st.error(response.text)

with tab_search:
    search_query = st.text_input("标题片段或关键词", "CNN相关论文")
    top_k = st.slider("返回数量", 1, 20, 8)
    if st.button("搜索论文"):
        response = api_post("/api/search", {"query": search_query, "top_k": top_k, "online": True}, timeout=120)
        if response and response.ok:
            data = response.json()
            source_label = {"online": "在线检索", "cache": "缓存命中", "local_fallback": "本地缓存兜底"}.get(data.get("source", ""), "")
            st.caption(f"共 {data['count']} 条，{source_label}")
            for item in data["results"]:
                paper = item["paper"]
                st.markdown(f"#### {paper['title']}")
                st.write(f"年份：{paper.get('year') or '未知'} | 期刊：{paper.get('journal') or '未知'} | 相关度：{item['score']}")
                st.write(f"作者：{', '.join(paper.get('authors', [])[:6])}")
                st.write(f"DOI：{paper.get('doi') or '无'}")
                if paper.get("landing_page_url"):
                    st.link_button("打开来源", paper["landing_page_url"])
        elif response:
            st.error(response.text)

with tab_detail:
    identifier = st.text_input("论文 DOI、arXiv ID、OpenAlex ID 或标题片段", "10.48550/arXiv.1706.03762")
    col_detail_a, col_detail_b = st.columns(2)
    with col_detail_a:
        if st.button("获取论文详情"):
            response = api_get(f"/api/papers/{identifier}", timeout=120)
            if response and response.ok:
                paper = response.json()
                st.markdown(f"### {paper['title']}")
                st.write(f"作者：{', '.join(paper.get('authors', [])[:10]) or '无'}")
                st.write(f"年份：{paper.get('year') or '未知'} | 期刊：{paper.get('journal') or '未知'}")
                st.write(f"DOI：{paper.get('doi') or '无'}")
                st.write(f"开放获取：{'是' if paper.get('is_oa') else '未知/否'}")
                if paper.get("landing_page_url"):
                    st.link_button("打开来源", paper["landing_page_url"])
                if paper.get("pdf_url"):
                    st.link_button("打开 PDF", paper["pdf_url"])
                st.info((paper.get("abstract") or "暂无摘要")[:1800])
            elif response:
                st.error(response.text)
    with col_detail_b:
        if st.button("自动下载/解析开放全文", type="primary"):
            response = api_post("/api/fulltext", {"identifier": identifier}, timeout=180)
            if response and response.ok:
                result = response.json()
                status_label = {"downloaded": "已下载并解析", "cached": "已有缓存", "abstract_only": "仅摘要分块", "no_open_text": "无开放全文", "not_found": "未找到论文", "failed": "解析失败"}.get(result.get("status", ""), result.get("status", ""))
                st.info(f"状态：{status_label} | 分块数：{result.get('chunk_count', 0)}")
                if result.get("title"):
                    st.caption(f"论文：{result['title']}")
            elif response:
                st.error(response.text)

with tab_compare:
    compare_query = st.text_area("输入两篇论文标题、关键词或 DOI", "比较 Attention Is All You Need 和 BERT pre-training 的方法区别", height=90)
    if st.button("生成论文对比"):
        response = api_post("/api/chat", {"query": compare_query, "session_id": "ui-compare"}, timeout=180)
        if response and response.ok:
            data = response.json()
            st.write(data["answer"])
            with st.expander("对比来源"):
                for citation in data.get("citations", []):
                    st.write(f"- {citation['title']} | {citation.get('doi') or '无 DOI'}")
        elif response:
            st.error(response.text)

with tab_trend:
    trend_query = st.text_input("趋势主题", "RAG近几年研究趋势")
    if st.button("生成趋势分析"):
        response = api_post("/api/chat", {"query": trend_query, "session_id": "ui-trend"}, timeout=180)
        if response and response.ok:
            data = response.json()
            st.write(data["answer"])
            with st.expander("趋势样本来源"):
                for citation in data.get("citations", []):
                    st.write(f"- {citation['title']} | {citation.get('doi') or '无 DOI'}")
        elif response:
            st.error(response.text)

with tab_eval:
    col_eval_a, col_eval_b = st.columns(2)
    with col_eval_a:
        if st.button("运行 Harness 评测"):
            with st.spinner("正在运行真实数据评测（约 12-20 分钟）..."):
                response = api_post("/api/evaluation/run", {}, timeout=1800)
            if response and response.ok:
                st.success("评测完成")
                report = response.json()
                metric_cols = st.columns(4)
                metric_cols[0].metric("Recall@5", report.get("recall_at_5"))
                metric_cols[1].metric("MRR", report.get("mrr"))
                metric_cols[2].metric("拒答准确率", report.get("refusal_precision"))
                metric_cols[3].metric("Judge 拒绝率", report.get("judge_rejection_rate"))
                st.dataframe(report.get("rows", []), use_container_width=True)
            elif response:
                st.error(response.text)
        if st.button("读取最近评测报告", type="primary"):
            response = api_get("/api/evaluation/latest")
            if response and response.ok:
                report = response.json()
                if report.get("status") == "empty":
                    st.warning(report["message"])
                else:
                    metric_cols = st.columns(4)
                    metric_cols[0].metric("Recall@5", report.get("recall_at_5"))
                    metric_cols[1].metric("MRR", report.get("mrr"))
                    metric_cols[2].metric("拒答准确率", report.get("refusal_precision"))
                    metric_cols[3].metric("p95 延迟", f"{report.get('p95_latency_ms', 0):.0f} ms")
                    st.dataframe(report.get("rows", []), use_container_width=True)
            elif response:
                st.error(response.text)
    with col_eval_b:
        if st.button("查看缓存/数据统计"):
            response = api_get("/api/stats")
            if response and response.ok:
                st.json(response.json())
        st.divider()
        st.caption("评测指标由真实 OpenAlex/Crossref/arXiv 响应和本机环境实时测得。")

with tab_tools:
    response = api_get("/mcp/tools")
    if response and response.ok:
        st.json(response.json())
    elif response:
        st.warning("API 尚未启动")
