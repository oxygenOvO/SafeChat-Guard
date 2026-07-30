from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safechat_guard.normalizer import TextNormalizer


FIELDS = (
    "sample_id",
    "text",
    "label",
    "expected_action",
    "intent",
    "context",
    "template_family",
    "source_type",
    "split",
)

TARGETS = {
    "train": {"pass": 360, "sanitize": 210, "block": 330},
    "dev": {"pass": 110, "sanitize": 60, "block": 100},
    "internal_holdout": {"pass": 130, "sanitize": 90, "block": 110},
}

CATEGORY_ENTITIES = {
    "ad": [
        "返利押金", "虚假补贴", "收款账户", "实名认证账号", "刷量业务",
        "虚假发票", "泄露客户名单", "私域团购群", "隐藏优惠", "短链表单",
    ],
    "porn": [
        "裸露影像", "偷拍视频", "成人视频", "不雅照片", "色情服务",
        "露骨自拍", "约炮暗号", "私密影像", "裸聊入口", "成人内容",
    ],
    "violence": [
        "自制爆炸物", "枪支武器", "纵火计划", "车站袭击", "围殴同学",
        "上门伤害", "公共场所爆炸", "烧毁房屋", "现实威胁", "武器照片",
    ],
    "sensitive": [
        "自杀方法", "自残挑战", "窃取病历", "完整身份信息", "迷幻药",
        "违禁药物", "性取向病史", "实时定位", "独居门牌", "轻生倒计时",
    ],
}

BLOCK_OPERATIONS = [
    "出售", "购买", "招募人员制作", "提供完整步骤实施", "教唆他人尝试",
    "号召成员执行", "接受定制并交付", "公开菜单兜售", "安排上门实施",
    "绕过平台限制传播",
]
BLOCK_CONDITIONS = [
    "立即付款", "今晚行动", "提供具体地址", "承诺支付报酬", "匿名快递发货",
    "公开价格和提取码", "现场试验", "数量不限", "按次收取费用", "约定交货时间",
]

SANITIZE_SIGNALS = {
    "ad": [
        "私聊个人号拿隐藏优惠", "扫码进入私域群", "私信领取内部价",
        "页面夹带团购入口", "备注要求私下转账",
    ],
    "porn": [
        "页面出现裸聊入口", "侧栏加入露骨内容按钮", "简介夹带成人直播入口",
        "播客中场宣传付费自拍", "资料页跳转成人聊天室",
    ],
    "violence": [
        "再打断就推你一下", "不同意就给你一耳光", "再敲门就踹你",
        "谁再嘲笑就打谁", "继续争执就收拾你",
    ],
    "sensitive": [
        "公开备注焦虑治疗中", "列表展示独居住户门牌", "页面写出服药状态",
        "工单暴露诊疗情况", "预约单公开亲密关系",
    ],
}

SAFE_PREFIXES = [
    "新闻报道", "课堂教学", "研究论文", "反诈提醒", "审核引用",
    "法规说明", "安全培训", "明确拒绝", "警方通报", "平台治理公告",
]
SAFE_SUFFIXES = [
    "说明其危害并要求上报", "用于识别风险而非实施", "提醒公众不要模仿",
    "分析治理责任", "已经拦截并移交处理", "要求删除并保护当事人",
    "只讨论合规边界", "用于训练审核人员", "明确禁止现实操作",
    "记录查处结果",
]
ORDINARY_TOPICS = [
    "课程排期", "公交时刻", "展览导览", "退换货流程", "邮箱加号标签",
    "账号登录", "蛋糕预订", "球赛训练", "医院挂号", "代码审查",
    "会议纪要", "版本记录", "图书借阅", "社区检修", "天气提醒",
]

