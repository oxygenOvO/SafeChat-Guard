from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.pipeline import SafeChatPipeline


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
FRONTEND_CASES = PROJECT_ROOT / "data" / "test_cases" / "frontend_cases.csv"

CATEGORY_LABELS = {
    "normal": "正常",
    "porn": "色情/低俗",
    "violence": "暴力",
    "ad": "广告",
    "sensitive": "敏感话术",
    "abuse": "低俗辱骂",
    "privacy": "隐私信息",
    "illegal": "违法违规",
    "self_harm": "自伤风险",
    "unknown": "未知类别",
}

RISK_LABELS = {
    "none": "无风险",
    "low": "低风险",
    "medium": "中低风险",
    "high": "高风险",
}

ACTION_LABELS = {
    "pass": "放行",
    "sanitize": "脱敏处理",
    "block": "拦截",
    "not_run": "未执行",
}

RISK_COLORS = {
    "low": "#16A34A",
    "medium": "#F59E0B",
    "high": "#DC2626",
}

ACTION_COLORS = {
    "pass": "#16A34A",
    "sanitize": "#2563EB",
    "block": "#DC2626",
}

DEMO_CASES = {
    "正常放行": ("今天图书馆几点关门？", False),
    "基线漏检": ("加 V-X 领取优 惠 券，名额有限", False),
    "中风险脱敏": ("想领取课程资料可以加微信私聊。", False),
    "高风险拦截": ("我要杀了你", False),
    "易误判放行": ("这个 bug 会导致程序崩溃，需要做网络安全防护。", False),
    "输出违规拦截": ("普通输入，但模拟模型输出违规", True),
}


@st.cache_resource
def get_adapter() -> FrontendPipelineAdapter:
    pipeline = SafeChatPipeline.from_config(str(PROJECT_ROOT / "config.yaml"))
    return FrontendPipelineAdapter(pipeline)


