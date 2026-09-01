"""SafeChat-Guard V1.0 phase-two product shell."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend.chat_app import (
    PROJECT_ROOT,
    configure_product_page,
    get_model_registry,
    load_config,
    render_chat,
)
from frontend.ui_components import icon
from safechat_guard.audit_service import AuditService
from safechat_guard.health_service import HealthService
from safechat_guard.llm_adapters import LLMAdapterFactory
from safechat_guard.pipeline import SafeChatPipeline


NAVIGATION = (
    "安全对话",
    "系统总览",
    "模型管理",
    "安全日志",
    "风险统计",
    "系统状态",
    "系统设置",
)
NAV_ICONS = {
    "安全对话": ":material/forum:",
    "系统总览": ":material/dashboard:",
    "模型管理": ":material/memory:",
    "安全日志": ":material/receipt_long:",
    "风险统计": ":material/monitoring:",
    "系统状态": ":material/health_and_safety:",
    "系统设置": ":material/settings:",
}



@st.cache_resource(show_spinner=False)
def get_operations_pipeline(default_provider: str) -> SafeChatPipeline:
    config = load_config()
    pipeline = SafeChatPipeline(config, project_root=PROJECT_ROOT)
    provider_config = get_model_registry().provider_config(default_provider)
    pipeline.llm = LLMAdapterFactory.create(provider_config)
    return pipeline


def _status_tone(status: str) -> str:
    if status == "normal":
        return "success"
    if status in {"degraded", "unknown", "unloaded"}:
        return "warning"
    return "danger"


def _render_sidebar() -> str:
    st.sidebar.markdown(
        f'<div class="sg-brand"><div class="sg-brand-mark">{icon("shield", 22)}</div>'
        '<div><div class="sg-brand-name">SafeChat-Guard</div>'
        '<div class="sg-brand-meta">V1.0 · SECURITY OPS</div></div></div>'
        '<div class="sg-nav-label">工作区导航</div>',
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("active_page", "安全对话")
    for label in NAVIGATION:
        if st.sidebar.button(
            label,
            key=f"nav_{label}",
            icon=NAV_ICONS[label],
            type="primary" if st.session_state.active_page == label else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_page = label
            st.rerun()

    return str(st.session_state.active_page)


def _render_sidebar_status(snapshot: dict, health_snapshot: dict) -> None:
    default_provider = str(snapshot.get("default_provider") or "暂无")
    provider = next(
        (item for item in snapshot.get("providers", []) if item.get("provider") == default_provider),
        {},
    )
    config_ready = default_provider == "mock" or bool(provider.get("key_configured"))
    system_status = str(health_snapshot.get("status") or "unknown")
    system_label = {
        "normal": "链路正常",
        "degraded": "链路降级",
        "abnormal": "链路异常",
    }.get(system_status, "未检测")
    tone = _status_tone(system_status)
    st.sidebar.markdown(
        '<div class="sg-sidebar-status" data-ui="sidebar-status"><h4>运行摘要</h4>'
        f'<div class="sg-status-line"><span>系统状态</span><b><i class="sg-dot {tone}"></i>{escape(system_label)}</b></div>'
        f'<div class="sg-status-line"><span>当前模型</span><b title="{escape(default_provider)}">{escape(default_provider)}</b></div>'
        f'<div class="sg-status-line"><span>配置状态</span><b>{"已配置" if config_ready else "未配置"}</b></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    configure_product_page()
    registry = get_model_registry()
    snapshot = registry.snapshot()
    default_provider = str(snapshot.get("default_provider") or "mock")
    pipeline = get_operations_pipeline(default_provider)
    audit = AuditService(pipeline.logger)
    health = HealthService(pipeline, registry)

    health_snapshot = health.snapshot()
    page = _render_sidebar()

    try:
        if page == "安全对话":
            if not health.snapshot()["model_calls_allowed"]:
                st.error("安全检测模块当前不可用，为避免绕过安全防护，模型调用已暂停。")
            else:
                st.markdown(
                    "<style>.main .block-container{max-width:850px}</style>",
                    unsafe_allow_html=True,
                )
                render_chat()
        else:
            from frontend import management_views

            if page == "系统总览":
                management_views.render_dashboard(audit, health, registry)
            elif page == "模型管理":
                management_views.render_model_management(registry)
            elif page == "安全日志":
                management_views.render_audit_logs(audit)
            elif page == "风险统计":
                management_views.render_risk_analytics(audit)
            elif page == "系统状态":
                management_views.render_system_health(health)
            else:
                management_views.render_settings(registry, pipeline)
    except Exception:
        st.error("当前管理数据无法读取，请检查运行配置和审计日志。")

    _render_sidebar_status(snapshot, health_snapshot)


if __name__ == "__main__":
    main()