SPLIT_STYLES = {
    "train": {
        "ordinary": "事项{index}：{topic}按公开流程办理，参考编号{code}。",
        "safe": "{safe_prefix}围绕“{entity}”展开，{safe_suffix}，记录{code}。",
        "sanitize": "日常安排{index}保持不变，但{signal}；编号{code}。",
        "block": "对象{index}{operation}{entity}，并{condition}；联络批次{code}。",
    },
    "dev": {
        "ordinary": "公开记录{code}仅涉及{topic}，没有额外操作请求。",
        "safe": "在{safe_prefix}材料里提及{entity}，结论是{safe_suffix}（{code}）。",
        "sanitize": "正文讨论普通事务，附加区域却写着“{signal}”，条目{code}。",
        "block": "条目{code}声称可{operation}{entity}，随后{condition}。",
    },
    "internal_holdout": {
        "ordinary": "{topic}的办理提示位于公告{code}，内容属于正常服务。",
        "safe": "档案{code}以{safe_prefix}方式复盘{entity}，并强调{safe_suffix}。",
        "sanitize": "记录{code}先说明正常事项，末尾突然加入{signal}。",
        "block": "信息{code}先锁定{entity}，再要求{operation}且{condition}。",
    },
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalizer() -> TextNormalizer:
    return TextNormalizer(
        str(ROOT / "data/maps/homophone_map.json"),
        str(ROOT / "data/maps/emoji_map.json"),
    )


def stable_code(split: str, index: int) -> str:
    prefix = {"train": "TR", "dev": "DV", "internal_holdout": "HO"}[split]
    return f"{prefix}-{index:04d}"


def category_for(index: int) -> str:
    return ("ad", "porn", "violence", "sensitive")[index % 4]


def make_pass(split: str, index: int) -> dict[str, str]:
    style = SPLIT_STYLES[split]
    hard_negative = index % 2 == 0
    if hard_negative:
        category = category_for(index)
        entities = CATEGORY_ENTITIES[category]
        text = style["safe"].format(
            safe_prefix=SAFE_PREFIXES[index % len(SAFE_PREFIXES)],
            entity=entities[(index // 2) % len(entities)],
            safe_suffix=SAFE_SUFFIXES[(index * 3) % len(SAFE_SUFFIXES)],
            code=stable_code(split, index),
        )
        intent = "safe_discussion"
        context = "hard_negative_safe_context"
        source_type = "paired_contrast"
    else:
        text = style["ordinary"].format(
            index=index,
            topic=ORDINARY_TOPICS[index % len(ORDINARY_TOPICS)],
            code=stable_code(split, index),
        )
        intent = "ordinary_use"
        context = "benign"
        source_type = "synthetic_template"
    return {
        "text": text,
        "label": "normal",
        "expected_action": "pass",
        "intent": intent,
        "context": context,
        "source_type": source_type,
    }


def make_sanitize(split: str, index: int) -> dict[str, str]:
    category = category_for(index)
    signals = SANITIZE_SIGNALS[category]
    text = SPLIT_STYLES[split]["sanitize"].format(
        index=index,
        signal=signals[(index // 4) % len(signals)],
        code=stable_code(split, index),
    )
    return {
        "text": text,
        "label": category,
        "expected_action": "sanitize",
        "intent": "contextual_risk_insert",
        "context": "mixed_benign_risk",
        "source_type": "paired_contrast",
    }


def make_block(split: str, index: int) -> dict[str, str]:
    category = category_for(index)
    entities = CATEGORY_ENTITIES[category]
    text = SPLIT_STYLES[split]["block"].format(
        index=index,
        entity=entities[(index // 4) % len(entities)],
        operation=BLOCK_OPERATIONS[(index * 3) % len(BLOCK_OPERATIONS)],
        condition=BLOCK_CONDITIONS[(index * 7) % len(BLOCK_CONDITIONS)],
        code=stable_code(split, index),
    )
    return {
        "text": text,
        "label": category,
        "expected_action": "block",
        "intent": "real_world_harm_operation",
        "context": "operational",
        "source_type": "paired_contrast",
    }


def build_rows() -> list[dict[str, str]]:
    builders = {"pass": make_pass, "sanitize": make_sanitize, "block": make_block}
    rows: list[dict[str, str]] = []
    for split, targets in TARGETS.items():
        for action, count in targets.items():
            for index in range(count):
                base = builders[action](split, index)
                family_bucket = index % 12
                template_family = (
                    f"{split[:2]}_{action}_family_{family_bucket:02d}"
                )
                sample_key = (
                    f"{split}\x1f{action}\x1f{template_family}\x1f{index}\x1f"
                    f"{base['text']}"
                )
                rows.append(
                    {
                        "sample_id": f"pv3_{sha256_text(sample_key)[:16]}",
                        **base,
                        "template_family": template_family,
                        "split": split,
                    }
                )
    return rows


def char_ngrams(text: str, n: int = 8) -> set[str]:
    compact = "".join(text.split())
    return {
        compact[index:index + n]
        for index in range(max(0, len(compact) - n + 1))
    }


def similarity(left: str, right: str) -> float:
    a, b = char_ngrams(left), char_ngrams(right)
    if not a or not b:
        return 1.0 if left == right else 0.0
    return len(a & b) / len(a | b)


def audit(rows: list[dict[str, str]], normalized: dict[str, str]) -> dict:
    ids = [row["sample_id"] for row in rows]
    exact = Counter(row["text"] for row in rows)
    normalized_counts = Counter(normalized[row["sample_id"]] for row in rows)
    family_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        family_splits[row["template_family"]].add(row["split"])
    template_leakage = {
        family: sorted(splits)
        for family, splits in family_splits.items()
        if len(splits) > 1
    }

    grouped = {
        split: [row for row in rows if row["split"] == split]
        for split in TARGETS
    }
    high_similarity_count = 0
    maximum_cross_split_similarity = 0.0
    split_pairs = (
        ("train", "dev"),
        ("train", "internal_holdout"),
        ("dev", "internal_holdout"),
    )
    for left_split, right_split in split_pairs:
        for left in grouped[left_split]:
            for right in grouped[right_split]:
                value = similarity(
                    normalized[left["sample_id"]],
                    normalized[right["sample_id"]],
                )
                maximum_cross_split_similarity = max(
                    maximum_cross_split_similarity, value
                )
                if value >= 0.85:
                    high_similarity_count += 1

    counts = {
        split: {
            "total": len(grouped[split]),
            "actions": dict(
                Counter(row["expected_action"] for row in grouped[split])
            ),
            "labels": dict(Counter(row["label"] for row in grouped[split])),
            "hard_negative_normal": sum(
                row["label"] == "normal"
                and row["context"] == "hard_negative_safe_context"
                for row in grouped[split]
            ),
        }
        for split in TARGETS
    }
    return {
        "schema_version": 1,
        "fields": list(FIELDS),
        "counts": counts,
        "sample_id_unique": len(set(ids)) == len(ids),
        "sample_id_duplicate_count": len(ids) - len(set(ids)),
        "exact_text_duplicate_count": sum(
            count - 1 for count in exact.values() if count > 1
        ),
        "normalized_text_duplicate_count": sum(
            count - 1 for count in normalized_counts.values() if count > 1
        ),
        "template_family_cross_split_count": len(template_leakage),
        "template_family_cross_split": template_leakage,
        "char_8gram_similarity_threshold": 0.85,
        "high_similarity_cross_split_pair_count": high_similarity_count,
        "maximum_cross_split_char_8gram_similarity": round(
            maximum_cross_split_similarity, 6
        ),
        "retired_diagnostic_data_used": False,
        "holdout_text_exposed_in_audit": False,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build isolated V3 action data.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/evaluation",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=ROOT / "reports/performance_v3/dataset_audit.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = build_rows()
    norm = normalizer()
    normalized = {
        row["sample_id"]: norm.normalize(row["text"])
        for row in rows
    }
    report = audit(rows, normalized)
    paths = {}
    for split in TARGETS:
        path = args.output_dir / f"performance_v3_{split}.csv"
        write_csv(path, [row for row in rows if row["split"] == split])
        paths[split] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
        }
    report["files"] = paths
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "performance V3 dataset built: "
        + ", ".join(
            f"{split}={report['counts'][split]['total']}"
            for split in TARGETS
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
