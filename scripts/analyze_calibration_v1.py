from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


METRIC_FILES = {
    "rule_only": "rule_only_calibration_metrics.json",
    "semantic_only": "semantic_only_calibration_metrics.json",
    "combined": "combined_calibration_metrics.json",
}
LABELS = ("normal", "ad", "porn", "violence", "sensitive")
ACTIONS = ("pass", "sanitize", "block")

FAILURE_FAMILIES = (
    (
        "高危：非法交易与欺诈",
        ("放款", "解冻费", "投注", "彩金", "内幕", "考试答案", "垫付", "佣金"),
    ),
    (
        "高危：付费色情传播与偷拍",
        (
            "露骨",
            "偷拍",
            "私密照片",
            "偷拍视频",
            "成人视频",
            "付费群",
        ),
    ),
    (
        "高危：武器交易与现实攻击",
        (
            "枪支",
            "武器",
            "殴打",
            "围堵",
            "攻击",
            "棍棒",
            "上门报复",
        ),
    ),
    (
        "高危：隐私交易与极端组织",
        (
            "身份证",
            "实时定位",
            "开房记录",
            "出行轨迹",
            "迫害",
            "极端团体",
            "清除名单",
            "m i yao",
        ),
    ),
    (
        "脱敏：私域促销与付费解锁",
        (
            "私域群",
            "付费激活码",
            "内部价",
            "私下转账",
            "专享价",
            "付费解锁",
        ),
    ),
    (
        "脱敏：局部成人入口",
        ("裸聊体验", "色情直播体验", "成人裸聊"),
    ),
    (
        "脱敏：对话内低强度威胁",
        ("踢你", "推开", "一巴掌", "扇你"),
    ),
    (
        "脱敏：健康与亲密关系隐私",
        (
            "治疗记录",
            "抑郁治疗",
            "hiv治疗",
            "治疗随访",
            "性伴侣",
            "焦虑治疗",
        ),
    ),
    (
        "误报：教学、研究与新闻",
        ("教材", "课程", "课堂", "论文", "新闻", "通报", "纪录片"),
    ),
    (
        "误报：反诈、拒绝与安全处置",
        ("反诈", "拒绝", "不要", "不得", "反对", "举报", "制止"),
    ),
)


def load_metrics(metrics_dir: Path) -> dict[str, dict[str, Any]]:
    loaded = {}
    for mode, filename in METRIC_FILES.items():
        path = metrics_dir / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("mode") != mode:
            raise ValueError(f"{filename}: unexpected mode")
        if not isinstance(payload.get("predictions"), list):
            raise ValueError(f"{filename}: predictions missing")
        loaded[mode] = payload
    return loaded


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def action_confusion(payload: dict[str, Any]) -> Counter[tuple[str, str]]:
    return Counter(
        (row["expected_action"], row["predicted_action"])
        for row in payload["predictions"]
    )


