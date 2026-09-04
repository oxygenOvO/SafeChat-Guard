"""Phase-three policy, explanation, and evaluation product views."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from frontend.ui_components import info_card, kpi_card, page_intro, section_header
from safechat_guard.decision_explanation_service import DecisionExplanationService
from safechat_guard.evaluation_service import EvaluationInputError, EvaluationService
from safechat_guard.rule_management_service import (
    RuleManagementService,
    RuleWritesDisabledError,
)
from safechat_guard.rule_manager import RuleManagerError


ACTION_LABELS = {"pass": "PASS", "sanitize": "SANITIZE", "block": "BLOCK", "not_run": "未执行"}
CATEGORY_LABELS = {"normal": "正常", "porn": "色情低俗", "violence": "暴力", "ad": "广告引流", "sensitive": "敏感话术"}


def render_decision_explanation(
    explanation: dict[str, Any], *, show_raw_expander: bool = True
) -> None:
    action = str(explanation.get("final", {}).get("action") or "not_run")
    normalization = explanation.get("normalization", {})
    rule_filter = explanation.get("rule_filter", {})
    semantic = explanation.get("semantic_classifier", {})
    router = explanation.get("action_router", {})
    sanitizer = explanation.get("sanitizer", {})
    output = explanation.get("output_guard", {})
    stage_rows = (
        ("01", "输入", "blue", f"Request · {explanation.get('request_id', '—')}"),
        ("02", "TextNormalizer", "pass" if not normalization.get("changed") else "sanitize", "已规范化" if normalization.get("changed") else "无需变更"),
        ("03", "RuleFilter", "block" if rule_filter.get("hits") else "pass", f"{len(rule_filter.get('hits') or [])} 条证据"),
        ("04", "SemanticClassifier", "pass" if not semantic.get("selected_category") else "sanitize", str(semantic.get("top_category") or "未加载")),
        ("05", "Router / Sanitizer", str(router.get("action") or "not_run"), ACTION_LABELS.get(str(router.get("action")), str(router.get("action")))),
        ("06", "OutputGuard", str(output.get("action") or "not_run"), ACTION_LABELS.get(str(output.get("action") or "not_run"), "未执行")),
    )
    cards = "".join(
        f'<div class="sg-stage {escape(tone)}"><div class="sg-stage-index">{index}</div>'
        f'<div class="sg-stage-title">{escape(title)}</div><div class="sg-stage-detail">{escape(detail)}</div></div>'
        for index, title, tone, detail in stage_rows
    )
    st.markdown(f'<div class="sg-decision-rail" data-ui="decision-rail">{cards}</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**输入与规范化**")
        st.code(str(explanation.get("input", {}).get("original_text", "[NOT STORED]")), language=None)
        st.code(str(normalization.get("normalized_text", "[NOT STORED]")), language=None)
        if normalization.get("steps"):
            st.dataframe(pd.DataFrame(normalization["steps"]), use_container_width=True, hide_index=True)
        st.markdown("**规则证据**")
        if rule_filter.get("hits"):
            st.dataframe(pd.DataFrame(rule_filter["hits"]), use_container_width=True, hide_index=True)
        else:
            st.caption("未命中规则。")
        if rule_filter.get("matched_rule_ids"):
            st.caption("Rule ID：" + ", ".join(rule_filter["matched_rule_ids"]))
    with right:
        st.markdown("**语义真实得分**")
        scores = semantic.get("scores") or {}
        if scores:
            for label, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
                width = max(0.0, min(float(score), 1.0)) * 100
                st.markdown(
                    f'<div class="sg-score-row"><span>{escape(CATEGORY_LABELS.get(label, label))}</span>'
                    f'<span class="sg-score-track"><span class="sg-score-fill" style="display:block;width:{width:.2f}%"></span></span>'
                    f'<b>{float(score):.1%}</b></div>', unsafe_allow_html=True,
                )
            st.caption(
                f"Top: {semantic.get('top_category')} · normal: {float(semantic.get('normal_score') or 0):.1%} · "
                f"threshold: {semantic.get('threshold')} · normal margin: {semantic.get('normal_margin')}"
            )
        else:
            st.caption(str(semantic.get("note") or semantic.get("error") or "语义模型未提供分数。"))
        st.markdown("**路由与安全处理**")
        st.write(
            f"最终风险：{router.get('risk_level', '—')} / {router.get('risk_score', 0)} · "
            f"动作：{ACTION_LABELS.get(str(router.get('action')), router.get('action', '—'))}"
        )
        if sanitizer.get("called"):
            st.code(str(sanitizer.get("actual_model_input") or "未转发模型"), language=None)
        st.write(f"OutputGuard：{ACTION_LABELS.get(str(output.get('action')), output.get('action', '未执行'))}")
    if show_raw_expander:
        with st.expander("查看原始解释数据", expanded=False):
            st.json(explanation)


def render_policy_center(pipeline: Any) -> None:
    service = RuleManagementService(pipeline)
    page_intro(
        "SECURITY / POLICY",
        "安全策略中心",
        "从候选校验到版本回滚，所有操作复用当前规则 overlay 与原子发布链。",
        pills=(("默认只读" if not service.writes_enabled else "写操作已启用", "warning"),),
    )
    if not service.writes_enabled:
        info_card("写操作已由 SAFECHAT_ENABLE_RULE_WRITES=false 锁定。查看、筛选、校验、测试、版本与 Diff 仍可使用。")
    query_col, category_col, type_col = st.columns([2, 1, 1])
    query = query_col.text_input("搜索", placeholder="Rule ID、说明或规则内容")
    category = category_col.selectbox("风险类别", ["全部", "porn", "violence", "ad", "sensitive"])
    pattern_type = type_col.selectbox("规则匹配模式", ["全部", "keyword", "phrase", "regex"])
    catalog = service.catalog(
        query=query,
        category=None if category == "全部" else category,
        pattern_type=None if pattern_type == "全部" else pattern_type,
    )
    k1, k2, k3 = st.columns(3)
    with k1: kpi_card("当前 Revision", catalog["revision"], "route", "blue", "原子 overlay")
    with k2: kpi_card("筛选结果", len(catalog["rules"]), "filter", "purple", "内置 + 用户规则")
    with k3: kpi_card("写操作", "开启" if service.writes_enabled else "关闭", "lock", "warning", "环境变量保护")
    rows = [{key: rule.get(key) for key in ("id", "category", "pattern_type", "risk_level", "action", "enabled", "read_only")} for rule in catalog["rules"]]
    display_rows = pd.DataFrame(rows).rename(
        columns={
            "id": "规则 ID",
            "category": "风险类别",
            "pattern_type": "规则匹配模式",
            "risk_level": "风险等级",
            "action": "处置动作",
            "enabled": "是否启用",
            "read_only": "是否只读",
        }
    )
    st.dataframe(display_rows, use_container_width=True, hide_index=True)
    if catalog["rules"]:
        selected_id = st.selectbox("查看规则详情", [rule["id"] for rule in catalog["rules"]])
        selected = service.get_rule(selected_id)
        with st.expander("规则详情", expanded=False):
            st.json(selected)

    test_tab, candidate_tab, version_tab = st.tabs(["单规则测试", "Candidate 校验与发布", "版本 / Diff / 回滚"])
    with test_tab:
        if catalog["rules"]:
            test_rule_id = st.selectbox("目标规则", [rule["id"] for rule in catalog["rules"]], key="policy_test_rule")
            test_text = st.text_area("测试文本", key="policy_test_text")
            if st.button("测试规则", disabled=not test_text.strip()):
                st.json(service.test_rule(test_rule_id, test_text))
    with candidate_tab:
        with st.form("policy_candidate"):
            cols = st.columns(2)
            rule_id = cols[0].text_input("Rule ID")
            pattern = cols[1].text_input("规则内容")
            pattern_kind = cols[0].selectbox("匹配类型", ["keyword", "phrase", "regex"])
            candidate_category = cols[1].selectbox("风险类别", ["porn", "violence", "ad", "sensitive"])
            risk_level = cols[0].selectbox("风险等级", ["low", "medium", "high"], index=1)
            candidate_action = cols[1].selectbox("Action", ["sanitize", "block"])
            description = st.text_input("说明")
            validate = st.form_submit_button("校验 Candidate")
        if validate:
            candidate = {"id": rule_id, "pattern": pattern, "pattern_type": pattern_kind, "category": candidate_category, "action": candidate_action, "risk_level": risk_level, "enabled": True, "description": description}
            try:
                report = service.validate_candidate(candidate)
            except RuleManagerError as exc:
                st.error(str(exc))
            else:
                st.session_state["validated_policy_candidate"] = candidate if not report["invalid"] else None
                st.json(report)
        candidate = st.session_state.get("validated_policy_candidate")
        if st.button("发布已校验 Candidate", disabled=not service.writes_enabled or not candidate):
            try:
                service.publish_candidate(candidate, expected_revision=catalog["revision"])
            except (RuleManagerError, RuleWritesDisabledError) as exc:
                st.error(str(exc))
            else:
                st.success("Candidate 已原子发布。")
                st.rerun()
    with version_tab:
        st.dataframe(pd.DataFrame(service.versions()), use_container_width=True, hide_index=True)
        diff = service.diff()
        st.json(diff)
        if st.button("回滚到上一版本", disabled=not service.writes_enabled or not diff["available"]):
            try:
                service.rollback(expected_revision=catalog["revision"])
            except (RuleManagerError, RuleWritesDisabledError) as exc:
                st.error(str(exc))
            else:
                st.success("上一版本已作为新 Revision 发布。")
                st.rerun()


def render_evaluation_lab(pipeline: Any) -> None:
    service = EvaluationService(pipeline)
    page_intro(
        "SECURITY / EVALUATION",
        "安全评测实验室",
        "以隔离运行验证规则、语义与融合能力；不调用外部模型，不写入生产审计。",
        pills=(("Evaluation 隔离", "success"), ("LLM 不调用", "purple")),
    )
    single_tab, compare_tab, batch_tab = st.tabs(["单文本分析", "检测能力对比", "批量评测"])
    with single_tab:
        text = st.text_area("待分析文本", key="evaluation_single_text", height=120)
        if st.button("运行输入检测", disabled=not text.strip()):
            try:
                st.session_state["evaluation_single_result"] = service.analyze(text)
            except EvaluationInputError as exc:
                st.error(str(exc))
        result = st.session_state.get("evaluation_single_result")
        if result:
            st.markdown(f'<span class="sg-badge {result["action"]}">{ACTION_LABELS[result["action"]]}</span>', unsafe_allow_html=True)
            render_decision_explanation(result["explanation"])
    with compare_tab:
        compare_text = st.text_area("对比文本", key="evaluation_compare_text", height=110)
        if st.button("运行五模式对比", disabled=not compare_text.strip()):
            st.session_state["evaluation_comparison"] = service.compare(compare_text)
        comparison = st.session_state.get("evaluation_comparison")
        if comparison:
            comparison_rows = [{"模式": item["mode"], "类别": item["category"], "风险": item["risk_level"], "Rule hit": item["rule_hit"], "Semantic top": item["semantic_top_class"], "Action": item["action"]} for item in comparison["results"]]
            st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)
            selected_mode = st.selectbox("查看模式解释", [item["mode"] for item in comparison["results"]])
            selected_result = next(item for item in comparison["results"] if item["mode"] == selected_mode)
            render_decision_explanation(selected_result["explanation"])
    with batch_tab:
        multiline = st.text_area("多行文本（每行一条）", key="evaluation_batch_text", height=130)
        upload = st.file_uploader("或上传 UTF-8 CSV / JSONL", type=["csv", "jsonl"])
        if st.button("运行批量评测", disabled=not multiline.strip() and upload is None):
            try:
                if upload is not None:
                    rows = service.parse_upload(upload.getvalue(), format_name=Path(upload.name).suffix.lower().lstrip("."))
                else:
                    rows = [{"text": line.strip()} for line in multiline.splitlines() if line.strip()]
                st.session_state["evaluation_batch_result"] = service.batch(rows)
            except EvaluationInputError as exc:
                st.error(str(exc))
        batch = st.session_state.get("evaluation_batch_result")
        if batch:
            columns = st.columns(4)
            metrics = (
                ("总数", batch["total"], "blue"),
                ("PASS", batch["counts"]["pass"], "success"),
                ("SANITIZE", batch["counts"]["sanitize"], "warning"),
                ("BLOCK", batch["counts"]["block"], "danger"),
            )
            for column, (label, value, tone) in zip(columns, metrics):
                with column:
                    kpi_card(label, value, "requests", tone, "当前 evaluation run")
            if batch["metrics"] is None:
                st.info("当前数据没有完整 ground truth，不计算 Accuracy、Macro F1 或 Recall。")
            else:
                st.json(batch["metrics"])
            st.dataframe(pd.DataFrame(batch["results"]), use_container_width=True, hide_index=True)
            st.download_button("导出评测 CSV", service.to_csv(batch["results"]), "safechat_evaluation.csv", "text/csv")


def render_historical_explanation(record: dict[str, Any]) -> None:
    render_decision_explanation(DecisionExplanationService.explain_audit_record(record))
