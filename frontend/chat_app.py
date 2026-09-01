"""SafeChat-Guard V1.0 product chat experience."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.llm_adapters import LLMAdapterFactory, PROVIDER_LABELS
from safechat_guard.model_registry import ModelRegistry
from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.version import PRODUCT_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
MODEL_STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "model_registry.json"

CATEGORY_LABELS = {
    "normal": "正常",
    "ad": "广告引流",
    "porn": "色情低俗",
    "violence": "暴力风险",
    "sensitive": "敏感内容",
    "abuse": "低俗辱骂",
    "privacy": "隐私信息",
    "illegal": "违法违规",
    "self_harm": "自伤风险",
}
RISK_LABELS = {"none": "无风险", "low": "低风险", "medium": "中风险", "high": "高风险"}
ACTION_LABELS = {"pass": "通过", "sanitize": "已安全处理", "block": "已拦截", "not_run": "未执行"}


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


@st.cache_resource(show_spinner=False)
def get_model_registry() -> ModelRegistry:
    return ModelRegistry(load_config(), state_path=MODEL_STATE_PATH)


@st.cache_resource(show_spinner=False)
def get_chat_adapter(provider: str) -> FrontendPipelineAdapter:
    config = load_config()
    provider_config = get_model_registry().provider_config(provider)
    pipeline = SafeChatPipeline(config, project_root=PROJECT_ROOT)
    pipeline.llm = LLMAdapterFactory.create(provider_config)
    return FrontendPipelineAdapter(pipeline)


def configure_product_page() -> None:
    st.set_page_config(
        page_title=f"SafeChat-Guard {PRODUCT_VERSION}",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { --navy:#10233f; --blue:#1f65d6; --sky:#eaf2ff; --line:#dce5f1;
                --ink:#132238; --muted:#68788e; --safe:#207a55; --warn:#a86713; --stop:#b63b45; }
        .stApp { background:#f7f9fc; color:var(--ink); }
        .main .block-container { max-width:850px; padding-top:1.4rem; padding-bottom:6rem; }
        [data-testid="stSidebar"] { background:#f0f5fb; border-right:1px solid var(--line); }
        .sg-header { border-bottom:1px solid var(--line); padding:0 0 1.15rem; margin-bottom:1.2rem; }
        .sg-kicker { color:var(--blue); font:700 .72rem/1.2 ui-monospace,Consolas,monospace;
                     letter-spacing:.12em; text-transform:uppercase; }
        .sg-title { color:var(--navy); font-size:2rem; font-weight:760; letter-spacing:-.035em; margin:.3rem 0 .2rem; }
        .sg-subtitle { color:var(--muted); font-size:.95rem; }
        .sg-runtime { display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.75rem; }
        .sg-chip { border:1px solid var(--line); border-radius:999px; background:white; color:#43536a;
                   font-size:.75rem; padding:.28rem .65rem; }
        .sg-chip.ready { border-color:#b9ddce; background:#f1faf6; color:var(--safe); }
        .sg-seal { border:1px solid var(--line); border-left:3px solid var(--safe); border-radius:10px;
                   background:#fbfdff; margin:.65rem 0 .2rem; padding:.62rem .75rem; }
        .sg-seal.sanitize { border-left-color:var(--warn); }
        .sg-seal.block { border-left-color:var(--stop); }
        .sg-seal-row { display:flex; flex-wrap:wrap; gap:.45rem .9rem; color:#4d5d72; font-size:.78rem; }
        .sg-seal-row b { color:var(--ink); font-weight:650; }
        [data-testid="stChatMessage"] { background:white; border:1px solid var(--line); border-radius:14px;
                                        padding:.25rem .55rem; box-shadow:0 3px 12px rgba(16,35,63,.035); }
        [data-testid="stChatInput"] { border-color:#cbd8e7; }
        .sg-empty { color:var(--muted); text-align:center; padding:3.6rem 1rem 2.6rem; }
        .sg-empty b { display:block; color:var(--navy); font-size:1.1rem; margin-bottom:.35rem; }
        @media (max-width:640px) { .main .block-container{padding-top:.75rem}.sg-title{font-size:1.55rem} }
        @media (prefers-reduced-motion:reduce) { * { scroll-behavior:auto !important; transition:none !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_chat_state(default_provider: str) -> None:
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("selected_provider", default_provider)
    st.session_state.setdefault("request_in_progress", False)


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return "模型服务响应超时，请稍后重试。"
    if "config" in message or isinstance(exc, (KeyError, ValueError, FileNotFoundError)):
        return "系统配置不完整，请检查配置文件。"
    return "安全检测暂时不可用，本次内容未发送至大模型。"


def render_security_seal(result: dict[str, Any]) -> None:
    input_action = result.get("action", "block")
    output_action = result.get("output_action", "not_run")
    css_action = result.get("final_action", "block")
    st.markdown(
        f'<div class="sg-seal {escape(css_action)}"><div class="sg-seal-row">'
        f'<span><b>输入检测</b> {escape(ACTION_LABELS.get(input_action, input_action))}</span>'
        f'<span><b>输出检测</b> {escape(ACTION_LABELS.get(output_action, output_action))}</span>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    with st.expander("查看安全详情", expanded=False):
        detail = {
            "风险类别": CATEGORY_LABELS.get(result.get("category"), result.get("category", "unavailable")),
            "风险等级": RISK_LABELS.get(result.get("risk"), result.get("risk", "unavailable")),
            "风险评分": result.get("risk_score", "unavailable"),
            "输入动作": ACTION_LABELS.get(input_action, input_action),
            "输出动作": ACTION_LABELS.get(output_action, output_action),
            "最终动作": ACTION_LABELS.get(result.get("final_action"), result.get("final_action", "unavailable")),
            "检测来源": sorted({str(hit.get("type")) for hit in result.get("hits", []) if hit.get("type")}) or ["未命中规则/语义风险"],
            "是否发送模型": bool(result.get("model_forwarded")),
            "Request ID": result.get("request_id", "unavailable"),
        }
        if input_action == "sanitize":
            detail["实际发送内容"] = result.get("processed_text", "unavailable")
        st.json(detail)


def render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("result"):
            render_security_seal(message["result"])


def render_chat() -> None:
    config = load_config()
    registry_snapshot = get_model_registry().snapshot()
    providers = {
        item["provider"]: item
        for item in registry_snapshot["providers"]
        if item["enabled"]
    }
    default_provider = str(registry_snapshot.get("default_provider") or "mock")
    init_chat_state(default_provider)

    provider_ids = [item for item in ("mock", "qwen", "deepseek") if item in providers]
    if st.session_state.selected_provider not in provider_ids:
        st.session_state.selected_provider = default_provider
    selected = st.sidebar.selectbox(
        "当前模型",
        provider_ids,
        index=provider_ids.index(st.session_state.selected_provider) if st.session_state.selected_provider in provider_ids else 0,
        format_func=lambda item: PROVIDER_LABELS.get(item, item),
    )
    st.session_state.selected_provider = selected
    adapter = get_chat_adapter(selected)
    llm_status = adapter.pipeline.llm.status()
    st.sidebar.caption(f"Provider：{selected}")
    st.sidebar.caption(f"Model：{llm_status.get('model') or 'unavailable'}")
    st.sidebar.caption("配置状态：" + ("已配置" if llm_status.get("ready") else "未配置"))
    if st.sidebar.button("清空当前对话", use_container_width=True):
        st.session_state.chat_messages = []
        st.rerun()

    semantic_ready = bool(adapter.pipeline.semantic_classifier.status().get("loaded"))
    runtime_ready = bool(adapter.pipeline.action_router is not None and (semantic_ready or not adapter.pipeline.semantic_required))
    st.markdown(
        f'<div class="sg-header"><div class="sg-kicker">SECURE CONVERSATION GATEWAY · {PRODUCT_VERSION}</div>'
        '<div class="sg-title">SafeChat-Guard</div><div class="sg-subtitle">大模型对话内容安全防护系统</div>'
        f'<div class="sg-runtime"><span class="sg-chip">{escape(PROVIDER_LABELS.get(selected, selected))} / {escape(str(llm_status.get("model") or "unavailable"))}</span>'
        f'<span class="sg-chip {"ready" if runtime_ready else ""}">安全链路：{"正常" if runtime_ready else "不可用"}</span></div></div>',
        unsafe_allow_html=True,
    )

    if not st.session_state.chat_messages:
        st.markdown('<div class="sg-empty"><b>在安全防护下开始对话</b>系统会自动识别风险，并在模型回答后再次复检。</div>', unsafe_allow_html=True)
    for message in st.session_state.chat_messages:
        render_message(message)

    prompt = st.chat_input("请输入消息……", disabled=st.session_state.request_in_progress)
    if not prompt:
        return
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.request_in_progress = True
    try:
        with st.chat_message("assistant"):
            with st.spinner("正在执行输入检测与输出复检…"):
                if selected != "mock" and not llm_status.get("ready"):
                    answer = "当前模型尚未配置，请切换模型或完成 API 配置。"
                    result = None
                else:
                    result = adapter.analyze(prompt, persist=True)
                    answer = result["final_answer"]
                st.markdown(answer)
                if result:
                    render_security_seal(result)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer, "result": result})
    except Exception as exc:
        answer = friendly_error(exc)
        st.error(answer)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer, "result": None})
    finally:
        st.session_state.request_in_progress = False


def main() -> None:
    configure_product_page()
    render_chat()
