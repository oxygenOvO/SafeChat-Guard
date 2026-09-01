"""Phase-two operations console views backed by SafeChat services."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from safechat_guard.analytics_service import AnalyticsService
from safechat_guard.audit_service import AuditService
from safechat_guard.health_service import HealthService
from safechat_guard.model_registry import ModelRegistry, ModelRegistryError
from safechat_guard.pipeline import SafeChatPipeline


ACTION_LABELS = {"pass": "PASS", "sanitize": "SANITIZE", "block": "BLOCK", "not_run": "未执行"}
HEALTH_LABELS = {
    "normal": "正常",
    "degraded": "降级",
    "abnormal": "异常",
    "unloaded": "未加载",
    "available": "可用",
    "unavailable": "不可用",
    "not_configured": "未配置",
    "unknown": "未检测",
    "failed": "连接失败",
    "timeout": "超时",
}
CONNECTION_MESSAGES = {
    "available": "连接可用",
    "not_configured": "尚未配置 API Key",
    "authentication_failed": "认证失败，请检查 API Key 配置",
    "permission_denied": "当前凭据无权访问该模型或服务",
    "not_found": "模型或接口地址不可用",
    "rate_limited": "请求受限，请稍后重试或检查账户额度",
    "timeout": "连接超时，请检查网络或稍后重试",
    "network_error": "网络连接失败",
    "ssl_error": "安全连接建立失败",
    "bad_request": "请求配置不正确",
    "connection_failed": "连接失败",
    "unknown_error": "连接失败",
}
HEALTH_LABELS.update(
    {
        "authentication_failed": "认证失败",
        "permission_denied": "权限不足",
        "not_found": "模型或接口不存在",
        "rate_limited": "请求受限",
        "network_error": "网络错误",
        "ssl_error": "安全连接失败",
        "bad_request": "请求配置错误",
        "connection_failed": "连接失败",
        "unknown_error": "连接失败",
    }
)



def page_intro(kicker: str, title: str, description: str, status: str | None = None) -> None:
    status_html = (
        f'<span class="sg-ops-status"><i></i>{escape(status)}</span>' if status else ""
    )
    st.markdown(
        f'<div class="sg-ops-head"><div><div class="sg-kicker">{escape(kicker)}</div>'
        f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>{status_html}</div>',
        unsafe_allow_html=True,
    )


def render_dashboard(audit: AuditService, health: HealthService, registry: ModelRegistry) -> None:
    records = audit.records()
    stats = AnalyticsService.summarize(records)
    health_snapshot = health.snapshot()
    registry_snapshot = registry.snapshot()
    page_intro(
        "OPERATIONS / OVERVIEW",
        "系统总览",
        "从脱敏审计摘要聚合当前运行状态，不维护第二份统计数据。",
        HEALTH_LABELS.get(health_snapshot["status"], health_snapshot["status"]),
    )
    default_provider = registry_snapshot.get("default_provider") or "暂无"
    columns = st.columns(6)
    metrics = (
        ("系统状态", HEALTH_LABELS.get(health_snapshot["status"], health_snapshot["status"])),
        ("默认模型", default_provider),
        ("累计请求", stats["total_requests"]),
        ("PASS", stats["pass_count"]),
        ("SANITIZE", stats["sanitize_count"]),
        ("BLOCK", stats["block_count"]),
    )
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)

    st.markdown('<div class="sg-section-label">最近风险事件</div>', unsafe_allow_html=True)
    recent = [row for row in records if row["final_action"] != "pass"][:8]
    if recent:
        st.dataframe(_display_frame(recent), use_container_width=True, hide_index=True)
    else:
        st.info("暂无安全事件。完成一次安全对话后，这里将显示审计记录。")

    if records:
        action_rows = [
            {"Action": key.upper(), "请求数": value}
            for key, value in stats["action_distribution"].items()
        ]
        category_rows = [
            {"风险类别": key, "事件数": value}
            for key, value in stats["category_distribution"].items()
        ]
        left, right = st.columns(2)
        if action_rows:
            left.markdown("#### Action 分布")
            left.bar_chart(pd.DataFrame(action_rows).set_index("Action"))
        if category_rows:
            right.markdown("#### 风险类别分布")
            right.bar_chart(pd.DataFrame(category_rows).set_index("风险类别"))


def render_model_management(registry: ModelRegistry) -> None:
    snapshot = registry.snapshot()
    page_intro(
        "OPERATIONS / MODELS",
        "模型管理",
        "管理启用状态和默认模型；密钥仅从环境变量检测，页面不读取或保存明文。",
    )
    rows = [
        {
            "模型": item["display_name"],
            "Provider": item["provider"],
            "Model ID": item["model"],
            "模式": item["mode"],
            "Key": "已配置" if item["key_configured"] else "未配置",
            "启用": item["enabled"],
            "默认": item["default"],
            "Health": HEALTH_LABELS.get(item["health"], item["health"]),
        }
        for item in snapshot["providers"]
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    provider_ids = [item["provider"] for item in snapshot["providers"]]
    selected = st.selectbox("选择 Provider", provider_ids, key="model_management_provider")
    record = next(item for item in snapshot["providers"] if item["provider"] == selected)
    enabled = st.checkbox("启用该 Provider", value=record["enabled"], key=f"enabled_{selected}")
    save_col, default_col, test_col = st.columns(3)
    if save_col.button("保存启用状态", use_container_width=True):
        try:
            registry.set_enabled(selected, enabled)
        except ModelRegistryError:
            st.error("模型状态未能保存，请检查运行时配置目录。")
        else:
            st.success("模型启用状态已保存。")
            st.rerun()
    if default_col.button(
        "设为默认模型",
        use_container_width=True,
        disabled=not record["enabled"] or record["default"],
    ):
        try:
            registry.set_default(selected)
        except ModelRegistryError as exc:
            st.error(str(exc))
        else:
            st.session_state["selected_provider"] = selected
            st.success("默认模型已更新，安全对话将在下次加载时同步。")
            st.rerun()
    if test_col.button("测试连接", use_container_width=True):
        try:
            result = registry.test_connection(selected)
        except ModelRegistryError:
            st.error("该 Provider 当前不可测试。")
        else:
            message = CONNECTION_MESSAGES.get(result["status"], "连接失败")
            latency = result.get("latency_ms")
            suffix = f"，实测 {latency} ms" if latency is not None else ""
            st.session_state["last_connection_result"] = f"{message}{suffix}"
    if st.session_state.get("last_connection_result"):
        st.info(f"最近连接测试：{st.session_state['last_connection_result']}")


def render_audit_logs(audit: AuditService) -> None:
    all_records = audit.records()
    page_intro(
        "OPERATIONS / AUDIT",
        "安全日志",
        "仅展示请求级脱敏摘要；用户输入、模型输出、密钥和异常堆栈均不进入此视图。",
    )
    range_name = st.selectbox("时间范围", ["全部", "今天", "最近 7 天", "最近 30 天"])
    actions = st.multiselect("Action", ["pass", "sanitize", "block"])
    categories = sorted({item["category"] for item in all_records})
    providers = sorted({item["provider"] for item in all_records})
    selected_categories = st.multiselect("风险类别", categories)
    selected_providers = st.multiselect("Provider", providers)
    start_date, end_date = _date_range(range_name)
    records = audit.records(
        start_date=start_date,
        end_date=end_date,
        actions=actions,
        categories=selected_categories,
        providers=selected_providers,
    )
    if records:
        st.dataframe(_display_frame(records), use_container_width=True, hide_index=True)
    else:
        st.info("当前筛选条件下暂无安全日志。")
    st.download_button(
        "导出当前筛选结果 CSV",
        data=audit.to_csv(records),
        file_name="safechat_audit_filtered.csv",
        mime="text/csv",
        use_container_width=True,
    )


def render_risk_analytics(audit: AuditService) -> None:
    records = audit.records()
    stats = AnalyticsService.summarize(records)
    page_intro(
        "OPERATIONS / ANALYTICS",
        "风险统计",
        "面向日常运维的请求分布与风险趋势，不展示模型能力评测指标。",
    )
    columns = st.columns(6)
    metrics = (
        ("总检测数", stats["total_requests"]),
        ("PASS", stats["pass_count"]),
        ("SANITIZE", stats["sanitize_count"]),
        ("BLOCK", stats["block_count"]),
        ("输入侧高风险", stats["input_high_risk_count"]),
        ("输出侧风险", stats["output_risk_event_count"]),
    )
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)
    if not records:
        st.info("当前暂无可统计数据。")
        return
    left, right = st.columns(2)
    action_rows = [
        {"Action": key.upper(), "请求数": value}
        for key, value in stats["action_distribution"].items()
    ]
    category_rows = [
        {"风险类别": key, "事件数": value}
        for key, value in stats["category_distribution"].items()
    ]
    left.markdown("#### Action 分布")
    left.bar_chart(pd.DataFrame(action_rows).set_index("Action"))
    if category_rows:
        right.markdown("#### 风险类别分布")
        right.bar_chart(pd.DataFrame(category_rows).set_index("风险类别"))
    else:
        right.info("当前没有风险类别事件。")
    trend_rows = [
        {"日期": day, "请求数": count}
        for day, count in stats["daily_request_counts"].items()
    ]
    if trend_rows:
        st.markdown("#### 请求时间趋势")
        st.line_chart(pd.DataFrame(trend_rows).set_index("日期"))
    if stats["invalid_time_count"]:
        st.caption(f"有 {stats['invalid_time_count']} 条旧日志时间字段无效，未计入时间趋势。")


def render_system_health(health: HealthService) -> None:
    snapshot = health.snapshot()
    page_intro(
        "OPERATIONS / HEALTH",
        "系统状态",
        "组件状态来自当前进程检查；Provider 未实测时保持“未检测”，不会冒充在线。",
        HEALTH_LABELS.get(snapshot["status"], snapshot["status"]),
    )
    if not snapshot["model_calls_allowed"]:
        st.error("安全检测模块当前不可用，为避免绕过安全防护，模型调用已暂停。")
    component_rows = [
        {
            "组件": item["name"],
            "状态": HEALTH_LABELS.get(item["status"], item["status"]),
            "说明": item.get("detail") or "—",
        }
        for item in snapshot["components"]
    ]
    st.markdown('<div class="sg-section-label">安全链路</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(component_rows), use_container_width=True, hide_index=True)
    provider_rows = [
        {
            "Provider": item["display_name"],
            "Model": item["model"],
            "配置": "已配置" if item["key_configured"] or item["provider"] == "mock" else "未配置",
            "状态": HEALTH_LABELS.get(item["health"], item["health"]),
        }
        for item in snapshot["providers"]
    ]
    st.markdown('<div class="sg-section-label">Provider Health</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)
    st.caption(f"检查时间：{snapshot['checked_at']}")


def render_settings(registry: ModelRegistry, pipeline: SafeChatPipeline) -> None:
    snapshot = registry.snapshot()
    page_intro(
        "OPERATIONS / SETTINGS",
        "系统设置与关于",
        "展示运行策略和配置来源；核心安全阈值不开放网页修改。",
    )
    st.markdown("#### 运行设置")
    settings = {
        "默认 Provider": snapshot.get("default_provider") or "暂无",
        "日志状态": "启用",
        "日志隐私": "请求摘要 + 敏感字段递归脱敏",
        "OutputGuard": "启用" if pipeline.output_guard is not None else "不可用",
        "模型运行时配置": "本地 gitignored overlay",
    }
    st.json(settings)
    st.markdown("#### SafeChat-Guard V1.0")
    st.write(
        "大模型对话内容安全防护系统，提供输入检测、输出复检、风险分级处置、"
        "统一多模型接入、模型管理、安全审计、风险统计和运行状态监测。"
    )
    st.info("管理员登录暂缓至具备可靠身份边界的后续版本；本阶段管理日志仅暴露脱敏摘要。")


def _display_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "时间": item["time"],
                "Request ID": item["request_id"],
                "Provider": item["provider"],
                "风险类别": item["category"],
                "风险等级": item["risk_level"],
                "Score": item["risk_score"],
                "Input": ACTION_LABELS.get(item["input_action"], item["input_action"]),
                "Output": ACTION_LABELS.get(item["output_action"], item["output_action"]),
                "Final": ACTION_LABELS.get(item["final_action"], item["final_action"]),
            }
            for item in records
        ]
    )


def _date_range(name: str) -> tuple[date | None, date | None]:
    today = date.today()
    if name == "今天":
        return today, today
    if name == "最近 7 天":
        return today - timedelta(days=6), today
    if name == "最近 30 天":
        return today - timedelta(days=29), today
    return None, None