def configure_page() -> None:
    st.set_page_config(
        page_title="SafeChat-Guard",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root {
            --sg-blue: #2563eb;
            --sg-cyan: #0891b2;
            --sg-green: #16a34a;
            --sg-orange: #f59e0b;
            --sg-red: #dc2626;
            --sg-ink: #111827;
            --sg-muted: #6b7280;
            --sg-border: #e5e7eb;
            --sg-panel: #ffffff;
            --sg-bg: #f5f7fb;
        }
        .stApp { background: var(--sg-bg); }
        .main .block-container { padding-top: 1.2rem; padding-bottom: 2.2rem; max-width: 1440px; }
        h1, h2, h3 { letter-spacing: 0 !important; }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
        }
        [data-testid="stSidebar"] * { color: #e5e7eb !important; }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            border-radius: 8px;
            padding: 7px 8px;
        }
        div[data-testid="stMetric"] {
            background: var(--sg-panel);
            border: 1px solid var(--sg-border);
            border-radius: 10px;
            padding: 14px 16px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        }
        .hero {
            background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 58%, #0891b2 100%);
            border-radius: 14px;
            padding: 22px 24px;
            color: white;
            margin-bottom: 16px;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.18);
        }
        .hero h2 { margin: 0 0 8px 0; color: white; }
        .hero p { margin: 0; color: #dbeafe; font-size: 15px; line-height: 1.6; }
        .panel {
            background: var(--sg-panel);
            border: 1px solid var(--sg-border);
            border-radius: 12px;
            padding: 16px 18px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
            min-height: 128px;
        }
        .panel-muted {
            background: #f8fafc;
            border: 1px solid var(--sg-border);
            border-radius: 12px;
            padding: 16px 18px;
            min-height: 128px;
        }
        .section-title {
            font-size: 18px;
            font-weight: 700;
            color: var(--sg-ink);
            margin: 10px 0 10px 0;
        }
        .soft-caption { color: var(--sg-muted); font-size: 13px; line-height: 1.55; }
        .pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .pill-blue { background: #dbeafe; color: #1d4ed8; }
        .pill-green { background: #dcfce7; color: #166534; }
        .pill-orange { background: #ffedd5; color: #9a3412; }
        .pill-red { background: #fee2e2; color: #991b1b; }
        .pill-gray { background: #f3f4f6; color: #374151; }
        .step {
            background: #fff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 12px 10px;
            min-height: 108px;
            text-align: center;
        }
        .step-ok { border-top: 5px solid #16a34a; }
        .step-warn { border-top: 5px solid #f59e0b; }
        .step-stop { border-top: 5px solid #dc2626; }
        .step-info { border-top: 5px solid #2563eb; }
        .step-title { font-weight: 700; font-size: 14px; color: #111827; }
        .step-desc { font-size: 12px; color: #6b7280; margin-top: 6px; line-height: 1.45; }
        .compare-bad { border-left: 5px solid #ef4444; }
        .compare-good { border-left: 5px solid #22c55e; }
        .codebox {
            background: #0f172a;
            color: #e5e7eb;
            border-radius: 8px;
            padding: 12px;
            font-size: 13px;
            line-height: 1.55;
            white-space: pre-wrap;
        }

        /* Competition UI polish: restrained motion and a security-console visual system. */
        :root {
            --sg-blue: #2563eb;
            --sg-cyan: #0e7490;
            --sg-green: #15803d;
            --sg-orange: #d97706;
            --sg-red: #dc2626;
            --sg-ink: #172033;
            --sg-muted: #64748b;
            --sg-border: #dce3ec;
            --sg-panel: #ffffff;
            --sg-bg: #f4f6f9;
            --sg-shadow: 0 8px 22px rgba(23, 32, 51, 0.06);
            --sg-shadow-hover: 0 12px 28px rgba(23, 32, 51, 0.10);
            --sg-ease: cubic-bezier(0.22, 1, 0.36, 1);
        }
        .stApp { background: var(--sg-bg); color: var(--sg-ink); }
        .main .block-container {
            padding-top: 1.15rem;
            padding-bottom: 2.4rem;
            max-width: 1440px;
            animation: sg-page-enter 280ms var(--sg-ease) both;
        }
        [data-testid="stHeader"] { background: rgba(244, 246, 249, 0.88); }
        [data-testid="stSidebar"] { background: #111827; border-right: 1px solid #263244; }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] { gap: 3px; }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            position: relative;
            min-height: 40px;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 8px 10px;
            transition: background-color 180ms ease, border-color 180ms ease, transform 180ms ease;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
            background: #1e293b;
            border-color: #334155;
            transform: translateX(2px);
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) {
            background: #1f314c;
            border-color: #315178;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked)::before {
            content: "";
            position: absolute;
            inset: 7px auto 7px -1px;
            width: 3px;
            border-radius: 2px;
            background: #38bdf8;
            animation: sg-indicator 220ms var(--sg-ease) both;
        }
        div[data-testid="stMetric"], .panel, .panel-muted, .step {
            border-radius: 8px;
            border-color: var(--sg-border);
            box-shadow: var(--sg-shadow);
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }
        div[data-testid="stMetric"] {
            min-height: 116px;
            padding: 14px 16px;
            animation: sg-rise 260ms var(--sg-ease) both;
        }
        div[data-testid="stMetric"]:hover, .panel:hover, .panel-muted:hover, .step:hover {
            transform: translateY(-2px);
            border-color: #bdc9d8;
            box-shadow: var(--sg-shadow-hover);
        }
        .hero {
            position: relative;
            overflow: hidden;
            background: #172033;
            border: 1px solid #27364f;
            border-radius: 8px;
            padding: 20px 22px;
            box-shadow: 0 10px 26px rgba(23, 32, 51, 0.14);
            animation: sg-hero-enter 300ms var(--sg-ease) both;
        }
        .hero::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: #22c55e;
        }
        .hero h2 { font-size: 24px; line-height: 1.25; }
        .hero p { color: #d7e1ef; }
        .section-title { font-size: 17px; margin: 14px 0 10px; animation: sg-rise 220ms var(--sg-ease) both; }
        .section-title {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .section-title::before {
            content: "";
            width: 3px;
            height: 17px;
            border-radius: 2px;
            background: var(--sg-cyan);
            box-shadow: 0 0 0 3px rgba(14, 116, 144, 0.10);
        }
        div[data-testid="stMetric"] {
            position: relative;
            overflow: hidden;
        }
        div[data-testid="stHorizontalBlock"] > div:nth-child(5n + 1) div[data-testid="stMetric"] { border-top: 3px solid #2878d0; }
        div[data-testid="stHorizontalBlock"] > div:nth-child(5n + 2) div[data-testid="stMetric"] { border-top: 3px solid #16869b; }
        div[data-testid="stHorizontalBlock"] > div:nth-child(5n + 3) div[data-testid="stMetric"] { border-top: 3px solid #d9485f; }
        div[data-testid="stHorizontalBlock"] > div:nth-child(5n + 4) div[data-testid="stMetric"] { border-top: 3px solid #e08a1e; }
        div[data-testid="stHorizontalBlock"] > div:nth-child(5n + 5) div[data-testid="stMetric"] { border-top: 3px solid #159f74; }
        [data-testid="stPlotlyChart"] {
            overflow: hidden;
            background: #ffffff;
            border: 1px solid var(--sg-border);
            border-radius: 8px;
            box-shadow: var(--sg-shadow);
            animation: sg-chart-enter 320ms var(--sg-ease) both;
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }
        [data-testid="stPlotlyChart"]:hover {
            transform: translateY(-2px);
            border-color: #bdc9d8;
            box-shadow: var(--sg-shadow-hover);
        }
        [data-testid="stPlotlyChart"] .pielayer {
            transform-box: fill-box;
            transform-origin: center;
            animation: sg-donut-spin-in 720ms var(--sg-ease) both;
        }
        [data-testid="stPlotlyChart"] .legend {
            animation: sg-legend-enter 420ms ease 260ms both;
        }
        [data-testid="stPlotlyChart"] .modebar {
            opacity: 0.25;
            transition: opacity 160ms ease;
        }
        [data-testid="stPlotlyChart"]:hover .modebar { opacity: 0.78; }
        div[data-baseweb="input"], div[data-baseweb="textarea"], div[data-baseweb="select"] > div {
            background: #ffffff;
            border-color: var(--sg-border);
            transition: border-color 160ms ease, box-shadow 160ms ease;
        }
        div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
        div[data-baseweb="select"] > div:focus-within {
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
        }
        [data-testid="stDataFrame"] { background: #ffffff; }
        .hero {
            padding: 16px 20px;
            margin-bottom: 12px;
        }
        .hero h2 { font-size: 22px; margin-bottom: 6px; }
        .hero p { font-size: 14px; }
        button[data-testid="stBaseButton-primary"],
        .stButton > button[kind="primary"] {
            background: #2563eb !important;
            border-color: #2563eb !important;
            color: #ffffff !important;
        }
        button[data-testid="stBaseButton-primary"]:hover,
        .stButton > button[kind="primary"]:hover {
            background: #1d4ed8 !important;
            border-color: #1d4ed8 !important;
        }
        .result-panel {
            min-height: 168px;
            padding: 17px 18px;
            background: #ffffff;
            border: 1px solid var(--sg-border);
            border-left: 4px solid #94a3b8;
            border-radius: 8px;
            box-shadow: var(--sg-shadow);
            animation: sg-result-enter 240ms var(--sg-ease) both;
        }
        .result-low { border-left-color: var(--sg-green); }
        .result-medium { border-left-color: var(--sg-orange); }
        .result-high { border-left-color: var(--sg-red); }
        .result-eyebrow {
            color: var(--sg-muted);
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .result-verdict {
            color: var(--sg-ink);
            font-size: 24px;
            font-weight: 750;
            line-height: 1.25;
            margin-bottom: 12px;
        }
        .result-meta {
            color: #334155;
            font-size: 14px;
            line-height: 1.7;
        }
        .result-empty {
            min-height: 168px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 18px;
            background: #f8fafc;
            border: 1px dashed #b8c4d3;
            border-radius: 8px;
            color: var(--sg-muted);
        }
        .result-empty b {
            color: var(--sg-ink);
            font-size: 17px;
            margin-bottom: 6px;
        }
        .step {
            min-height: 122px;
            text-align: left;
            padding: 13px 14px;
            margin-bottom: 12px;
        }
        .step-index {
            color: var(--sg-cyan);
            font-size: 11px;
            font-weight: 800;
            margin-bottom: 5px;
        }
        .step-title { font-size: 15px; }
        .step-desc {
            overflow-wrap: anywhere;
            line-height: 1.55;
        }
        .pill { transition: filter 160ms ease, transform 160ms ease; }
        .pill:hover { filter: saturate(1.08); transform: translateY(-1px); }
        .step { animation: sg-rise 260ms var(--sg-ease) both; }
        .step:nth-child(2) { animation-delay: 35ms; }
        .step:nth-child(3) { animation-delay: 70ms; }
        .step:nth-child(4) { animation-delay: 105ms; }
        .step:nth-child(5) { animation-delay: 140ms; }
        div[data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--sg-border); }
        button[data-baseweb="tab"] { transition: color 180ms ease, background-color 180ms ease; }
        button[data-baseweb="tab"]:hover { background: #eaf0f7; }
        div[data-baseweb="tab-panel"] { animation: sg-tab-enter 240ms var(--sg-ease) both; }
        .stButton > button, .stDownloadButton > button {
            min-height: 40px;
            border-radius: 6px;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(37, 99, 235, 0.14);
        }
        .stButton > button:active, .stDownloadButton > button:active { transform: translateY(1px); box-shadow: none; }
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            border: 1px solid var(--sg-border);
            border-radius: 8px;
            overflow: hidden;
            animation: sg-rise 250ms var(--sg-ease) both;
        }
        [data-testid="stAlert"] { border-radius: 8px; animation: sg-rise 220ms var(--sg-ease) both; }
        input:focus, textarea:focus { transition: box-shadow 160ms ease, border-color 160ms ease; }
        @keyframes sg-page-enter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes sg-hero-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes sg-rise { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes sg-tab-enter { from { opacity: 0; transform: translateX(4px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes sg-indicator { from { opacity: 0; transform: scaleY(0.45); } to { opacity: 1; transform: scaleY(1); } }
        @keyframes sg-chart-enter {
            from { opacity: 0; transform: translateY(7px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes sg-donut-spin-in {
            from { opacity: 0; transform: rotate(-72deg) scale(0.94); }
            to { opacity: 1; transform: rotate(0deg) scale(1); }
        }
        @keyframes sg-legend-enter {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        @keyframes sg-result-enter {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 768px) {
            .main .block-container { padding: 0.8rem 0.85rem 1.8rem; }
            .hero { padding: 17px 16px; }
            .hero h2 { font-size: 21px; }
            div[data-testid="stMetric"] { min-height: 104px; }
            div[data-testid="stMetric"]:hover, .panel:hover, .panel-muted:hover, .step:hover { transform: none; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
                scroll-behavior: auto !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "selected_demo" not in st.session_state:
        st.session_state.selected_demo = "基线漏检"
    if "last_result" not in st.session_state:
        text, flag = DEMO_CASES[st.session_state.selected_demo]
        st.session_state.last_result = run_pipeline(text, flag)
    if "last_run_signature" not in st.session_state:
        text, flag = DEMO_CASES[st.session_state.selected_demo]
        st.session_state.last_run_signature = (text.strip(), bool(flag))















def run_pipeline(text: str, simulate_output_violation: bool = False) -> dict[str, Any]:
    output_override = None
    if simulate_output_violation:
        output_override = "模拟模型原始输出：可以加微信领取优惠券，名额有限。"
    return get_adapter().analyze(text, output_override=output_override)


def sample_test_cases() -> pd.DataFrame:
    return pd.read_csv(FRONTEND_CASES, dtype={"id": str})


def append_log(result: dict[str, Any]) -> None:
    get_adapter().record(result)


def format_hits(hits: list[dict[str, str]]) -> str:
    if not hits:
        return "无"
    rows = []
    for hit in hits:
        category = CATEGORY_LABELS.get(hit["category"], hit["category"])
        rows.append(
            f'{escape(str(hit["type"]))}: {escape(str(category))} / '
            f'{escape(str(hit["value"]))}'
        )
    return "<br>".join(rows)


def label_pill(text: str, kind: str = "blue") -> str:
    return f'<span class="pill pill-{kind}">{escape(str(text))}</span>'


def risk_pill(risk: str) -> str:
    mapping = {"none": "green", "low": "green", "medium": "orange", "high": "red"}
    return label_pill(RISK_LABELS.get(risk, risk), mapping.get(risk, "gray"))


def action_pill(action: str) -> str:
    mapping = {"pass": "green", "sanitize": "blue", "block": "red", "not_run": "gray"}
    return label_pill(ACTION_LABELS.get(action, action), mapping.get(action, "gray"))


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <h2>SafeChat-Guard 大模型内容安全风控控制台</h2>
          <p>真实接入输入归一化、双层检测、分级处理、输出校验、日志审计与批量评测。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def plot_donut(df: pd.DataFrame, column: str, title: str, label_map: dict[str, str] | None = None) -> go.Figure:
    if df.empty or column not in df:
        data = pd.DataFrame({"label": ["暂无数据"], "count": [1]})
    else:
        data = df[column].fillna("unknown").value_counts().reset_index()
        data.columns = ["label", "count"]
        if label_map:
            data["label"] = data["label"].map(label_map).fillna(data["label"])
    semantic_colors = {
        "正常": "#159f74",
        "无风险": "#159f74",
        "放行": "#159f74",
        "广告": "#2878d0",
        "中低风险": "#e08a1e",
        "脱敏处理": "#16869b",
        "低俗辱骂": "#d9485f",
        "高风险": "#d9485f",
        "拦截": "#d9485f",
        "敏感话术": "#7c6acf",
        "未知": "#94a3b8",
        "暂无数据": "#cbd5e1",
    }
    fallback_colors = ["#2878d0", "#159f74", "#e08a1e", "#d9485f", "#7c6acf", "#16869b"]
    colors = [semantic_colors.get(str(label), fallback_colors[index % len(fallback_colors)]) for index, label in enumerate(data["label"])]
    total = 0 if df.empty or column not in df else int(data["count"].sum())
    center_text = f"<b>{total}</b><br><span style='font-size:11px;color:#64748b'>条记录</span>"
    fig = go.Figure(
        go.Pie(
            labels=data["label"],
            values=data["count"],
            hole=0.62,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            textinfo="percent",
            textposition="inside",
            textfont=dict(size=12, color="#ffffff"),
            insidetextorientation="horizontal",
            hovertemplate="<b>%{label}</b><br>数量：%{value}<br>占比：%{percent}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, x=0.04, y=0.95, font=dict(size=17, color="#172033")),
        margin=dict(l=14, r=14, t=54, b=50),
        height=330,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Microsoft YaHei, Arial, sans-serif", color="#334155"),
        legend=dict(
            orientation="h",
            x=0.5,
            xanchor="center",
            y=-0.08,
            yanchor="bottom",
            font=dict(size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        annotations=[dict(text=center_text, x=0.5, y=0.5, showarrow=False, font=dict(size=22, color="#172033"))],
        uniformtext_minsize=10,
        uniformtext_mode="hide",
        hoverlabel=dict(bgcolor="#172033", bordercolor="#172033", font=dict(color="#ffffff")),
    )
    return fig


def plot_baseline_comparison(df: pd.DataFrame) -> go.Figure:
    total = len(df)
    enhanced = int((df["action"] != "pass").sum()) if total else 0
    recovered = int(df.get("baseline_missed", pd.Series(dtype=bool)).sum()) if total else 0
    baseline = max(enhanced - recovered, 0)
    labels = ["未归一化基线", "中文归一化增强版"]
    values = [baseline, enhanced]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=["#94a3b8", "#2878d0"],
            text=values,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>识别风险内容：%{y} 条<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="基线与增强版识别能力", x=0.04, y=0.95, font=dict(size=17, color="#172033")),
        margin=dict(l=28, r=18, t=58, b=38),
        height=330,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Microsoft YaHei, Arial, sans-serif", color="#334155"),
        yaxis=dict(title="", showgrid=True, gridcolor="#e8edf3", rangemode="tozero"),
        xaxis=dict(title="", showgrid=False),
        showlegend=False,
        hoverlabel=dict(bgcolor="#172033", bordercolor="#172033", font=dict(color="#ffffff")),
    )
    if recovered:
        fig.add_annotation(
            x="中文归一化增强版",
            y=enhanced,
            text=f"修复 {recovered} 条基线漏检",
            showarrow=False,
            yshift=24,
            font=dict(size=11, color="#159f74"),
        )
    return fig


def build_case_results(cases: pd.DataFrame) -> pd.DataFrame:
    results = []
    for _, row in cases.iterrows():
        mock_output = row.get("mock_model_output", "")
        simulate_output = pd.notna(mock_output) and bool(str(mock_output).strip())
        result = run_pipeline(str(row["input_text"]), simulate_output)
        results.append(
            {
                **row.to_dict(),
                "baseline_category": result["baseline_category"],
                "baseline_action": result["baseline_action"],
                "actual_category": result["category"],
                "actual_risk": result["risk"],
                "actual_action": result["action"],
                "semantic_score": round(result["semantic_score"], 3),
                "actual_output_action": result["output_action"],
                "category_match": result["category"] == row.get("expected_category"),
                "action_match": result["action"] == row.get("expected_action"),
                "output_action_match": result["output_action"] == row.get("expected_output_action"),
                "baseline_action_match": result["baseline_action"] == row.get("baseline_expected"),
                "baseline_missed": result["baseline_action"] == "pass" and row.get("expected_action") != "pass",
                "enhanced_success": result["action"] == row.get("expected_action"),
            }
        )
    return pd.DataFrame(results)


def dashboard_df() -> pd.DataFrame:
    log_rows = get_adapter().log_rows()
    if log_rows:
        return pd.DataFrame(log_rows)
    if "batch_results" in st.session_state:
        batch = st.session_state.batch_results.copy()
        return pd.DataFrame(
            {
                "time": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")] * len(batch),
                "input_text": batch["input_text"],
                "category": batch["actual_category"],
                "risk": batch["actual_risk"],
                "action": batch["actual_action"],
                "output_action": batch["actual_output_action"],
                "baseline_missed": batch["baseline_missed"],
            }
        )
    sample = build_case_results(sample_test_cases())
    return pd.DataFrame(
        {
            "time": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")] * len(sample),
            "input_text": sample["input_text"],
            "category": sample["actual_category"],
            "risk": sample["actual_risk"],
            "action": sample["actual_action"],
            "output_action": sample["actual_output_action"],
            "baseline_missed": sample["baseline_missed"],
        }
    )


def render_metric_row(df: pd.DataFrame) -> None:
    total = len(df)
    handled = int((df["action"] != "pass").sum()) if total else 0
    blocked = int((df["action"] == "block").sum()) if total else 0
    output_block = int((df["output_action"] == "block").sum()) if "output_action" in df and total else 0
    baseline_missed = int(df.get("baseline_missed", pd.Series(dtype=bool)).sum()) if total else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("请求总量", total)
    c2.metric("风险处理数", handled)
    c3.metric("高风险拦截", blocked)
    c4.metric("输出侧拦截", output_block)
    c5.metric("基线漏检修复", baseline_missed)
    st.caption("无真实日志时，总览使用内置测试集现场运行结果；指标用于演示系统链路，不代表正式评测成绩。")


def render_overview_page() -> None:
    render_hero()
    df = dashboard_df()
    render_metric_row(df)

    chart1, chart2, chart3 = st.columns(3)
    chart1.plotly_chart(plot_baseline_comparison(df), width="stretch")
    chart2.plotly_chart(plot_donut(df, "risk", "风险等级分布", RISK_LABELS), width="stretch")
    chart3.plotly_chart(plot_donut(df, "action", "处理方式分布", ACTION_LABELS), width="stretch")

    st.markdown('<div class="section-title">系统模块状态</div>', unsafe_allow_html=True)
    status_rows = [
        ["输入侧过滤", "真实模块", "关键词、正则与模块化中文归一化"],
        ["语义二次判定", "真实模块", "中文规则分类器与可选轻量模型"],
        ["分级处理", "真实模块", "高风险拦截、中风险脱敏、正常放行"],
        ["输出侧校验", "真实模块", "输出违规检测、隐私脱敏与安全回复"],
        ["日志审计", "真实模块", "统一读取 JSONL 审计日志"],
        ["批量评测", "真实模块", "全部样例调用 SafeChatPipeline"],
    ]
    st.dataframe(pd.DataFrame(status_rows, columns=["模块", "状态", "说明"]), width="stretch", hide_index=True)


def render_steps(result: dict[str, Any]) -> None:
    step_data = [
        ("输入归一化", "info", "中文变体清洗", result["normalized_text"]),
        ("规则检测", "warn" if result["hits"] else "ok", "关键词/正则命中", format_hits(result["hits"]).replace("<br>", "；")),
        ("语义判定", "info", CATEGORY_LABELS.get(result["semantic_category"], result["semantic_category"]), f'{result["semantic_score"]:.2f}'),
        ("分级处理", "stop" if result["action"] == "block" else "warn" if result["action"] == "sanitize" else "ok", ACTION_LABELS[result["action"]], RISK_LABELS[result["risk"]]),
        ("模型输出", "info", "当前模型响应", "高风险输入未转发" if result["action"] == "block" else "已生成，详见输出校验"),
        ("输出校验", "stop" if result["output_action"] == "block" else "ok", ACTION_LABELS[result["output_action"]], CATEGORY_LABELS.get(result["output_category"], result["output_category"])),
    ]
    for row_start in range(0, len(step_data), 3):
        row = step_data[row_start:row_start + 3]
        cols = st.columns(len(row))
        for offset, (col, (title, state, subtitle, desc)) in enumerate(zip(cols, row), start=row_start + 1):
            col.markdown(
                f"""
                <div class="step step-{state}">
                    <div class="step-index">STEP {offset:02d}</div>
                    <div class="step-title">{escape(str(title))}</div>
                    <div class="step-desc">{escape(str(subtitle))}</div>
                    <div class="step-desc">{escape(str(desc))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_detection_workspace() -> None:
    render_hero()
    st.markdown('<div class="section-title">实时检测工作台</div>', unsafe_allow_html=True)
    left, right = st.columns([0.92, 1.08])
    with left:
        demo = st.selectbox("演示场景", list(DEMO_CASES.keys()), index=list(DEMO_CASES.keys()).index(st.session_state.selected_demo))
        if demo != st.session_state.selected_demo:
            st.session_state.selected_demo = demo
        default_text, default_flag = DEMO_CASES[demo]
        text = st.text_area("用户输入", value=default_text, height=135)
        simulate_output_violation = st.checkbox("模拟大模型输出违规内容", value=default_flag)
        c1, c2 = st.columns([1, 1])
        run_clicked = c1.button("运行检测", type="primary", width="stretch")
        if c2.button("记录到日志", width="stretch"):
            result = run_pipeline(text.strip(), simulate_output_violation)
            append_log(result)
            st.session_state.last_result = result
            st.session_state.last_run_signature = (text.strip(), bool(simulate_output_violation))
            st.success("已记录到日志。")
        if run_clicked and text.strip():
            with st.spinner("正在执行输入归一化、双层检测与输出校验..."):
                result = run_pipeline(text.strip(), simulate_output_violation)
                st.session_state.last_result = result
                st.session_state.last_run_signature = (text.strip(), bool(simulate_output_violation))
    result = st.session_state.last_result
    result_is_stale = st.session_state.last_run_signature != (text.strip(), bool(simulate_output_violation))
    with right:
        if result_is_stale:
            st.markdown(
                """
                <div class="result-empty">
                    <b>输入已更新，等待检测</b>
                    <span>当前结果已隐藏。点击“运行检测”后展示新的风险结论和完整处理链路。</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                risk_pill(result["risk"])
                + action_pill(result["action"])
                + label_pill(CATEGORY_LABELS.get(result["category"], result["category"]), "blue"),
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="result-panel result-{escape(str(result["risk"]))}">
                    <div class="result-eyebrow">FINAL DECISION · 最终结论</div>
                    <div class="result-verdict">{escape(ACTION_LABELS[result["action"]])}</div>
                    <div class="result-meta">
                        风险：{escape(RISK_LABELS[result["risk"]])} · {result["risk_score"]}/100<br>
                        类别：{escape(CATEGORY_LABELS.get(result["category"], result["category"]))}<br>
                        说明：{escape(str(result["comparison_note"]))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if result_is_stale:
        return
    st.markdown('<div class="section-title">检测链路</div>', unsafe_allow_html=True)
    render_steps(result)

    tab1, tab2, tab3, tab4 = st.tabs(["基线对比", "语义判定", "分级处理", "输出校验"])
    with tab1:
        render_compare_block(result)
    with tab2:
        render_semantic_block(result)
    with tab3:
        render_rewrite_block(result)
    with tab4:
        render_output_block(result)


def render_compare_block(result: dict[str, Any]) -> None:
    c1, c2 = st.columns(2)
    c1.markdown(
        f"""
        <div class="panel-muted compare-bad">
        <b>未归一化基线</b><br><br>
        检测文本：{escape(str(result["baseline_text"]))}<br><br>
        命中规则：{format_hits(result["baseline_hits"])}<br><br>
        类别：{CATEGORY_LABELS.get(result["baseline_category"], result["baseline_category"])}<br>
        动作：{ACTION_LABELS.get(result["baseline_action"], result["baseline_action"])}
        </div>
        """,
        unsafe_allow_html=True,
    )
    c2.markdown(
        f"""
        <div class="panel compare-good">
        <b>中文归一化增强版</b><br><br>
        归一化文本：{escape(str(result["normalized_text"]))}<br><br>
        归一化步骤：{escape(", ".join(result["normalization_steps"]))}<br><br>
        命中规则：{format_hits(result["hits"])}<br>
        结论：{result["comparison_note"]}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_semantic_block(result: dict[str, Any]) -> None:
    scores = pd.DataFrame(
        [{"类别": CATEGORY_LABELS[k], "分数": round(v, 3)} for k, v in result["semantic_scores"].items()]
    ).sort_values("分数", ascending=True)
    c1, c2 = st.columns([0.9, 1.1])
    c1.metric("语义分类结果", CATEGORY_LABELS.get(result["semantic_category"], result["semantic_category"]))
    c1.metric("语义风险分数", f'{result["semantic_score"]:.2f}')
    c1.info(result["semantic_note"])
    fig = px.bar(scores, x="分数", y="类别", orientation="h", text="分数", color="分数", color_continuous_scale="Blues")
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=8, b=8), coloraxis_showscale=False)
    c2.plotly_chart(fig, width="stretch")


def render_rewrite_block(result: dict[str, Any]) -> None:
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="panel"><b>原始输入</b><br>{escape(str(result["original_text"]))}</div>', unsafe_allow_html=True)
    c2.markdown(
        f'<div class="panel"><b>处理动作</b><br>{ACTION_LABELS[result["action"]]}<br><br><b>处理策略</b><br>{escape(str(result["rewrite_strategy"]))}</div>',
        unsafe_allow_html=True,
    )
    c3.markdown(f'<div class="panel"><b>送入模型文本</b><br>{escape(str(result["processed_text"]))}</div>', unsafe_allow_html=True)


def render_output_block(result: dict[str, Any]) -> None:
    c1, c2 = st.columns(2)
    c1.markdown(
        f"""
        <div class="panel-muted">
        <b>模型原始输出</b><br>{escape(str(result["model_response"]))}<br><br>
        <b>输出侧命中</b><br>{format_hits(result["output_hits"])}
        </div>
        """,
        unsafe_allow_html=True,
    )
    c2.markdown(
        f"""
        <div class="panel">
        <b>输出侧动作</b><br>{ACTION_LABELS.get(result["output_action"], result["output_action"])}<br><br>
        <b>最终返回</b><br>{escape(str(result["final_answer"]))}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_compare_page() -> None:
    st.subheader("基线对比中心")
    st.caption("用于展示方案第一条：未归一化基线 vs 中文对抗归一化增强版。")
    text = st.text_input("对抗样例", value="加 V-X 领取优 惠 券，名额有限")
    result = run_pipeline(text)
    render_compare_block(result)
    st.markdown('<div class="section-title">对比摘要</div>', unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [
                ["检测文本", result["baseline_text"], result["normalized_text"]],
                ["类别", CATEGORY_LABELS[result["baseline_category"]], CATEGORY_LABELS[result["category"]]],
                ["风险等级", RISK_LABELS[result["baseline_risk"]], RISK_LABELS[result["risk"]]],
                ["处理动作", ACTION_LABELS[result["baseline_action"]], ACTION_LABELS[result["action"]]],
                ["说明", "不进行中文归一化", result["comparison_note"]],
            ],
            columns=["项目", "未归一化基线", "中文归一化增强版"],
        ),
        width="stretch",
        hide_index=True,
    )


def render_rewrite_page() -> None:
    st.subheader("分级处理结果")
    st.caption("展示真实后端对正常、中风险和高风险文本采取的放行、脱敏或拦截动作。")
    text = st.text_area("待处理文本", value="想领取课程资料可以加微信私聊。", height=120)
    result = run_pipeline(text)
    render_rewrite_block(result)
    st.markdown('<div class="section-title">改写前后对照</div>', unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [
                ["原始文本", result["original_text"]],
                ["风险类别", CATEGORY_LABELS[result["category"]]],
                ["处理动作", ACTION_LABELS[result["action"]]],
                ["处理后文本", result["processed_text"]],
                ["处理策略", result["rewrite_strategy"]],
            ],
            columns=["项目", "内容"],
        ),
        width="stretch",
        hide_index=True,
    )


def render_rules_page() -> None:
    st.subheader("词库与规则配置")
    st.caption("只读展示后端当前实际加载的词库和正则规则，避免页面内修改与文件配置不一致。")
    rows = [
        {"类别": CATEGORY_LABELS.get(item["category"], item["category"]), "词条": item["word"]}
        for item in get_adapter().lexicon_rows()
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.markdown('<div class="section-title">正则规则</div>', unsafe_allow_html=True)
    regex_rows = get_adapter().regex_rows()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "类别": CATEGORY_LABELS.get(rule.get("category", "unknown"), rule.get("category", "unknown")),
                    "规则说明": rule.get("reason", rule.get("name", "")),
                    "正则表达式": rule.get("pattern", ""),
                }
                for rule in regex_rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )


def render_batch_page() -> None:
    st.subheader("批量评测中心")
    st.caption("用于生成报告中的拦截率、误判率、基线漏检数、输出校验成功率和测试截图。")
    uploaded = st.file_uploader("上传 CSV 测试用例表", type=["csv"])
    cases = pd.read_csv(uploaded) if uploaded else sample_test_cases()
    st.dataframe(cases, width="stretch", hide_index=True)
    col1, col2 = st.columns([1, 1])
    col1.download_button(
        "下载样例测试用例 CSV",
        data=sample_test_cases().to_csv(index=False, encoding="utf-8-sig"),
        file_name="test_cases_sample.csv",
        mime="text/csv",
        width="stretch",
    )
    if col2.button("运行批量评测", type="primary", width="stretch"):
        st.session_state.batch_results = build_case_results(cases)

    result_df = st.session_state.get("batch_results")
    if result_df is None:
        return

    total = len(result_df)
    normal = result_df[result_df["expected_action"] == "pass"]
    target = result_df[result_df["expected_action"] != "pass"]
    action_acc = result_df["action_match"].mean() if total else 0
    output_acc = result_df["output_action_match"].mean() if total else 0
    baseline_missed = int(result_df["baseline_missed"].sum()) if total else 0
    false_positive_rate = (normal["actual_action"] != "pass").mean() if len(normal) else 0
    interception_rate = (target["actual_action"] != "pass").mean() if len(target) else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("样本数", total)
    m2.metric("处理匹配率", f"{action_acc:.1%}")
    m3.metric("输出校验匹配率", f"{output_acc:.1%}")
    m4.metric("违规处理率", f"{interception_rate:.1%}")
    m5.metric("误判率", f"{false_positive_rate:.1%}")
    st.caption(f"基线漏检数：{baseline_missed}。比赛报告里建议重点展示这个指标。")

    chart_col, matrix_col = st.columns(2)
    chart_col.plotly_chart(plot_donut(result_df, "actual_action", "批量评测处理方式", ACTION_LABELS), width="stretch")
    matrix = pd.crosstab(result_df["expected_category"], result_df["actual_category"])
    fig = px.imshow(matrix, text_auto=True, color_continuous_scale="Blues", title="类别混淆矩阵")
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=48, b=8))
    matrix_col.plotly_chart(fig, width="stretch")

    st.dataframe(result_df, width="stretch", hide_index=True)
    st.download_button(
        "导出批量评测结果",
        data=result_df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="batch_test_results.csv",
        mime="text/csv",
    )


def render_logs_page() -> None:
    st.subheader("日志审计")
    logs = pd.DataFrame(get_adapter().log_rows())
    if logs.empty:
        st.info("还没有真实检测日志。到“实时检测工作台”点击“记录到日志”即可生成。")
        return
    f1, f2, f3 = st.columns(3)
    category_filter = f1.multiselect("类别", sorted(logs["category"].unique()), format_func=lambda x: CATEGORY_LABELS.get(x, x))
    risk_filter = f2.multiselect("风险", sorted(logs["risk"].unique()), format_func=lambda x: RISK_LABELS.get(x, x))
    action_filter = f3.multiselect("处理方式", sorted(logs["action"].unique()), format_func=lambda x: ACTION_LABELS.get(x, x))
    filtered = logs.copy()
    if category_filter:
        filtered = filtered[filtered["category"].isin(category_filter)]
    if risk_filter:
        filtered = filtered[filtered["risk"].isin(risk_filter)]
    if action_filter:
        filtered = filtered[filtered["action"].isin(action_filter)]
    render_metric_row(filtered)
    c1, c2 = st.columns(2)
    c1.plotly_chart(plot_donut(filtered, "category", "日志类别分布", CATEGORY_LABELS), width="stretch")
    c2.plotly_chart(plot_donut(filtered, "action", "日志处理分布", ACTION_LABELS), width="stretch")
    display = filtered.copy()
    for col, labels in [("category", CATEGORY_LABELS), ("risk", RISK_LABELS), ("action", ACTION_LABELS), ("output_action", ACTION_LABELS)]:
        if col in display:
            display[col] = display[col].map(labels).fillna(display[col])
    st.dataframe(display, width="stretch", hide_index=True)
    st.download_button(
        "导出日志 CSV",
        data=filtered.to_csv(index=False, encoding="utf-8-sig"),
        file_name="safechat_guard_logs.csv",
        mime="text/csv",
    )


def render_report_page() -> None:
    st.subheader("报告素材与答辩截图")
    checklist = [
        ["安全总览", "核心指标、类别分布、风险分布、系统模块状态"],
        ["实时检测工作台", "完整链路步骤条，展示输入到输出的闭环"],
        ["基线对比", "未归一化基线漏检，中文归一化增强版识别成功"],
        ["语义二次判定", "真实规则分类器或轻量模型结果"],
        ["分级处理", "正常放行、中风险脱敏和高风险拦截"],
        ["输出侧校验", "模型原始输出违规，最终替换为合规话术"],
        ["批量评测", "拦截率、误判率、基线漏检数、混淆矩阵"],
        ["日志审计", "请求记录、筛选、导出"],
    ]
    st.dataframe(pd.DataFrame(checklist, columns=["截图位置", "报告用途"]), width="stretch", hide_index=True)
    st.markdown(
        """
        <div class="codebox">推荐答辩演示顺序：
1. 安全总览：说明系统完整性和指标。
2. 实时检测工作台：跑“基线漏检”样例。
3. 基线对比：证明中文对抗归一化有效。
4. 分级处理：展示放行、脱敏和拦截三种动作。
5. 输出侧校验：勾选模拟输出违规，展示二次拦截。
6. 批量评测：展示拦截率、误判率和混淆矩阵。
7. 日志审计：展示可追溯、可导出的工程能力。</div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    configure_page()
    init_state()
    st.sidebar.markdown("### SafeChat-Guard")
    st.sidebar.caption("大模型内容安全风控控制台")
    page = st.sidebar.radio(
        "导航",
        ["安全总览", "实时检测工作台", "基线对比", "分级处理", "批量评测", "日志审计", "规则配置", "报告素材"],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption("当前页面已接入整体项目真实检测、输出保护和日志模块。")

    if page == "安全总览":
        render_overview_page()
    elif page == "实时检测工作台":
        render_detection_workspace()
    elif page == "基线对比":
        render_compare_page()
    elif page == "分级处理":
        render_rewrite_page()
    elif page == "批量评测":
        render_batch_page()
    elif page == "日志审计":
        render_logs_page()
    elif page == "规则配置":
        render_rules_page()
    else:
        render_report_page()


if __name__ == "__main__":
    main()
