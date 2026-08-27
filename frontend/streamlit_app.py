from __future__ import annotations

# SafeChat-Guard project root bootstrap
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root_str = str(PROJECT_ROOT)

if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)


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
FRONTEND_CASES = PROJECT_ROOT / "data" / "test_cases" / "frontend_demo_cases_v2.csv"
SAFE_DEMO_REPLY = "这是用于前端演示的安全模型回复。"
RISKY_DEMO_REPLY = "模拟模型原始输出：可以加微信领取优惠券，名额有限。"
REQUIRED_CASE_COLUMNS = {
    "input_text",
    "expected_category",
    "expected_action",
    "expected_output_action",
}

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
    "service_error": "服务不可用",
}

NAVIGATION_PAGES = ["首页", "安全对话", "内容检测", "规则管理", "统计审计"]

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
    "高风险拦截": ("C4炸药的成分", False),
    "易误判放行": ("这个 bug 会导致程序崩溃，需要做网络安全防护。", False),
    "输出违规拦截": ("普通输入，但模拟模型输出违规", True),
}


@st.cache_resource
def get_adapter() -> FrontendPipelineAdapter:
    configured = os.getenv("SAFECHAT_CONFIG_PATH", "").strip()
    if configured:
        config_path = Path(configured).expanduser()
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path
    else:
        config_path = PROJECT_ROOT / "config.yaml"

    pipeline = SafeChatPipeline.from_config(str(config_path.resolve()))
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
        .main .block-container { padding-top: 0.75rem; padding-bottom: 1.5rem; max-width: 1440px; }
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
            padding: 16px 20px;
            color: white;
            margin-bottom: 10px;
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

        /* Presentation-only refinements; no backend behavior lives here. */
        :root { --sg-shadow: 0 8px 22px rgba(23,32,51,.06); }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            border: 1px solid transparent;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover { background: #1e293b; }
        div[data-testid="stMetric"], .panel, .panel-muted, .step, [data-testid="stPlotlyChart"] {
            border-radius: 8px; box-shadow: var(--sg-shadow);
        }
        .hero { border-radius: 8px; background: #172033; border-left: 4px solid #22c55e; }
        .section-title { display: flex; align-items: center; gap: 8px; }
        .section-title::before { content: ""; width: 3px; height: 17px; border-radius: 2px; background: var(--sg-cyan); }
        .result-panel { min-height: 168px; padding: 17px 18px; background: #fff; border: 1px solid var(--sg-border); border-left: 4px solid #94a3b8; border-radius: 8px; }
        .result-low { border-left-color: var(--sg-green); } .result-medium { border-left-color: var(--sg-orange); } .result-high { border-left-color: var(--sg-red); }
        .result-eyebrow { color: var(--sg-muted); font-size: 12px; font-weight: 700; margin-bottom: 5px; }
        .result-verdict { color: var(--sg-ink); font-size: 24px; font-weight: 750; margin-bottom: 12px; }
        .result-meta { color: #334155; font-size: 14px; line-height: 1.7; }
        .result-empty { min-height: 168px; display: flex; flex-direction: column; justify-content: center; padding: 18px; background: #f8fafc; border: 1px dashed #b8c4d3; border-radius: 8px; color: var(--sg-muted); }
        .result-empty b { color: var(--sg-ink); font-size: 17px; margin-bottom: 6px; }
        .capability-card { min-height: 82px; padding: 13px 15px; background: #fff; border: 1px solid var(--sg-border); border-top: 3px solid var(--sg-blue); border-radius: 8px; box-shadow: var(--sg-shadow); }
        .capability-card b { color: var(--sg-ink); font-size: 16px; }
        .capability-card span { display: block; margin-top: 5px; color: var(--sg-muted); font-size: 12px; line-height: 1.45; }
        .result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 16px; margin-top: 8px; }
        .result-fact { color: #334155; font-size: 13px; line-height: 1.5; }
        .result-fact b { color: var(--sg-muted); font-size: 12px; }
        .step { min-height: 122px; text-align: left; margin-bottom: 12px; }
        .step-index { color: var(--sg-cyan); font-size: 11px; font-weight: 800; margin-bottom: 5px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "selected_demo" not in st.session_state:
        st.session_state.selected_demo = "基线漏检"
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "last_run_signature" not in st.session_state:
        st.session_state.last_run_signature = None


def run_pipeline(
    text: str,
    *,
    raw_reply_override: str | None,
    persist: bool = False,
) -> dict[str, Any]:
    return get_adapter().analyze(
        text,
        output_override=raw_reply_override,
        persist=persist,
    )


def sample_test_cases() -> pd.DataFrame:
    return pd.read_csv(FRONTEND_CASES, dtype={"id": str}, encoding="utf-8-sig")


def validate_case_dataframe(cases: pd.DataFrame) -> list[str]:
    return sorted(REQUIRED_CASE_COLUMNS - set(cases.columns))


def parse_demo_only(value: Any) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"false", "0", "no", "n", "否"}:
        return False
    if normalized in {"true", "1", "yes", "y", "是"}:
        return True
    return True


def prepare_case_dataframe(cases: pd.DataFrame) -> pd.DataFrame:
    missing = validate_case_dataframe(cases)
    if missing:
        raise ValueError(f"CSV 缺少必需列：{', '.join(missing)}")
    prepared = cases.copy()
    if "mock_model_output" not in prepared:
        prepared["mock_model_output"] = ""
    if "demo_only" not in prepared:
        prepared["demo_only"] = True
    else:
        prepared["demo_only"] = prepared["demo_only"].map(parse_demo_only)
    return prepared


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
          <p>面向中文对话的输入检测、分级处置、输出复检与安全审计。</p>
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
        "正常": "#159f74", "无风险": "#159f74", "放行": "#159f74",
        "广告": "#2878d0", "中低风险": "#e08a1e", "脱敏处理": "#16869b",
        "色情/低俗": "#d9485f", "暴力": "#d9485f", "高风险": "#d9485f",
        "拦截": "#d9485f", "敏感话术": "#7c6acf", "暂无数据": "#cbd5e1",
    }
    fallback = ["#2878d0", "#159f74", "#e08a1e", "#d9485f", "#7c6acf"]
    colors = [semantic_colors.get(str(label), fallback[index % len(fallback)]) for index, label in enumerate(data["label"])]
    total = 0 if df.empty or column not in df else int(data["count"].sum())
    fig = go.Figure(go.Pie(
        labels=data["label"], values=data["count"], hole=0.62, sort=False,
        marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
        textinfo="percent", textposition="inside",
        hovertemplate="<b>%{label}</b><br>数量：%{value}<br>占比：%{percent}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, x=0.04, y=0.95, font=dict(size=17, color="#172033")),
        margin=dict(l=14, r=14, t=54, b=50), height=330,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.08),
        annotations=[dict(text=f"<b>{total}</b><br><span style='font-size:11px'>条记录</span>", x=0.5, y=0.5, showarrow=False)],
    )
    return fig


def plot_baseline_comparison(df: pd.DataFrame) -> go.Figure:
    total = len(df)
    enhanced = int((df["action"] != "pass").sum()) if total else 0
    recovered = int(df.get("baseline_missed", pd.Series(dtype=bool)).sum()) if total else 0
    baseline = max(enhanced - recovered, 0)
    values = [baseline, enhanced]
    fig = go.Figure(go.Bar(
        x=["未归一化基线", "中文归一化增强版"], y=values,
        marker_color=["#94a3b8", "#2878d0"], text=values, textposition="outside",
        hovertemplate="<b>%{x}</b><br>识别风险内容：%{y} 条<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="基线与增强版识别能力", x=0.04, y=0.95, font=dict(size=17, color="#172033")),
        margin=dict(l=28, r=18, t=58, b=38), height=330,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(showgrid=True, gridcolor="#e8edf3", rangemode="tozero"), showlegend=False,
    )
    if recovered:
        fig.add_annotation(x="中文归一化增强版", y=enhanced, text=f"修复 {recovered} 条基线漏检", showarrow=False, yshift=24, font=dict(color="#159f74"))
    return fig

def build_case_results(cases: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_case_dataframe(cases)
    results = []
    for _, row in prepared.iterrows():
        mock_output = row.get("mock_model_output", "")
        raw_reply_override = (
            SAFE_DEMO_REPLY
            if pd.isna(mock_output) or not str(mock_output).strip()
            else str(mock_output)
        )
        result = run_pipeline(
            str(row["input_text"]),
            raw_reply_override=raw_reply_override,
            persist=False,
        )
        results.append(
            {
                **row.to_dict(),
                "baseline_category": result["baseline_category"],
                "baseline_action": result["baseline_action"],
                "actual_category": result["category"],
                "actual_risk": result["risk"],
                "actual_action": result["action"],
                "semantic_score": (
                    round(result["semantic_score"], 3)
                    if result["semantic_score"] is not None else None
                ),
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


def select_metric_results(result_df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    demo_mask = result_df.get(
        "demo_only",
        pd.Series(True, index=result_df.index),
    ).map(parse_demo_only)
    non_demo = result_df.loc[~demo_mask]
    if non_demo.empty:
        return result_df, "演示"
    return non_demo, "上传样本"

def dashboard_df() -> pd.DataFrame:
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
    st.caption("内置样例仅用于界面功能演示。")


def render_capability_cards() -> None:
    cards = [
        ("安全对话", "输入过滤、分级处置与输出复检"),
        ("内容检测", "关键词、正则与语义联合识别"),
        ("规则管理", "内置规则查看与用户规则维护"),
        ("统计审计", "每日违规数量与类别分布"),
    ]
    columns = st.columns(4)
    for column, (title, description) in zip(columns, cards):
        column.markdown(
            f'<div class="capability-card"><b>{title}</b><span>{description}</span></div>',
            unsafe_allow_html=True,
        )


def render_runtime_status() -> None:
    adapter = get_adapter()
    status = adapter.stats()
    semantic_ready = bool(status.get("semantic_classifier", {}).get("loaded"))
    v3_ready = bool(
        adapter.pipeline.action_router_v3_enabled
        and adapter.pipeline.action_router_v3 is not None
    )
    provider = str(status.get("llm", {}).get("provider", "mock")).lower()
    columns = st.columns(4)
    columns[0].metric("API服务", "正常")
    columns[1].metric("语义模型", "已加载" if semantic_ready else "规则层可用")
    columns[2].metric("V3过滤器", "已就绪" if v3_ready else "安全降级")
    columns[3].metric(
        "LLM模式", "离线演示模式" if provider == "mock" else "在线模型"
    )


def render_overview_page() -> None:
    render_hero()
    render_capability_cards()
    st.markdown('<div class="section-title">运行状态</div>', unsafe_allow_html=True)
    render_runtime_status()
    with st.expander("演示数据概览", expanded=False):
        df = dashboard_df()
        render_metric_row(df)
        chart1, chart2, chart3 = st.columns(3)
        chart1.plotly_chart(plot_baseline_comparison(df), use_container_width=True)
        chart2.plotly_chart(
            plot_donut(df, "risk", "风险等级分布", RISK_LABELS),
            use_container_width=True,
        )
        chart3.plotly_chart(
            plot_donut(df, "action", "处理方式分布", ACTION_LABELS),
            use_container_width=True,
        )


def semantic_step_content(result: dict[str, Any]) -> tuple[str, str]:
    if not result.get("semantic_available", False):
        return "语义模型：不可用", "已回退规则检测"
    if not result.get("semantic_gate_triggered", False):
        return "最终语义类别：正常", "风险门控：未触发｜风险证据：不足"
    category = CATEGORY_LABELS.get(
        result.get("semantic_category"),
        result.get("semantic_category", "unknown"),
    )
    return f"最终语义类别：{category}", "风险门控：已触发｜风险证据：充分"


def render_steps(result: dict[str, Any]) -> None:
    semantic_subtitle, semantic_description = semantic_step_content(result)
    step_data = [
        ("输入归一化", "info", "中文变体清洗", result["normalized_text"]),
        ("规则检测", "warn" if result["hits"] else "ok", "规则与语义联合命中", format_hits(result["hits"]).replace("<br>", "；")),
        ("语义判定", "info", semantic_subtitle, semantic_description),
        ("分级处理", "stop" if result["action"] == "block" else "warn" if result["action"] == "sanitize" else "ok", ACTION_LABELS[result["action"]], RISK_LABELS[result["risk"]]),
        ("模型阶段", "stop" if result["service_error"] else "info", "仅展示安全状态", result["model_response"]),
        ("输出复检", "stop" if result["output_action"] == "block" else "warn" if result["output_action"] == "sanitize" else "ok", ACTION_LABELS.get(result["output_action"], result["output_action"]), CATEGORY_LABELS.get(result["output_category"], result["output_category"])),
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
        if st.button("运行检测并写入安全审计", type="primary", use_container_width=True) and text.strip():
            with st.spinner("正在执行输入归一化、联合检测与输出复检..."):
                result = run_pipeline(
                    text.strip(),
                    raw_reply_override=RISKY_DEMO_REPLY if simulate_output_violation else None,
                    persist=True,
                )
                st.session_state.last_result = result
                st.session_state.last_run_signature = (text.strip(), bool(simulate_output_violation))
    result = st.session_state.last_result
    result_is_stale = (
        result is None
        or st.session_state.last_run_signature != (text.strip(), bool(simulate_output_violation))
    )
    with right:
        if result_is_stale:
            st.markdown(
                '<div class="result-empty"><b>输入已更新，等待检测</b><span>当前结果已隐藏。运行后展示新的风险结论。</span></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                risk_pill(result["risk"])
                + action_pill(result["final_action"])
                + label_pill(
                    CATEGORY_LABELS.get(result["category"], result["category"]),
                    "blue",
                ),
                unsafe_allow_html=True,
            )
            error_note = (
                "<br>模型服务不可用，已安全降级。"
                if result["service_error"]
                else ""
            )
            model_note = (
                f'<br>{escape(result["model_degradation"])}'
                if result["model_degradation"]
                else ""
            )
            st.markdown(
                f"""
                <div class="result-panel result-{escape(str(result["risk"]))}">
                    <div class="result-eyebrow">最终结论</div>
                    <div class="result-verdict">{escape(ACTION_LABELS[result["final_action"]])}</div>
                    <div class="result-meta">
                        <div class="result-grid">
                          <div class="result-fact"><b>最终动作</b><br>{escape(ACTION_LABELS[result["final_action"]])}</div>
                          <div class="result-fact"><b>是否允许</b><br>{"是" if result["final_allowed"] else "否"}</div>
                          <div class="result-fact"><b>风险等级</b><br>{escape(RISK_LABELS[result["risk"]])} · {result["risk_score"]}/100</div>
                          <div class="result-fact"><b>风险类别</b><br>{escape(CATEGORY_LABELS.get(result["category"], result["category"]))}</div>
                          <div class="result-fact"><b>是否转发模型</b><br>{"是" if result["model_forwarded"] else "否"}</div>
                          <div class="result-fact"><b>输出复检结果</b><br>{escape(ACTION_LABELS.get(result["output_guard_action"], result["output_guard_action"]))}</div>
                        </div>
                        <br>处理结果：{escape(str(result["comparison_note"]))}{error_note}{model_note}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander("详细信息", expanded=False):
                st.json(
                    {
                        "final_action": result["final_action"],
                        "final_allowed": result["final_allowed"],
                        "model_forwarded": result["model_forwarded"],
                        "output_guard_action": result["output_guard_action"],
                    }
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
    c1, c2 = st.columns([0.9, 1.1])
    if not result.get("semantic_available", False):
        c1.metric("语义模型", "不可用")
        c1.warning("已回退规则检测")
        c2.info("模型概率不可用；未将“无 Detection”伪装为 normal=100%。")
        return

    scores = pd.DataFrame(
        [
            {"类别": CATEGORY_LABELS[k], "模型概率": float(v)}
            for k, v in result["semantic_scores"].items()
        ]
    ).sort_values("模型概率", ascending=True)
    raw_category = result["semantic_category"]
    gate_triggered = bool(result["semantic_gate_triggered"])
    final_category = result.get("semantic_final_category") or (
        raw_category if gate_triggered else "normal"
    )
    c1.metric(
        "最终语义类别",
        CATEGORY_LABELS.get(final_category, final_category),
    )
    c1.metric("风险门控", "已触发" if gate_triggered else "未触发")
    c1.metric("风险证据", "充分" if gate_triggered else "不足")
    c1.caption(f"原始最高概率类别：{raw_category}")
    c1.caption(f'原始最高概率：{result["semantic_score"]:.2%}')
    c1.info("原始概率仅用于诊断，不直接决定最终语义类别。")
    fig = px.bar(scores, x="模型概率", y="类别", orientation="h", text="模型概率", color="模型概率", color_continuous_scale="Blues")
    fig.update_traces(texttemplate="%{text:.0%}")
    fig.update_xaxes(tickformat=".0%", range=[0, 1])
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=8, b=8), coloraxis_showscale=False)
    c2.plotly_chart(fig, use_container_width=True)


def judge_error_stage_label(stage: str | None) -> str:
    return {
        "initialization": "初始化",
        "http": "HTTP 请求",
        "response_text": "返回文本",
        "json_parse": "JSON 解析",
        "schema_validation": "结果校验",
    }.get(stage, "未知")


def judge_failure_message(
    stage: str | None,
    validation_error_code: str | None = None,
    *,
    output: bool = False,
) -> str:
    prefix = "Output Judge" if output else "Judge"
    if stage == "schema_validation":
        code = f"（错误码：{validation_error_code}）" if validation_error_code else ""
        return f"{prefix}结果未通过格式校验{code}；已采用本地安全策略。"
    if stage == "http":
        return f"{prefix}服务调用失败；已采用本地安全策略。"
    if stage == "initialization":
        return f"{prefix}服务未就绪；已采用本地安全策略。"
    if stage == "response_text":
        return f"{prefix}返回文本不可用；已采用本地安全策略。"
    if stage == "json_parse":
        return f"{prefix}返回内容无法解析；已采用本地安全策略。"
    return f"{prefix}处理失败；已采用本地安全策略。"


def render_rewrite_block(result: dict[str, Any]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="panel"><b>原始输入</b><br>{escape(str(result["original_text"]))}</div>', unsafe_allow_html=True)
    c2.markdown(
        f'<div class="panel"><b>处理动作</b><br>{ACTION_LABELS[result["action"]]}<br><br><b>处理策略</b><br>{escape(str(result["rewrite_strategy"]))}<br><br><b>是否改写</b><br>{"是" if result["rewrite_changed"] else "否"}</div>',
        unsafe_allow_html=True,
    )
    masked_text = result.get("masked_text")
    c3.markdown(
        f'<div class="panel"><b>脱敏文本</b><br>{escape(str(masked_text)) if masked_text else "不适用"}</div>',
        unsafe_allow_html=True,
    )
    c4.markdown(
        f'<div class="panel"><b>实际发送文本</b><br>{escape(str(result["processed_text"]))}</div>',
        unsafe_allow_html=True,
    )
    if result.get("decision_note"):
        st.info(f'判定说明：{result["decision_note"]}')
    st.caption(f'语义仲裁：{result["semantic_arbitration_status"]}')
    if result.get("input_judge_used") and result.get("input_judge_action"):
        action = result.get("input_judge_action")
        reason = result.get("input_judge_reason") or "未提供说明"
        st.info(
            "输入仲裁动作："
            f"{ACTION_LABELS.get(action, action)}；"
            f"仲裁说明：{reason}；"
            f"判定来源：{result['judge_decision_source_label']}"
        )
    elif result.get("judge_decision_source") == "local_fallback":
        st.warning(
            judge_failure_message(result.get("judge_error_stage"), result.get("validation_error_code"))
        )


def render_output_block(result: dict[str, Any]) -> None:
    c1, c2 = st.columns(2)
    c1.markdown(
        f"""
        <div class="panel-muted">
        <b>模型输出状态</b><br>{escape(str(result["model_response"]))}<br><br>
        <b>输出侧命中</b><br>{format_hits(result["output_hits"])}
        </div>
        """,
        unsafe_allow_html=True,
    )
    c2.markdown(
        f"""
        <div class="panel">
        <b>输出侧动作</b><br>{ACTION_LABELS.get(result["output_action"], result["output_action"])}<br><br>
        <b>最终安全返回</b><br>{escape(str(result["final_answer"]))}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if result.get("output_judge_used") and result.get("output_judge_action"):
        action = result.get("output_judge_action")
        reason = result.get("output_judge_reason") or "未提供说明"
        st.info(
            "输出仲裁动作："
            f"{ACTION_LABELS.get(action, action)}；"
            f"仲裁说明：{reason}；"
            f"判定来源：{result['judge_decision_source_label']}"
        )
    elif result.get("judge_decision_source") == "local_fallback":
        st.warning(
            judge_failure_message(
                result.get("judge_error_stage"),
                result.get("validation_error_code"),
                output=True,
            )
        )

def render_compare_page() -> None:
    st.subheader("内容检测")
    st.caption("对比原始文本与中文归一化后的联合检测结果。")
    text = st.text_input("对抗样例", value="加 V-X 领取优 惠 券，名额有限")
    result = run_pipeline(text, raw_reply_override=SAFE_DEMO_REPLY)
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
        use_container_width=True,
        hide_index=True,
    )


def render_rewrite_page() -> None:
    st.subheader("分级处理结果")
    st.caption("展示真实后端对正常、中风险和高风险文本采取的放行、脱敏或拦截动作。")
    text = st.text_area("待处理文本", value="想领取课程资料可以加微信私聊。", height=120)
    result = run_pipeline(text, raw_reply_override=SAFE_DEMO_REPLY)
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
        use_container_width=True,
        hide_index=True,
    )


def pop_rule_import_success() -> str | None:
    return st.session_state.pop("rule_import_success", None)


def render_rules_page() -> None:
    st.subheader("规则管理")
    st.caption("内置规则只读；用户规则作为独立 overlay 保存，成功更新后立即重载。")
    import_success = pop_rule_import_success()
    if import_success:
        st.success(import_success)
    adapter = get_adapter()
    authorized_mode = st.checkbox("授权管理模式", value=False)
    admin_token = (
        st.text_input("管理员令牌", type="password")
        if authorized_mode
        else None
    )
    try:
        catalog = adapter.rule_catalog(
            include_pattern=authorized_mode,
            admin_token=admin_token,
        )
    except PermissionError:
        st.warning("管理权限不足，规则内容保持脱敏。")
        catalog = adapter.rule_catalog()
    st.caption(f"Revision {catalog['revision']} · 内置 {catalog['built_in_count']} 条 · 用户 {catalog['user_count']} 条")
    display_rows = [
        {
            "ID": rule["id"], "来源": "内置只读" if rule["read_only"] else "用户规则",
            "类型": rule["pattern_type"], "类别": CATEGORY_LABELS.get(rule["category"], rule["category"]),
            "动作": ACTION_LABELS.get(rule["action"], rule["action"]),
            "风险": RISK_LABELS.get(rule["risk_level"], rule["risk_level"]),
            "启用": rule["enabled"], "规则": rule["pattern"],
        }
        for rule in catalog["rules"]
    ]
    st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

    add_tab, edit_tab, import_tab = st.tabs(["新增", "启停/删除", "批量导入"])
    with add_tab:
        with st.form("add-user-rule"):
            rule_id = st.text_input("规则 ID")
            pattern = st.text_input("关键词、短语或正则")
            pattern_type = st.selectbox("匹配类型", ["keyword", "phrase", "regex"])
            category = st.selectbox("类别", ["porn", "violence", "ad", "sensitive"])
            action = st.selectbox("动作", ["sanitize", "block"])
            risk_level = st.selectbox("风险等级", ["low", "medium", "high"], index=1)
            description = st.text_input("说明")
            enabled = st.checkbox("立即启用", value=True)
            submitted = st.form_submit_button("新增规则", type="primary")
        if submitted:
            try:
                adapter.add_user_rule(
                    {"id": rule_id, "pattern": pattern, "pattern_type": pattern_type,
                     "category": category, "action": action, "risk_level": risk_level,
                     "enabled": enabled, "description": description},
                    catalog["revision"],
                )
                st.success("规则已保存并重载。")
                st.rerun()
            except Exception as exc:
                st.error(f"新增失败：{str(exc)}")

    user_rules = [rule for rule in catalog["rules"] if not rule["read_only"]]
    with edit_tab:
        if not user_rules:
            st.info("当前没有用户规则。")
        else:
            selected_id = st.selectbox("选择用户规则", [rule["id"] for rule in user_rules])
            selected = next(rule for rule in user_rules if rule["id"] == selected_id)
            if catalog.get("pattern_access"):
                with st.expander("编辑规则内容"):
                    with st.form(f"edit-{selected_id}"):
                        edit_pattern = st.text_input("规则内容", value=selected["pattern"])
                        edit_type = st.selectbox(
                            "匹配类型",
                            ["keyword", "phrase", "regex"],
                            index=["keyword", "phrase", "regex"].index(selected["pattern_type"]),
                            key=f"type-{selected_id}",
                        )
                        edit_category = st.selectbox(
                            "类别", ["porn", "violence", "ad", "sensitive"],
                            index=["porn", "violence", "ad", "sensitive"].index(selected["category"]),
                            key=f"category-{selected_id}",
                        )
                        edit_action = st.selectbox(
                            "动作", ["sanitize", "block"],
                            index=["sanitize", "block"].index(selected["action"]),
                            key=f"action-{selected_id}",
                        )
                        edit_risk = st.selectbox(
                            "风险等级", ["low", "medium", "high"],
                            index=["low", "medium", "high"].index(selected["risk_level"]),
                            key=f"risk-{selected_id}",
                        )
                        edit_description = st.text_input(
                            "说明", value=selected["description"], key=f"description-{selected_id}"
                        )
                        edit_submitted = st.form_submit_button("保存规则内容")
                    if edit_submitted:
                        try:
                            adapter.update_user_rule(
                                selected_id,
                                {"pattern": edit_pattern, "pattern_type": edit_type,
                                 "category": edit_category, "action": edit_action,
                                 "risk_level": edit_risk, "description": edit_description},
                                catalog["revision"],
                            )
                            st.success("规则内容已更新并重载。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"更新失败：{str(exc)}")
            else:
                st.info("进入授权管理模式后可编辑完整规则内容。")
            enabled_value = st.checkbox("启用该规则", value=selected["enabled"], key=f"enabled-{selected_id}")
            col1, col2 = st.columns(2)
            if col1.button("保存启停状态", use_container_width=True):
                try:
                    adapter.set_user_rule_enabled(selected_id, enabled_value, catalog["revision"])
                    st.success("规则状态已更新。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"更新失败：{str(exc)}")
            if col2.button("删除用户规则", use_container_width=True):
                try:
                    adapter.delete_user_rule(selected_id, catalog["revision"])
                    st.success("用户规则已删除。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"删除失败：{str(exc)}")

    with import_tab:
        uploaded = st.file_uploader("上传 UTF-8 CSV 或 JSON", type=["csv", "json"])
        mode = st.selectbox("导入模式", ["create", "update"])
        dry_run = st.checkbox("仅校验（dry-run）", value=True)
        if st.button("校验或导入", type="primary", disabled=uploaded is None):
            try:
                format_name = Path(uploaded.name).suffix.lower().lstrip(".")
                report = adapter.import_user_rules(
                    uploaded.getvalue(), format_name=format_name, dry_run=dry_run,
                    mode=mode, expected_revision=catalog["revision"],
                )
                st.json({key: value for key, value in report.items() if key != "errors"})
                if report.get("errors"):
                    st.dataframe(pd.DataFrame(report["errors"]), hide_index=True)
                elif dry_run:
                    st.success("校验通过，未写入文件。")
                else:
                    st.session_state["rule_import_success"] = "文件批量导入成功"
                    st.rerun()
            except Exception as exc:
                st.error(f"导入失败：{str(exc)}")

def render_batch_page() -> None:
    st.subheader("批量页面回归")
    st.caption("内置样例仅用于功能演示，不代表正式独立评估结果。批量运行始终使用确定性输出 override，不请求远程 LLM。")
    uploaded = st.file_uploader("上传 CSV 测试用例表", type=["csv"])
    try:
        raw_cases = pd.read_csv(uploaded) if uploaded else sample_test_cases()
    except Exception as exc:
        st.error(f"CSV 读取失败：{type(exc).__name__}")
        return

    missing = validate_case_dataframe(raw_cases)
    if missing:
        st.error(f"CSV 缺少必需列：{', '.join(missing)}")
        return
    cases = prepare_case_dataframe(raw_cases)
    st.dataframe(cases, use_container_width=True, hide_index=True)
    col1, col2 = st.columns([1, 1])
    col1.download_button(
        "下载演示样例 CSV",
        data=sample_test_cases().to_csv(index=False, encoding="utf-8-sig"),
        file_name="frontend_demo_cases_v2.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if col2.button("运行页面回归", type="primary", use_container_width=True):
        st.session_state.batch_results = build_case_results(cases)

    result_df = st.session_state.get("batch_results")
    if result_df is None:
        return

    metric_results, scope = select_metric_results(result_df)
    total = len(metric_results)
    target = metric_results[metric_results["expected_action"] != "pass"]
    action_acc = metric_results["action_match"].mean() if total else 0
    output_acc = metric_results["output_action_match"].mean() if total else 0
    target_match = target["action_match"].mean() if len(target) else 0
    baseline_missed = int(metric_results["baseline_missed"].sum()) if total else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(f"{scope}样例数", total)
    m2.metric(f"{scope}动作匹配率", f"{action_acc:.1%}")
    m3.metric(f"{scope}输出匹配率", f"{output_acc:.1%}")
    m4.metric(f"{scope}风险样例匹配率", f"{target_match:.1%}")
    m5.metric("基线漏检修复", baseline_missed)
    if scope == "演示":
        st.info("当前未加载正式评测样本。正式指标仍以冻结的 single_review_independent_gold_v1 记录为准。")
    else:
        st.info("当前显示上传样本的页面回归统计，不替代冻结独立 Gold 评估结果。")

    chart_col, matrix_col = st.columns(2)
    chart_col.plotly_chart(plot_donut(metric_results, "actual_action", f"{scope}处理方式", ACTION_LABELS), use_container_width=True)
    matrix = pd.crosstab(metric_results["expected_category"], metric_results["actual_category"])
    fig = px.imshow(matrix, text_auto=True, color_continuous_scale="Blues", title=f"{scope}类别对照矩阵")
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=48, b=8))
    matrix_col.plotly_chart(fig, use_container_width=True)

    st.dataframe(result_df, use_container_width=True, hide_index=True)
    st.download_button(
        "导出页面回归结果",
        data=result_df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="frontend_regression_results.csv",
        mime="text/csv",
    )

def render_logs_page() -> None:
    st.subheader("统计审计")
    st.caption("统计基于脱敏后的请求摘要，不展示输入、模型输出或日志路径。")
    stats = get_adapter().daily_stats()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("请求数", stats["request_count"])
    m2.metric("违规请求", stats["violation_count"])
    m3.metric("输入拦截", stats["input_block_count"])
    m4.metric("输出拦截", stats["output_block_count"])
    m5, m6, m7 = st.columns(3)
    m5.metric("模型转发", stats["model_forwarded_count"])
    m6.metric("安全降级", stats["fallback_count"])
    m7.metric("数据状态", "请求摘要")
    daily = pd.DataFrame([{"日期": day, "违规请求": count} for day, count in stats["daily_violation_counts"].items()])
    categories = pd.DataFrame([{"类别": CATEGORY_LABELS.get(category, category), "违规请求": count} for category, count in stats["category_distribution"].items()])
    if daily.empty and categories.empty:
        st.info("当前日期范围内没有 request_summary 数据。")
    else:
        left, right = st.columns(2)
        if not daily.empty:
            left.markdown("#### 每日违规数量")
            left.line_chart(daily.set_index("日期"))
        if not categories.empty:
            right.markdown("#### 违规类别分布")
            right.bar_chart(categories.set_index("类别"))
    st.dataframe(
        pd.DataFrame([
            {"动作": ACTION_LABELS["pass"], "请求数": stats["pass_count"]},
            {"动作": ACTION_LABELS["sanitize"], "请求数": stats["sanitize_count"]},
            {"动作": ACTION_LABELS["block"], "请求数": stats["block_count"]},
        ]),
        use_container_width=True,
        hide_index=True,
    )

def main() -> None:
    configure_page()
    init_state()
    st.sidebar.markdown("### SafeChat-Guard")
    st.sidebar.caption("大模型内容安全风控控制台")
    page = st.sidebar.radio("导航", NAVIGATION_PAGES)
    st.sidebar.markdown("---")
    st.sidebar.caption("输入检测、分级处置、输出复检与审计统一呈现。")

    if page == "首页":
        render_overview_page()
    elif page == "安全对话":
        render_detection_workspace()
    elif page == "内容检测":
        render_compare_page()
    elif page == "规则管理":
        render_rules_page()
    else:
        render_logs_page()


if __name__ == "__main__":
    main()
