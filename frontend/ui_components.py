"""Small, data-driven presentation components for the management console."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, Mapping

import streamlit as st


_ICONS = {
    "shield": '<path d="M12 3 5 6v5c0 4.6 2.9 8 7 10 4.1-2 7-5.4 7-10V6l-7-3Z"/><path d="m9.2 12 1.8 1.8 3.8-4"/>',
    "pulse": '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    "model": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9zM9 1v3m6-3v3M9 20v3m6-3v3M1 9h3m-3 6h3m16-6h3m-3 6h3"/>',
    "requests": '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
    "filter": '<path d="M4 5h16l-6 7v5l-4 2v-7L4 5Z"/>',
    "block": '<circle cx="12" cy="12" r="9"/><path d="m8 8 8 8m0-8-8 8"/>',
    "lock": '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "route": '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h4a3 3 0 0 1 3 3v8a3 3 0 0 0 3 3"/>',
    "eye": '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8m-3 3 2 2m-5 1 2 2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
}


def icon(name: str, size: int = 18) -> str:
    paths = _ICONS.get(name, _ICONS["shield"])
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
    )


def page_intro(
    kicker: str,
    title: str,
    description: str,
    *,
    status: tuple[str, str] | None = None,
    pills: Iterable[tuple[str, str]] = (),
) -> None:
    metadata = list(pills)
    if status:
        metadata.insert(0, status)
    pill_html = "".join(
        f'<span class="sg-pill {escape(tone)}">{escape(label)}</span>'
        for label, tone in metadata
    )
    st.markdown(
        f'<div class="sg-page-head" data-ui="page-header"><div>'
        f'<div class="sg-kicker">{escape(kicker)}</div><h1>{escape(title)}</h1>'
        f'<p>{escape(description)}</p></div><div class="sg-head-meta">{pill_html}</div></div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, description: str = "") -> None:
    st.markdown(
        f'<div class="sg-section-head"><h2>{escape(title)}</h2>'
        f'<p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: Any, icon_name: str, tone: str = "blue", note: str = "") -> None:
    st.markdown(
        f'<div class="sg-kpi tone-{escape(tone)}" data-ui="kpi-card">'
        f'<div class="sg-kpi-icon">{icon(icon_name)}</div>'
        f'<div class="sg-kpi-label">{escape(str(label))}</div>'
        f'<div class="sg-kpi-value">{escape(str(value))}</div>'
        f'<div class="sg-kpi-note">{escape(str(note))}</div></div>',
        unsafe_allow_html=True,
    )


def setting_rows(rows: Iterable[tuple[str, str, str]]) -> None:
    html = []
    for label, value, hint in rows:
        html.append(
            '<div class="sg-setting-row">'
            f'<div><div class="sg-setting-label">{escape(label)}</div>'
            f'<div class="sg-setting-hint">{escape(hint)}</div></div>'
            f'<div class="sg-setting-value">{escape(value)}</div></div>'
        )
    st.markdown(
        f'<div class="sg-setting-card" data-ui="setting-list">{"".join(html)}</div>',
        unsafe_allow_html=True,
    )


def about_card() -> None:
    capabilities = ("输入检测", "输出复检", "风险处置", "多模型接入", "审计追踪", "运行监测")
    chips = "".join(f'<span class="sg-capability">{item}</span>' for item in capabilities)
    st.markdown(
        f'<div class="sg-about-card" data-ui="about-card"><div class="sg-about-mark">{icon("shield", 24)}</div>'
        '<h3>SafeChat-Guard V1.0</h3><p>面向大模型应用的双向内容安全防护系统，'
        '在模型调用前后执行统一检测、处置与脱敏审计。</p>'
        f'<div class="sg-capabilities">{chips}</div></div>',
        unsafe_allow_html=True,
    )


def info_card(message: str) -> None:
    st.markdown(
        f'<div class="sg-info-card" data-ui="info-card"><span>{icon("info")}</span>'
        f'<span>{escape(message)}</span></div>',
        unsafe_allow_html=True,
    )


def audit_event_table(records: list[Mapping[str, Any]], action_labels: Mapping[str, str]) -> None:
    rows = []
    for item in records:
        request_id = str(item.get("request_id") or "—")
        short_id = request_id if len(request_id) <= 16 else f"{request_id[:12]}…"
        action = str(item.get("final_action") or "not_run").lower()
        risk = str(item.get("risk_level") or "unknown").lower()
        rows.append(
            '<tr>'
            f'<td>{escape(str(item.get("time") or "—"))}</td>'
            f'<td class="sg-mono" title="{escape(request_id)}">{escape(short_id)}</td>'
            f'<td>{escape(str(item.get("provider") or "—"))}</td>'
            f'<td>{escape(str(item.get("category") or "—"))}</td>'
            f'<td><span class="sg-badge {escape(risk)}">{escape(risk.upper())}</span></td>'
            f'<td><span class="sg-badge {escape(action)}">{escape(action_labels.get(action, action.upper()))}</span></td>'
            '</tr>'
        )
    st.markdown(
        '<div class="sg-event-table" data-ui="audit-event-table"><table><thead><tr>'
        '<th>时间</th><th>Request ID</th><th>Provider</th><th>风险类别</th><th>风险等级</th><th>最终动作</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def health_list(rows: Iterable[tuple[str, str, str, str]]) -> None:
    html = []
    for name, status, tone, detail in rows:
        html.append(
            '<div class="sg-health-row">'
            f'<strong>{escape(name)}</strong><span><span class="sg-badge {escape(tone)}">{escape(status)}</span></span>'
            f'<span class="sg-health-detail">{escape(detail or "—")}</span></div>'
        )
    st.markdown(
        f'<div class="sg-health-list" data-ui="health-list">{"".join(html)}</div>',
        unsafe_allow_html=True,
    )
