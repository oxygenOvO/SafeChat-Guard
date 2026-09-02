"""Product-grade management views backed exclusively by existing SafeChat services."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from frontend.ui_components import (
    about_card,
    audit_event_table,
    health_list,
    icon,
    info_card,
    kpi_card,
    page_intro,
    section_header,
    setting_rows,
)
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
    "response_error": "模型已响应，但未返回可用的最终内容",
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
        "response_error": "响应内容不可用",
        "connection_failed": "连接失败",
        "unknown_error": "连接失败",
    }
)

ACTION_COLORS = {"PASS": "#2f7d5b", "SANITIZE": "#b7791f", "BLOCK": "#b94a55"}
CATEGORY_COLORS = ["#526f9e", "#657faf", "#6d5bd0", "#8a76c8", "#8594aa", "#a06d7a"]


def _health_tone(status: str) -> str:
    if status in {"normal", "available"}:
        return "normal"
    if status in {"degraded", "timeout", "rate_limited"}:
        return "degraded"
    if status in {
        "abnormal",
        "failed",
        "unavailable",
        "not_configured",
        "authentication_failed",
        "permission_denied",
        "not_found",
        "network_error",
        "ssl_error",
        "bad_request",
        "connection_failed",
        "response_error",
        "unknown_error",
    }:
        return "abnormal"
    return "unknown"


def _health_header(snapshot: dict[str, Any]) -> tuple[str, str]:
    status = str(snapshot.get("status") or "unknown")
    label = {
        "normal": "安全链路正常",
        "degraded": "安全链路降级",
        "abnormal": "安全链路异常",
    }.get(status, "安全链路未检测")
    tone = {"normal": "success", "degraded": "warning", "abnormal": "danger"}.get(status, "warning")
    return label, tone


def _render_kpis(items: tuple[tuple[str, Any, str, str, str], ...]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, icon_name, tone, note) in zip(columns, items):
        with column:
            kpi_card(label, value, icon_name, tone, note)


def _base_chart(chart: alt.Chart) -> alt.Chart:
    return chart.properties(height=235).configure_view(strokeWidth=0).configure_axis(
        labelColor="#66768b",
        titleColor="#66768b",
        gridColor="#e8edf4",
        domainColor="#d9e2ef",
        tickColor="#d9e2ef",
        labelFont="Segoe UI",
        titleFont="Segoe UI",
    )


def _action_chart(rows: list[dict[str, Any]]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=38)
        .encode(
            x=alt.X("Action:N", sort=["PASS", "SANITIZE", "BLOCK"], title=None),
            y=alt.Y("请求数:Q", title="请求数"),
            color=alt.Color(
                "Action:N",
                scale=alt.Scale(domain=list(ACTION_COLORS), range=list(ACTION_COLORS.values())),
                legend=None,
            ),
            tooltip=["Action:N", "请求数:Q"],
        )
    )
    return _base_chart(chart)


def _category_chart(rows: list[dict[str, Any]]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    categories = frame["风险类别"].tolist()
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y("风险类别:N", sort="-x", title=None),
            x=alt.X("事件数:Q", title="事件数"),
            color=alt.Color(
                "风险类别:N",
                scale=alt.Scale(domain=categories, range=CATEGORY_COLORS[: len(categories)]),
                legend=None,
            ),
            tooltip=["风险类别:N", "事件数:Q"],
        )
    )
    return _base_chart(chart)


def _trend_chart(rows: list[dict[str, Any]]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    chart = (
        alt.Chart(frame)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=55), color="#2563d9", strokeWidth=2.3)
        .encode(
            x=alt.X("日期:T", title=None, axis=alt.Axis(format="%m-%d")),
            y=alt.Y("请求数:Q", title="请求数"),
            tooltip=[alt.Tooltip("日期:T", format="%Y-%m-%d"), "请求数:Q"],
        )
    )
    return _base_chart(chart)


def _chart_panel(title: str, chart: alt.Chart) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="sg-chart-title">{escape(title)}</div>', unsafe_allow_html=True)
        st.altair_chart(chart, use_container_width=True)


def render_dashboard(audit: AuditService, health: HealthService, registry: ModelRegistry) -> None:
    records = audit.records()
    stats = AnalyticsService.summarize(records)
    health_snapshot = health.snapshot()
    registry_snapshot = registry.snapshot()
    page_intro(
        "OPERATIONS / OVERVIEW",
        "系统总览",
        "基于脱敏审计摘要呈现当前安全链路、请求处置与风险事件。",
        status=_health_header(health_snapshot),
    )
    default_provider = registry_snapshot.get("default_provider") or "暂无"
    _render_kpis(
        (
            ("系统状态", HEALTH_LABELS.get(health_snapshot["status"], health_snapshot["status"]), "pulse", "success" if health_snapshot["status"] == "normal" else "warning", "实时组件快照"),
            ("默认模型", default_provider, "model", "purple", "当前 Provider"),
            ("累计请求", stats["total_requests"], "requests", "blue", "脱敏审计计数"),
            ("PASS", stats["pass_count"], "check", "success", "直接通过"),
            ("SANITIZE", stats["sanitize_count"], "filter", "warning", "安全处理"),
            ("BLOCK", stats["block_count"], "block", "danger", "已阻断"),
        )
    )

    section_header("最近风险事件", "仅展示非 PASS 的脱敏请求摘要")
    recent = [row for row in records if row["final_action"] != "pass"][:8]
    if recent:
        audit_event_table(recent, ACTION_LABELS)
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
        section_header("处置分布", "语义颜色与审计动作保持一致")
        left, right = st.columns(2)
        with left:
            _chart_panel("Action 分布", _action_chart(action_rows))
        with right:
            if category_rows:
                _chart_panel("风险类别分布", _category_chart(category_rows))
            else:
                with st.container(border=True):
                    st.info("当前没有风险类别事件。")


def _provider_card(item: dict[str, Any]) -> None:
    health = str(item.get("health") or "unknown")
    enabled = bool(item.get("enabled"))
    configured = bool(item.get("key_configured")) or item.get("provider") == "mock"
    st.markdown(
        '<div class="sg-provider-card" data-ui="provider-card">'
        f'<div class="sg-provider-head"><span class="sg-provider-name">{escape(str(item["display_name"]))}</span>'
        f'<span class="sg-badge {_health_tone(health)}">{escape(HEALTH_LABELS.get(health, health))}</span></div>'
        f'<div class="sg-provider-id">{escape(str(item["provider"]))} · {escape(str(item["platform"]))}</div>'
        '<div class="sg-provider-meta">'
        f'<span>模型<br><b>{escape(str(item["model"]))}</b></span>'
        f'<span>模式<br><b>{escape(str(item["mode"]).replace("remote_api", "Remote API"))}</b></span>'
        f'<span>协议<br><b>{escape(str(item["protocol"]).replace("openai_compatible", "OpenAI Compatible"))}</b></span>'
        f'<span>密钥<br><b>{"已配置" if configured else "未配置"}</b></span>'
        f'<span>启用<br><b>{"是" if enabled else "否"}</b></span>'
        f'<span>角色<br><b>{"默认" if item.get("default") else "备选"}</b></span>'
        '</div></div>',
        unsafe_allow_html=True,
    )


def render_model_management(registry: ModelRegistry) -> None:
    snapshot = registry.snapshot()
    page_intro(
        "OPERATIONS / MODELS",
        "模型管理",
        "统一管理 Provider 启用状态与默认模型；密钥仅检测环境变量，不读取明文。",
        pills=((f"默认模型 · {snapshot.get('default_provider') or '暂无'}", "purple"),),
    )
    section_header("Provider 概览", "配置、角色与健康状态一屏可见")
    providers = snapshot["providers"]
    columns = st.columns(len(providers))
    for column, item in zip(columns, providers):
        with column:
            _provider_card(item)

    section_header("模型操作", "所有变更继续写入既有运行时配置")
    with st.container(border=True):
        provider_ids = [item["provider"] for item in providers]
        selected = st.selectbox("选择 Provider", provider_ids, key="model_management_provider")
        record = next(item for item in providers if item["provider"] == selected)
        enabled = st.checkbox("启用该 Provider", value=record["enabled"], key=f"enabled_{selected}")
        save_col, default_col, test_col = st.columns(3)
        if save_col.button("保存启用状态", icon=":material/save:", use_container_width=True):
            try:
                registry.set_enabled(selected, enabled)
            except ModelRegistryError:
                st.error("模型状态未能保存，请检查运行时配置目录。")
            else:
                st.success("模型启用状态已保存。")
                st.rerun()
        if default_col.button(
            "设为默认模型",
            icon=":material/star:",
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
        if test_col.button("测试连接", icon=":material/network_check:", use_container_width=True):
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


def render_audit_logs(
    audit: AuditService, pipeline: SafeChatPipeline | None = None
) -> None:
    all_records = audit.records()
    page_intro(
        "OPERATIONS / AUDIT",
        "安全日志",
        "请求级脱敏摘要；原始输入、模型输出、密钥与异常堆栈均不进入此视图。",
        pills=((f"{len(all_records)} 条记录", "blue"),),
    )
    section_header("筛选条件", "组合筛选后导出当前结果")
    with st.container(border=True):
        first, second = st.columns(2)
        with first:
            range_name = st.selectbox("时间范围", ["全部", "今天", "最近 7 天", "最近 30 天"])
        with second:
            actions = st.multiselect("Action", ["pass", "sanitize", "block"])
        categories = sorted({item["category"] for item in all_records})
        providers = sorted({item["provider"] for item in all_records})
        third, fourth = st.columns(2)
        with third:
            selected_categories = st.multiselect("风险类别", categories)
        with fourth:
            selected_providers = st.multiselect("Provider", providers)
    start_date, end_date = _date_range(range_name)
    records = audit.records(
        start_date=start_date,
        end_date=end_date,
        actions=actions,
        categories=selected_categories,
        providers=selected_providers,
    )
    title_col, export_col = st.columns([4, 1])
    with title_col:
        section_header("审计记录", f"当前筛选共 {len(records)} 条")
    with export_col:
        st.download_button(
            "导出 CSV",
            data=audit.to_csv(records),
            file_name="safechat_audit_filtered.csv",
            mime="text/csv",
            icon=":material/download:",
            use_container_width=True,
        )
    if records:
        st.dataframe(
            _display_frame(records),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Request ID": st.column_config.TextColumn(width="medium"),
                "Score": st.column_config.NumberColumn(format="%.3f"),
            },
        )
        section_header(
            "安全决策解释",
            "历史记录仅使用脱敏审计摘要，不恢复原始输入或模型输出",
        )
        request_ids = [str(item["request_id"]) for item in records]
        selected_request = st.selectbox(
            "选择 Request ID", request_ids, key="audit_explanation_request"
        )
        selected_record = next(
            item for item in records
            if str(item["request_id"]) == selected_request
        )
        from frontend.security_platform_views import render_historical_explanation

        render_historical_explanation(selected_record)
    else:
        st.info("当前筛选条件下暂无安全日志。")


def render_risk_analytics(audit: AuditService) -> None:
    records = audit.records()
    stats = AnalyticsService.summarize(records)
    page_intro(
        "OPERATIONS / ANALYTICS",
        "风险统计",
        "聚合请求分布与时间趋势，所有指标均来自当前脱敏审计记录。",
        pills=(("实时审计聚合", "blue"),),
    )
    _render_kpis(
        (
            ("总检测数", stats["total_requests"], "requests", "blue", "全部请求"),
            ("PASS", stats["pass_count"], "check", "success", "直接通过"),
            ("SANITIZE", stats["sanitize_count"], "filter", "warning", "安全处理"),
            ("BLOCK", stats["block_count"], "block", "danger", "已阻断"),
            ("输入侧高风险", stats["input_high_risk_count"], "shield", "danger", "输入检测"),
            ("输出侧风险", stats["output_risk_event_count"], "eye", "warning", "OutputGuard"),
        )
    )
    if not records:
        st.info("当前暂无可统计数据。")
        return
    action_rows = [
        {"Action": key.upper(), "请求数": value}
        for key, value in stats["action_distribution"].items()
    ]
    category_rows = [
        {"风险类别": key, "事件数": value}
        for key, value in stats["category_distribution"].items()
    ]
    section_header("风险分布", "处置动作与风险类别")
    left, right = st.columns(2)
    with left:
        _chart_panel("Action 分布", _action_chart(action_rows))
    with right:
        if category_rows:
            _chart_panel("风险类别分布", _category_chart(category_rows))
        else:
            with st.container(border=True):
                st.info("当前没有风险类别事件。")
    trend_rows = [
        {"日期": day, "请求数": count}
        for day, count in stats["daily_request_counts"].items()
    ]
    if trend_rows:
        section_header("请求时间趋势", "按审计日期聚合")
        _chart_panel("每日请求数", _trend_chart(trend_rows))
    if stats["invalid_time_count"]:
        st.caption(f"有 {stats['invalid_time_count']} 条旧日志时间字段无效，未计入时间趋势。")


def render_system_health(health: HealthService) -> None:
    snapshot = health.snapshot()
    page_intro(
        "OPERATIONS / HEALTH",
        "系统状态",
        "组件状态来自当前进程检查；Provider 未实测时保留“未检测”。",
        status=_health_header(snapshot),
        pills=((f"检查于 {snapshot['checked_at']}", "blue"),),
    )
    if not snapshot["model_calls_allowed"]:
        st.error("安全检测模块当前不可用，为避免绕过安全防护，模型调用已暂停。")
    section_header("安全链路", "检测、路由、输出复检与审计组件")
    health_list(
        (
            (
                str(item["name"]),
                HEALTH_LABELS.get(item["status"], item["status"]),
                _health_tone(str(item["status"])),
                str(item.get("detail") or "—"),
            )
            for item in snapshot["components"]
        )
    )
    section_header("Provider Health", "未执行连接测试时不会标记为在线")
    health_list(
        (
            (
                f"{item['display_name']} · {item['model']}",
                HEALTH_LABELS.get(item["health"], item["health"]),
                _health_tone(str(item["health"])),
                "配置已就绪" if item["key_configured"] or item["provider"] == "mock" else "等待 API 配置",
            )
            for item in snapshot["providers"]
        )
    )


def _safe_config_view(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if lowered in {"api_key", "secret", "token", "password"} or lowered.endswith("_secret"):
        return "***REDACTED***"
    if isinstance(value, dict):
        return {str(item_key): _safe_config_view(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_safe_config_view(item) for item in value]
    return value


def render_settings(registry: ModelRegistry, pipeline: SafeChatPipeline) -> None:
    snapshot = registry.snapshot()
    default_provider = str(snapshot.get("default_provider") or "暂无")
    output_guard_ready = pipeline.output_guard is not None
    page_intro(
        "OPERATIONS / SETTINGS",
        "系统设置与关于",
        "查看当前运行策略、配置来源与产品能力；核心安全阈值保持只读。",
        pills=(
            ("配置已生效", "success"),
            ("安全策略已锁定", "warning"),
            (f"默认模型 · {default_provider}", "purple"),
        ),
    )
    _render_kpis(
        (
            ("运行配置", "已生效", "settings", "success", "config.yaml"),
            ("安全策略", "只读锁定", "lock", "warning", "网页不可修改"),
            ("默认 Provider", default_provider, "model", "purple", "模型注册表"),
            ("审计日志", "已启用", "database", "blue", "递归脱敏"),
        )
    )
    section_header("产品设置", "将工程配置转换为可核查的运行摘要")
    left, right = st.columns([1.35, 1])
    with left:
        setting_rows(
            (
                ("默认 Provider", default_provider, "模型管理页可切换"),
                ("日志状态", "启用", "请求摘要 + 敏感字段递归脱敏"),
                ("OutputGuard", "启用" if output_guard_ready else "不可用", "模型输出返回前复检"),
                ("运行时覆盖", "本地 overlay", "Git 忽略，不进入版本库"),
                ("核心安全阈值", "只读", "管理页面不开放修改入口"),
            )
        )
    with right:
        about_card()
    with st.expander("查看原始配置 JSON（敏感值已隐藏）", expanded=False):
        st.json(_safe_config_view(pipeline.config))
    info_card("管理员身份认证将在具备可靠身份边界后接入；当前管理端只展示脱敏审计摘要，且不提供密钥明文读取能力。")


def _display_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "时间": item["time"],
                "Request ID": item["request_id"],
                "Provider": item["provider"],
                "风险类别": item["category"],
                "风险等级": item["risk_level"].upper(),
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
