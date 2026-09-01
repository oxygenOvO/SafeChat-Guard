"""SafeChat-Guard V1.0 phase-two product shell."""

from __future__ import annotations

import streamlit as st

from frontend.chat_app import (
    PROJECT_ROOT,
    configure_product_page,
    get_model_registry,
    load_config,
    render_chat,
)
from frontend.management_console import (
    render_audit_logs,
    render_dashboard,
    render_model_management,
    render_risk_analytics,
    render_settings,
    render_system_health,
)
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


@st.cache_resource(show_spinner=False)
def get_operations_pipeline(default_provider: str) -> SafeChatPipeline:
    config = load_config()
    pipeline = SafeChatPipeline(config, project_root=PROJECT_ROOT)
    provider_config = get_model_registry().provider_config(default_provider)
    pipeline.llm = LLMAdapterFactory.create(provider_config)
    return pipeline


def apply_phase2_styles() -> None:
    st.markdown(
        """
        <style>
        .main .block-container { max-width:1180px; }
        .sg-ops-head { display:flex; align-items:flex-start; justify-content:space-between; gap:2rem;
                       border-bottom:1px solid var(--line); padding:.25rem 0 1.15rem; margin-bottom:1.25rem; }
        .sg-ops-head h1 { color:var(--navy); font-size:1.8rem; letter-spacing:-.035em;
                          margin:.28rem 0 .28rem; font-weight:760; }
        .sg-ops-head p { color:var(--muted); max-width:690px; margin:0; font-size:.92rem; }
        .sg-ops-status { display:flex; align-items:center; gap:.48rem; border:1px solid var(--line);
                         border-radius:999px; background:#fff; color:#43536a; padding:.38rem .72rem;
                         font:650 .76rem/1.2 ui-monospace,Consolas,monospace; white-space:nowrap; }
        .sg-ops-status i { display:block; width:.52rem; height:.52rem; border-radius:50%;
                           background:var(--safe); box-shadow:0 0 0 4px rgba(32,122,85,.11); }
        .sg-section-label { margin:1.45rem 0 .65rem; color:var(--navy); font-size:.82rem;
                            font-weight:750; letter-spacing:.04em; border-left:3px solid var(--blue);
                            padding-left:.62rem; }
        [data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:10px;
                                   padding:.75rem .85rem; min-height:92px; }
        [data-testid="stMetricLabel"] { color:var(--muted); }
        [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
        [data-testid="stSidebar"] [role="radiogroup"] { gap:.16rem; }
        [data-testid="stSidebar"] [role="radiogroup"] label { border-radius:8px; padding:.24rem .4rem; }
        @media (max-width:760px) {
          .sg-ops-head { display:block; }
          .sg-ops-status { display:inline-flex; margin-top:.85rem; }
          [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    configure_product_page()
    apply_phase2_styles()
    registry = get_model_registry()
    snapshot = registry.snapshot()
    default_provider = str(snapshot.get("default_provider") or "mock")
    pipeline = get_operations_pipeline(default_provider)
    audit = AuditService(pipeline.logger)
    health = HealthService(pipeline, registry)

    st.sidebar.markdown("### SafeChat-Guard")
    st.sidebar.caption("V1.0 · Security Operations")
    page = st.sidebar.radio("功能导航", NAVIGATION, index=0)
    st.sidebar.markdown("---")

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
        elif page == "系统总览":
            render_dashboard(audit, health, registry)
        elif page == "模型管理":
            render_model_management(registry)
        elif page == "安全日志":
            render_audit_logs(audit)
        elif page == "风险统计":
            render_risk_analytics(audit)
        elif page == "系统状态":
            render_system_health(health)
        else:
            render_settings(registry, pipeline)
    except Exception:
        st.error("当前管理数据无法读取，请检查运行配置和审计日志。")


if __name__ == "__main__":
    main()