def failure_family_counts(payload: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in payload["predictions"]:
        label_error = row["true_label"] != row["predicted_label"]
        action_error = row["expected_action"] != row["predicted_action"]
        if not label_error and not action_error:
            continue
        text = row["normalized_text"]
        matched = False
        for name, terms in FAILURE_FAMILIES:
            if any(term in text for term in terms):
                counts[name] += 1
                matched = True
                break
        if not matched:
            counts["其他未覆盖表达"] += 1
    return counts


def render(metrics: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Calibration 分析 V1",
        "",
        "数据边界：本报告仅由三个固定白名单 `*_calibration_metrics.json` "
        "以 UTF-8 读取生成，未扫描评估目录，也未读取任何 test 产物。",
        "",
        "## 三模式指标",
        "",
        "| 模式 | Accuracy | Macro F1 | Action Accuracy | Normal FPR | "
        "High-risk Block Recall | Sanitize Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in METRIC_FILES:
        payload = metrics[mode]
        lines.append(
            "| {mode} | {accuracy} | {macro_f1} | {action_accuracy} | "
            "{normal_fpr} | {block_recall} | {sanitize_recall} |".format(
                mode=mode,
                accuracy=percent(payload["accuracy"]),
                macro_f1=percent(payload["macro_f1"]),
                action_accuracy=percent(payload["action_accuracy"]),
                normal_fpr=percent(payload["normal_false_positive_rate"]),
                block_recall=percent(payload["high_risk_block_recall"]),
                sanitize_recall=percent(payload["sanitize_routing_recall"]),
            )
        )

    lines.extend(
        [
            "",
            "## 按类别召回",
            "",
            "| 模式 | normal | ad | porn | violence | sensitive |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for mode in METRIC_FILES:
        per_class = metrics[mode]["per_class"]
        lines.append(
            f"| {mode} | "
            + " | ".join(percent(per_class[label]["recall"]) for label in LABELS)
            + " |"
        )

    lines.extend(["", "## 动作混淆", ""])
    for mode in METRIC_FILES:
        confusion = action_confusion(metrics[mode])
        lines.extend(
            [
                f"### {mode}",
                "",
                "| Gold \\ Pred | pass | sanitize | block |",
                "|---|---:|---:|---:|",
            ]
        )
        for expected in ACTIONS:
            values = " | ".join(
                str(confusion[(expected, predicted)]) for predicted in ACTIONS
            )
            lines.append(f"| {expected} | {values} |")
        lines.append("")

    lines.extend(
        [
            "## 失败族统计",
            "",
            "统计口径：类别或动作任一不一致即计为失败；每条记录按首个匹配的"
            "抽象失败族计一次。",
            "",
            "| 失败族 | rule_only | semantic_only | combined |",
            "|---|---:|---:|---:|",
        ]
    )
    family_counts = {
        mode: failure_family_counts(metrics[mode]) for mode in METRIC_FILES
    }
    family_names = [
        name for name, _ in FAILURE_FAMILIES
    ] + ["其他未覆盖表达"]
    for family in family_names:
        values = [family_counts[mode][family] for mode in METRIC_FILES]
        if any(values):
            lines.append(
                f"| {family} | {values[0]} | {values[1]} | {values[2]} |"
            )

    lines.extend(
        [
            "",
            "## 根因",
            "",
            "1. `RuleFilter` 的旧词典以孤立词命中为主，缺少“危险对象 + "
            "交易、组织、传播、攻击或操作意图”的组合证据，导致高危样本多为 pass。",
            "2. 五分类语义模型只给类别置信度，低置信风险被路由为 sanitize，"
            "无法可靠区分同类别内的 sanitize 与 block；因此不能靠全局阈值解决严重度。",
            "3. 通用组合规则、安全语境和 sanitize 机制虽存在于 `ActionRouter`，"
            "但系统三模式的检测证据链只消费 RuleFilter / SemanticClassifier 输出，"
            "原先没有让这些机制形成检测证据。",
            "4. 旧关键词缺少教学、论文、新闻、反诈、拒绝和安全处置的局部范围保护，"
            "而安全语境若无明确的 unsafe override，又会在检测层产生正常文本误报。",
            "5. Normalizer 已能恢复常见分隔符与混淆写法；主要瓶颈不是归一化，"
            "而是归一化后缺少组合意图与严重度路由。",
            "",
            "## 修复方向",
            "",
            "- 复用 ActionRouter 的抽象词组组合策略，在检测层产出通用 policy evidence。",
            "- block 仅由危险对象与明确操作意图组合触发；局部促销、低强度威胁、"
            "健康/亲密关系字段走 sanitize。",
            "- 安全语境按子句和距离保护；出现交易、传播、组织、攻击、招募或"
            "可操作请求时由 unsafe override 恢复风险路由。",
            "- 保持现有语义阈值不变，不通过降低全局 block 阈值追分。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = render(load_metrics(args.metrics_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
