"""SafeChatPipeline——系统的主流程编排器。

一次完整的对话请求（handle_chat）依次经过：

1. 输入检测（_filter_text）：
   对抗归一化 → 关键词/正则/语义三层检测 → V2/V3 动作路由 →
   高风险直接拦截（不调模型）；中风险脱敏改写后重扫复检，
   复检不通过则升级为拦截。
2. 模型调用：只把脱敏后的消息（及可选的多轮历史）发给 LLM；
   调用失败返回安全的 llm_unavailable 兜底回复（Fail-Closed）。
3. 输出复检（_filter_output）：OutputGuard 对模型原文再次扫描，
   拦截或掩码改写后;才把最终文本返回给用户。

全程通过 EventLogger 分阶段写入脱敏审计事件（request_id 关联），
用户输入、模型原文、最终文本统一脱敏后落盘。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid
import warnings

from .action_router import ActionRouter
from .action_router_v3 import ActionRouterV3
from .llm_adapters import LLMAdapterFactory
from .llm_client import LLMClientError
from .logger import EventLogger
from .normalizer import TextNormalizer
from .output_guard import OutputGuard
from .rule_filter import RuleFilter
from .rule_manager import RuleManager
from .sanitizer import Sanitizer
from .semantic_config import (
    DEFAULT_PRODUCTION_CONFIG_PATH,
    build_semantic_classifier,
    load_semantic_runtime_configuration,
)


def _accepts_scored_kwarg(method) -> bool:
    import inspect

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "scored" or parameter.kind is parameter.VAR_KEYWORD
        for parameter in parameters
    )


MAX_HISTORY_TURNS = 20
VALID_HISTORY_ROLES = frozenset({"user", "assistant"})


class SafeChatPipeline:
    """安全检测主管线：组装归一化、规则、语义、路由、脱敏、LLM 与输出复检。

    所有组件在构造时一次性初始化；语义分类器缺失时自动降级（除非
    ``semantic.required=true`` 强制失败）；V2/V3 路由器加载失败同样
    降级并记录错误码（action_router_error_code / action_router_v3_error_code），
    由健康检查与 Fail-Closed 逻辑消费。
    """

    def __init__(self, config: dict, *, project_root: str | Path | None = None):
        self.config = config
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.package_root = Path(__file__).resolve().parent.parent
        # 归一化器：同音/Emoji 映射表位于包内 data/maps/
        self.normalizer = TextNormalizer(
            str(self.package_root / "data/maps/homophone_map.json"),
            str(self.package_root / "data/maps/emoji_map.json"),
        )
        self.rule_manager = RuleManager(RuleManager.default_path(self.project_root))
        self.rule_filter = RuleFilter(
            str(self.package_root / "data/lexicons"),
            str(self.package_root / "data/rules/regex_rules.json"),
            rule_manager=self.rule_manager,
        )
        semantic_options = config.get("semantic", {})
        semantic_config_path = semantic_options.get(
            "config_path", str(DEFAULT_PRODUCTION_CONFIG_PATH)
        )
        self.semantic_required = bool(semantic_options.get("required", False))
        runtime_configuration = load_semantic_runtime_configuration(
            self.project_root,
            semantic_config_path,
        )
        self.semantic_classifier = build_semantic_classifier(runtime_configuration)
        self.semantic_config_path = str(runtime_configuration.config_path)
        self.semantic_model_path = runtime_configuration.model_path
        semantic_status = self.semantic_classifier.status()
        if not semantic_status["loaded"]:
            message = (
                "semantic classifier unavailable: "
                f"{semantic_status['error']} "
                f"(model={runtime_configuration.model_path})"
            )
            if self.semantic_required:
                raise RuntimeError(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)

        self.sanitizer = Sanitizer()
        self.llm = LLMAdapterFactory.create(config.get("llm", {}))
        logging_config = config.get("logging", {})
        log_path = Path(logging_config.get("path", "data/logs/events.jsonl"))
        if not log_path.is_absolute():
            log_path = self.project_root / log_path
        self.logger = EventLogger(
            str(log_path),
            max_bytes=int(logging_config.get("max_bytes", 5 * 1024 * 1024)),
            backup_count=int(logging_config.get("backup_count", 5)),
            retention_days=int(logging_config.get("retention_days", 7)),
        )
        self.output_guard = OutputGuard(
            block_threshold=int(config["risk"].get("block_threshold", 80)),
            sanitize_threshold=int(config["risk"].get("sanitize_threshold", 40)),
        )
        self.action_router = None
        self.action_router_error_code = None
        try:
            self.action_router = ActionRouter(self._resolve_action_rules_path())
        except Exception as exc:
            self.action_router_error_code = "ROUTER_UNAVAILABLE"
            warnings.warn(
                f"action router unavailable: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        self.action_router_v3 = None
        self.action_router_v3_error_code = None
        action_v3_options = config.get("action_v3", {})
        self.action_router_v3_enabled = bool(
            action_v3_options.get("enabled", False)
        )
        if self.action_router_v3_enabled:
            try:
                self.action_router_v3 = ActionRouterV3.from_config(
                    self.project_root,
                    action_v3_options.get(
                        "threshold_config_path",
                        "config/action_thresholds_v3.json",
                    ),
                )
            except Exception as exc:
                self.action_router_v3_error_code = type(exc).__name__
                if bool(action_v3_options.get("required", False)):
                    raise RuntimeError("V3 action router unavailable") from exc
                warnings.warn(
                    "V3 action router unavailable; using V2 routing",
                    RuntimeWarning,
                    stacklevel=2,
                )

    @classmethod
    def from_config(cls, path: str):
        """从配置文件路径构建管线（配置解析以文件所在目录为项目根）。"""
        config_path = Path(path).resolve()
        with config_path.open("r", encoding="utf-8-sig") as file:
            return cls(json.load(file), project_root=config_path.parent)

    def handle_chat(
        self,
        message: str,
        raw_reply_override: str | None = None,
        persist: bool = True,
        history: list[dict[str, str]] | None = None,
    ) -> dict:
        """安全对话的唯一公共入口。

        参数：
            message: 用户本轮输入（将经过完整输入检测链路）；
            raw_reply_override: 跳过真实模型、直接指定模型原文（仅测试/演示用）；
            persist: 是否写入审计日志；
            history: 可选多轮对话历史（最多保留最近 MAX_HISTORY_TURNS 条），
                仅包含 user/assistant 消息；历史内容均为已通过双向检测的内容。

        返回包含 input_filter / output_filter / final_action /
        model_forwarded / request_id 等字段的完整结果字典。
        """
        started = time.perf_counter()
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if raw_reply_override is not None and not isinstance(raw_reply_override, str):
            raise TypeError("raw_reply_override must be a string or None")
        chat_history = self._normalize_history(history)
        try:
            llm_status = self.llm.status()
        except Exception as exc:
            warnings.warn(
                f"llm status check failed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            llm_status = {}
        audit_context = {
            "request_id": uuid.uuid4().hex,
            "provider": str(llm_status.get("provider") or "unknown"),
            "model": str(llm_status.get("model") or "unknown"),
        }

        input_result = self._filter_text(message, stage="input")
        self._write_event(
            {**audit_context, "stage": "input", "input": message, "result": input_result}, persist
        )
        if "USER_RULE_BLOCK" in input_result.get("reason_codes", []):
            input_result = dict(input_result)
            input_result["original_text"] = None
            input_result["normalized_text"] = None
            input_result["sanitized_text"] = None
        if input_result["action"] == "block":
            result = {
                "allowed": False,
                "reply": "\u62b1\u6b49\uff0c\u60a8\u7684\u8f93\u5165\u5305\u542b\u9ad8\u98ce\u9669\u5185\u5bb9\uff0c\u5df2\u62e6\u622a\u4e14\u672a\u8f6c\u53d1\u7ed9\u6a21\u578b\u3002",
                "safe_input": None,
                "raw_reply": None,
                "rewrite": {
                    "changed": bool(input_result.get("rewrite_called")),
                    "rewrite_text": input_result.get("sanitized_text"),
                },
                "input_filter": input_result,
                "output_filter": None,
            }
            result.update(
                self._pipeline_result_fields(
                    input_result,
                    model_forwarded=False,
                    model_response=None,
                    output_guard_action=None,
                    final_action="block",
                    final_allowed=False,
                    started=started,
                )
            )
            self._write_event(
                {**audit_context, "stage": "final", "action": "block", "reason": "input_block"},
                persist,
            )
            return self._complete_request(
                result,
                input_result,
                started=started,
                persist=persist,
                audit_context=audit_context,
            )

        safe_message = input_result.get("sanitized_text") or message
        rewrite = {
            "changed": safe_message != message,
            "rewrite_text": safe_message if safe_message != message else None,
        }
        model_forwarded = False
        try:
            if raw_reply_override is not None:
                raw_reply = raw_reply_override
            else:
                model_forwarded = True
                if chat_history:
                    request_messages = [
                        *chat_history,
                        {"role": "user", "content": safe_message},
                    ]
                    raw_reply = self.llm.chat(request_messages)
                else:
                    raw_reply = self.llm.chat(safe_message)
        except LLMClientError:
            input_result["model_forwarded"] = model_forwarded
            result = {
                "allowed": False,
                "reply": "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
                "safe_input": safe_message,
                "raw_reply": None,
                "rewrite": rewrite,
                "input_filter": input_result,
                "output_filter": None,
                "service_error": "llm_unavailable",
            }
            result.update(
                self._pipeline_result_fields(
                    input_result,
                    model_forwarded=model_forwarded,
                    model_response=None,
                    output_guard_action=None,
                    final_action="block",
                    final_allowed=False,
                    started=started,
                )
            )
            self._write_event(
                {
                    **audit_context,
                    "stage": "final",
                    "action": "service_error",
                    "reason": "llm_unavailable",
                },
                persist,
            )
            return self._complete_request(
                result,
                input_result,
                started=started,
                persist=persist,
                audit_context=audit_context,
            )

        output_result = self._filter_output(raw_reply)
        input_result["model_forwarded"] = model_forwarded
        self._write_event(
            {**audit_context, "stage": "output", "raw_reply": raw_reply, "result": output_result},
            persist,
        )
        final_reply = output_result["final_text"]
        output_risky = output_result["action"] != "pass"
        public_output_result = self._public_output_result(output_result)
        result = {
            "allowed": output_result["action"] != "block",
            "reply": final_reply,
            "safe_input": safe_message,
            "raw_reply": None if output_risky else raw_reply,
            "rewrite": rewrite,
            "input_filter": input_result,
            "output_filter": public_output_result,
        }
        result.update(
            self._pipeline_result_fields(
                input_result,
                model_forwarded=model_forwarded,
                model_response=None if output_risky else raw_reply,
                output_guard_action=output_result["action"],
                final_action=self._final_action(
                    input_result["action"], output_result["action"]
                ),
                final_allowed=output_result["action"] != "block",
                started=started,
            )
        )
        self._write_event(
            {
                **audit_context,
                "stage": "final",
                "action": result["final_action"],
                "allowed": result["allowed"],
                "final_reply": final_reply,
            },
            persist,
        )
        return self._complete_request(
            result,
            input_result,
            started=started,
            persist=persist,
            audit_context=audit_context,
        )

    def detect_text(self, text: str) -> dict:
        """仅执行输入检测链路（不调用模型），供 /api/detect 与评测使用。"""
        return self._filter_text(text, stage="detect")

    def _normalize_history(
        self,
        history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        """校验、截断并做基础安全扫描的对话历史。

        规则：只能是 user/assistant 消息；内容必须是非空字符串；
        超过 MAX_HISTORY_TURNS 条时只保留最近的记录。
        user 消息额外经过归一化 + 规则层扫描：命中已知危险规则的
        历史条目会被移除，防止旧版本会话文件中的不安全内容
        通过 history 路径绕过当前输入检测直接进入模型。
        不合法条目直接抛 ValueError（API 层映射为 422）。
        """
        if history is None:
            return []
        if not isinstance(history, list):
            raise ValueError("history must be a list of message objects")
        if len(history) > MAX_HISTORY_TURNS:
            history = history[-MAX_HISTORY_TURNS:]
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                raise ValueError(f"history item {index} must be an object")
            role = item.get("role")
            content = item.get("content")
            if role not in VALID_HISTORY_ROLES:
                raise ValueError(
                    f"history item {index} role must be 'user' or 'assistant'"
                )
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"history item {index} content must be a non-empty string")
            normalized.append({"role": role, "content": content})
        safe: list[dict[str, str]] = []
        for item in normalized:
            if item["role"] != "user":
                safe.append(item)
                continue
            normalized_text = self.normalizer.normalize(item["content"])
            detections = self.rule_filter.detect(normalized_text)
            if not detections:
                safe.append(item)
        return safe

    def _scan_text(self, text: str) -> tuple[str, list]:
        """便捷扫描：三层扫描后返回 (归一化文本, 去重后的全部命中)。"""
        normalized, rule_detections, semantic_detections, _semantic_scores = (
            self._scan_text_layers(text)
        )
        return normalized, self._deduplicate_detections(
            [*rule_detections, *semantic_detections]
        )

    def _scan_text_layers(
        self, text: str
    ) -> tuple[str, list, list, dict | None]:
        """单文本三层扫描：归一化 → 规则检测 → 语义检测。

        返回 (归一化文本, 规则命中列表, 语义命中列表, 语义分数详情)。
        语义分数详情（score_text 的原始输出）随检测结果一起返回，
        供决策解释服务消费，避免解释阶段重复推理。
        对缺少 score_text 接口的测试替身自动降级为只调 detect()。
        """
        view_builder = getattr(self.normalizer, "normalize_views", None)
        if callable(view_builder):
            views = view_builder(text)
            normalized = views.normalized_text
            adversarial = views.adversarial_text or normalized
        else:
            normalized = self.normalizer.normalize(text)
            adversarial = normalized
        rule_detections = self.rule_filter.detect(adversarial)
        score_reader = getattr(self.semantic_classifier, "score_text", None)
        if callable(score_reader):
            semantic_scores = score_reader(normalized)
        else:
            semantic_scores = None
        detect_method = self.semantic_classifier.detect
        if semantic_scores is not None and _accepts_scored_kwarg(detect_method):
            semantic_detections = detect_method(
                normalized, scored=semantic_scores
            )
        else:
            semantic_detections = detect_method(normalized)
        return normalized, rule_detections, semantic_detections, semantic_scores

    def _filter_output(self, text: str) -> dict:
        """输出侧复检：OutputGuard 扫描 + 改写后再复检。

        sanitize 改写完成后会对改写文本再跑一次完整扫描与 OutputGuard，
        若复检仍有风险则升级为拦截并返回类别化拒绝话术。
        """
        if not isinstance(text, str):
            raise TypeError("output text must be a string")
        normalized, detections = self._scan_text(text)
        result = self.output_guard.process(text, normalized, detections)
        if result["action"] != "sanitize":
            result["rewrite_recheck"] = None
            return result

        rewritten = result["final_text"]
        re_normalized, re_detections = self._scan_text(rewritten)
        rechecked = self.output_guard.process(rewritten, re_normalized, re_detections)
        result["rewrite_recheck"] = {
            "normalized_text": re_normalized,
            "action": rechecked["action"],
            "detections": rechecked["detections"],
        }
        if rechecked["action"] != "pass":
            categories = sorted(
                set(result.get("risk_categories", []))
                | set(rechecked.get("risk_categories", []))
            )
            refusal = self.output_guard._refusal(categories)
            result.update(
                {
                    "action": "block",
                    "blocked": True,
                    "rewritten": True,
                    "risk_level": "high",
                    "risk_categories": categories,
                    "final_text": refusal,
                    "sanitized_text": refusal,
                }
            )
        return result

    def _filter_text(self, text: str, stage: str) -> dict:
        """输入侧完整检测链路（含脱敏改写与复检）。

        流程：三层扫描 → 动作路由 → 显式硬拦升级 →
        若动作为 sanitize：脱敏改写（改写失败/为空/无变化都安全降级为 block），
        改写成功后对新文本重扫+重路由复检，复检 pass 才放行改写文本。
        返回的字典会进入审计日志（敏感字段由 logger 统一脱敏）。
        """
        started = time.perf_counter()
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized, rule_detections, semantic_detections, semantic_scores = (
            self._scan_text_layers(text)
        )
        detections = self._deduplicate_detections(
            [*rule_detections, *semantic_detections]
        )
        routed, fallback_used = self._route_input_all_versions(
            text,
            normalized,
            rule_detections,
            semantic_detections,
        )
        action = routed["action"]
        category = routed["category"]
        risk_level = routed["risk_level"]
        risk_score = routed["risk_score"]
        reason_codes = list(routed["reason_codes"])
        hard_block = bool(routed["hard_block"])
        if self._is_explicit_legacy_hard_block(routed, rule_detections):
            action = "block"
            hard_block = True
            risk_level = "high"
            risk_score = max(
                risk_score,
                max(detection.score for detection in rule_detections),
            )
            reason_codes.append("LEGACY_EXPLICIT_HARD_BLOCK")
        sanitized = None
        rewrite_called = False
        rewrite_changed = False
        rewrite_recheck = None
        recheck_action = None

        if action == "sanitize":
            rewrite_called = True
            matches = list(routed.get("sanitize_matches", []))
            matches.extend(
                match
                for detection in rule_detections
                for match in detection.matches
                if match and match in normalized
            )
            try:
                rewritten = self.sanitizer.sanitize(normalized, matches)
            except Exception:
                action = "block"
                risk_level = "high"
                risk_score = max(risk_score, 60)
                reason_codes.append("SANITIZER_ERROR")
            else:
                if not isinstance(rewritten, str) or not rewritten.strip():
                    action = "block"
                    risk_level = "high"
                    risk_score = max(risk_score, 60)
                    reason_codes.append("SANITIZER_EMPTY")
                elif rewritten == normalized:
                    action = "block"
                    risk_level = "high"
                    risk_score = max(risk_score, 60)
                    reason_codes.append("SANITIZER_UNCHANGED")
                    rewrite_recheck = {
                        "normalized_text": normalized,
                        "action": "block",
                        "category": category,
                        "risk_level": "high",
                        "risk_score": risk_score,
                        "reason_codes": ["SANITIZER_UNCHANGED"],
                        "hard_block": False,
                        "fallback_used": False,
                        "detections": self._serialize_detections(detections),
                    }
                else:
                    rewrite_changed = True
                    if "，" in text and "," not in text:
                        rewritten = rewritten.replace(",", "，")
                    try:
                        (
                            re_normalized,
                            re_rule_detections,
                            re_semantic_detections,
                            _re_semantic_scores,
                        ) = self._scan_text_layers(rewritten)
                        re_detections = self._deduplicate_detections(
                            [*re_rule_detections, *re_semantic_detections]
                        )
                        re_routed, re_fallback = self._route_input_all_versions(
                            rewritten,
                            re_normalized,
                            re_rule_detections,
                            re_semantic_detections,
                        )
                        fallback_used = fallback_used or re_fallback
                        recheck_action = re_routed["action"]
                        rewrite_recheck = {
                            "normalized_text": re_normalized,
                            "action": recheck_action,
                            "category": re_routed["category"],
                            "risk_level": re_routed["risk_level"],
                            "risk_score": re_routed["risk_score"],
                            "reason_codes": re_routed["reason_codes"],
                            "hard_block": re_routed["hard_block"],
                            "fallback_used": re_fallback,
                            "detections": self._serialize_detections(re_detections),
                        }
                    except Exception:
                        re_fallback = True
                        fallback_used = True
                        recheck_action = "block"
                        rewrite_recheck = {
                            "normalized_text": None,
                            "action": "block",
                            "category": category,
                            "risk_level": "high",
                            "risk_score": max(risk_score, 60),
                            "reason_codes": ["RECHECK_ERROR"],
                            "hard_block": False,
                            "fallback_used": True,
                            "detections": [],
                        }

                    if re_fallback:
                        action = "block"
                        risk_level = "high"
                        risk_score = max(risk_score, 60)
                        reason_codes.append("RECHECK_ROUTER_ERROR")
                    elif recheck_action == "pass":
                        sanitized = rewritten
                    else:
                        action = "block"
                        hard_block = bool(re_routed["hard_block"])
                        risk_level = "high"
                        risk_score = max(risk_score, re_routed["risk_score"])
                        reason_codes.extend(
                            [
                                f"REWRITE_RECHECK_{recheck_action.upper()}",
                                *re_routed["reason_codes"],
                            ]
                        )

        categories = sorted(
            {d.category for d in detections}
            | ({category} if category != "normal" else set())
        )
        return {
            "stage": stage,
            "original_text": (
                None if "USER_RULE_BLOCK" in reason_codes else text
            ),
            "normalized_text": (
                None if "USER_RULE_BLOCK" in reason_codes else normalized
            ),
            "action": action,
            "category": category,
            "risk_score": int(risk_score),
            "risk_level": risk_level,
            "risk_categories": categories,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "hard_block": hard_block,
            "confidence": routed.get("confidence", 0.0),
            "matched_rule_ids": list(routed.get("matched_rule_ids", [])),
            "sanitized_text": sanitized,
            "rewrite_called": rewrite_called,
            "rewrite_changed": rewrite_changed,
            "recheck_action": recheck_action,
            "rewrite_recheck": rewrite_recheck,
            "detections": self._serialize_detections(detections),
            "semantic_explanation": semantic_scores,
            "semantic_model_status": self._semantic_model_status(),
            "fallback_used": fallback_used,
            "model_forwarded": False,
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        }

    def _route_input_all_versions(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list,
        semantic_detections: list,
    ) -> tuple[dict, bool]:
        """动作路由总入口：V2 路由为基础，V3 启用时做证据增强叠加。

        返回 (路由结果, 是否使用了降级路径)。V3 路由异常时：
        required=true 返回 Fail-Closed 拦截结果；否则回退 V2 结果。
        """
        routed, fallback_used = self._route_with_user_overlay_guard(
            original_text,
            normalized_text,
            rule_detections,
            semantic_detections,
        )
        if self.action_router_v3 is None:
            return routed, fallback_used
        try:
            return (
                self.action_router_v3.route(
                    original_text,
                    normalized_text,
                    category_hint=routed.get("category", "normal"),
                    base_result=routed,
                ),
                fallback_used,
            )
        except Exception:
            if bool(self.config.get("action_v3", {}).get("required", False)):
                return self._router_failure_result(
                    rule_detections,
                    semantic_detections,
                    "ACTION_V3_ROUTER_ERROR",
                ), True
            return routed, fallback_used

    def route_input(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list,
        semantic_detections: list,
    ) -> tuple[dict, bool]:
        """动作路由公共接口：供评测模块等外部调用方使用。

        返回 (路由结果 dict, 是否使用了降级路径)。
        """
        return self._route_input_all_versions(
            original_text, normalized_text, rule_detections, semantic_detections
        )

    def _route_with_user_overlay_guard(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list,
        semantic_detections: list,
    ) -> tuple[dict, bool]:
        """用户可信 block 规则前置守卫。

        命中用户 overlay 的 block 规则时，直接生成硬拦截结果
        （reason_codes=USER_RULE_BLOCK），不进入 ActionRouter 重新评估——
        用户显式配置的拦截规则优先级最高，语义分数无法降级它。
        其余情况交给 _route_input 正常路由。
        """
        metadata_reader = getattr(self.rule_filter, "user_overlay_metadata", None)
        if not callable(metadata_reader):
            return self._route_input(
                original_text,
                normalized_text,
                rule_detections,
                semantic_detections,
            )
        trusted_blocks = []
        for detection in rule_detections:
            metadata = metadata_reader(detection)
            if metadata and metadata["configured_action"] == "block":
                trusted_blocks.append((detection, metadata))
        if not trusted_blocks:
            return self._route_input(
                original_text,
                normalized_text,
                rule_detections,
                semantic_detections,
            )

        selected, _ = max(trusted_blocks, key=lambda item: item[0].score)
        rule_ids = sorted({metadata["rule_id"] for _, metadata in trusted_blocks})
        return (
            {
                "action": "block",
                "category": selected.category,
                "risk_level": selected.level,
                "confidence": 1.0,
                "reason_codes": ["USER_RULE_BLOCK"],
                "hard_block": True,
                "risk_score": int(selected.score),
                "matched_rule_ids": rule_ids,
                "sanitize_matches": [],
                "evidence": [],
            },
            False,
        )

    def _serialize_detections(self, detections: list) -> list[dict]:
        """把 Detection 对象序列化为可入库的字典；用户 overlay 命中词脱敏。"""
        serialized = []
        overlay_checker = getattr(self.rule_filter, "is_user_overlay_detection", None)
        for detection in detections:
            public = dict(detection.__dict__)
            if callable(overlay_checker) and overlay_checker(detection):
                public["matches"] = ["[REDACTED]"] if detection.matches else []
            serialized.append(public)
        return serialized
    def _is_explicit_legacy_hard_block(
        self,
        routed: dict,
        rule_detections: list,
    ) -> bool:
        """V2 时代的显式硬拦兼容判定。

        当路由动作为 sanitize，但存在关键词/正则来源、分数达到 block 阈值的
        高危命中（且不是语义证据触发）时，升级为硬拦截——保证历史版本中
        "高分关键词必须拦"的语义在 V3 叠加下不被削弱。
        """
        return (
            routed["action"] == "sanitize"
            and "SEMANTIC_RISK_EVIDENCE" not in routed.get("reason_codes", [])
            and any(
                detection.source in {"keyword", "regex"}
                and detection.level == "high"
                and detection.score
                >= int(self.config["risk"].get("block_threshold", 80))
                for detection in rule_detections
            )
        )
    def _route_input(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list,
        semantic_detections: list,
    ) -> tuple[dict, bool]:
        if self.action_router is None:
            return (
                self._router_failure_result(
                    rule_detections,
                    semantic_detections,
                    self.action_router_error_code or "ROUTER_UNAVAILABLE",
                ),
                True,
            )
        try:
            return (
                self.action_router.route(
                    original_text,
                    normalized_text,
                    rule_detections,
                    semantic_detections,
                ),
                False,
            )
        except Exception:
            return (
                self._router_failure_result(
                    rule_detections,
                    semantic_detections,
                    "ROUTER_ERROR",
                ),
                True,
            )

    def _router_failure_result(
        self,
        rule_detections: list,
        semantic_detections: list,
        reason_code: str,
    ) -> dict:
        """路由器不可用时的 Fail-Closed 决策。

        依据剩余证据保守决策：
        - 无任何命中且语义模型也不可用 → 拦截（无法证明安全）；
        - 无任何命中但语义可用 → 放行（有模型背书）；
        - 有命中 → 以最高分命中拦截，显式高危规则命中标记 hard_block。
        """
        detections = [*rule_detections, *semantic_detections]
        if not detections:
            semantic_available = self._semantic_model_status() == "loaded"
            if not semantic_available:
                return {
                    "action": "block",
                    "category": "normal",
                    "risk_level": "high",
                    "confidence": 0.0,
                    "reason_codes": [
                        reason_code,
                        "ROUTER_AND_SEMANTIC_UNAVAILABLE",
                    ],
                    "hard_block": False,
                    "risk_score": 60,
                    "matched_rule_ids": [],
                    "sanitize_matches": [],
                }
            return {
                "action": "pass",
                "category": "normal",
                "risk_level": "none",
                "confidence": 0.0,
                "reason_codes": [reason_code, "NO_DETECTION_EVIDENCE"],
                "hard_block": False,
                "risk_score": 0,
                "matched_rule_ids": [],
                "sanitize_matches": [],
            }
        selected = max(detections, key=lambda detection: detection.score)
        explicit_rule_block = any(
            detection.source in {"keyword", "regex"}
            and detection.level == "high"
            and detection.score
            >= int(self.config["risk"].get("block_threshold", 80))
            for detection in rule_detections
        )
        return {
            "action": "block",
            "category": selected.category,
            "risk_level": "high",
            "confidence": 0.0,
            "reason_codes": [reason_code, "DETECTION_EVIDENCE_FAIL_CLOSED"],
            "hard_block": explicit_rule_block,
            "risk_score": max(int(selected.score), 60),
            "matched_rule_ids": [],
            "sanitize_matches": [],
        }

    def _resolve_action_rules_path(self) -> Path:
        """解析 V2 路由规则文件路径（配置可覆盖，默认包内 config/action_rules_v1.json）。"""
        configured = self.config.get("action_router", {}).get("rules_path")
        if configured:
            path = Path(configured)
            return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()
        return (self.package_root / "config/action_rules_v1.json").resolve()

    def _semantic_model_status(self) -> str:
        """语义模型状态摘要：loaded / unavailable。"""
        status = self.semantic_classifier.status()
        return "loaded" if status.get("loaded") else "unavailable"

    @staticmethod
    def _pipeline_result_fields(
        input_result: dict,
        *,
        model_forwarded: bool,
        model_response: str | None,
        output_guard_action: str | None,
        final_action: str,
        final_allowed: bool,
        started: float,
    ) -> dict:
        """构造对外的公共结果字段（各分支结果 dict 的公共投影 + 耗时统计）。"""
        return {
            "action": input_result["action"],
            "final_action": final_action,
            "final_allowed": final_allowed,
            "category": input_result["category"],
            "risk_level": input_result["risk_level"],
            "risk_score": input_result["risk_score"],
            "reason_codes": input_result["reason_codes"],
            "hard_block": input_result["hard_block"],
            "normalized_text": input_result["normalized_text"],
            "sanitized_text": input_result.get("sanitized_text"),
            "model_forwarded": model_forwarded,
            "model_response": model_response,
            "output_guard_action": output_guard_action,
            "semantic_model_status": input_result["semantic_model_status"],
            "fallback_used": input_result["fallback_used"],
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        }

    @staticmethod
    def _final_action(input_action: str, output_action: str | None) -> str:
        """汇总输入/输出两侧动作为最终动作：任一侧更严格则取更严格者。"""
        if input_action == "block" or output_action == "block":
            return "block"
        if input_action == "sanitize" or output_action == "sanitize":
            return "sanitize"
        return "pass"

    def _complete_request(
        self,
        result: dict,
        input_result: dict,
        *,
        started: float,
        persist: bool,
        audit_context: dict,
    ) -> dict:
        """请求收尾：补齐公共字段并写入 request_summary 汇总审计事件。

        request_summary 是统计服务（stats/daily_stats/管理页总览）的
        唯一数据源：每条持久化请求恰好对应一条汇总，包含最终动作、
        风险类别/等级/分数、是否调模型、是否脱敏、耗时等聚合字段。
        """
        result["latency_ms"] = max(
            0, round((time.perf_counter() - started) * 1000)
        )
        result["request_id"] = audit_context["request_id"]
        result["provider"] = audit_context["provider"]
        result["model"] = audit_context["model"]
        output_filter = result.get("output_filter") or {}
        output_action = result.get("output_guard_action") or "not_run"
        category = result["category"]
        risk_level = result["risk_level"]
        risk_score = result["risk_score"]
        if output_action in {"sanitize", "block"}:
            output_categories = output_filter.get("risk_categories") or []
            if output_categories:
                category = sorted(output_categories)[0]
            risk_level = output_filter.get("risk_level", risk_level)
            risk_score = max(risk_score, int(output_filter.get("risk_score", 0)))
        input_sanitize = bool(input_result.get("rewrite_called"))
        input_changed = bool(input_result.get("rewrite_changed"))
        output_sanitize = output_action == "sanitize"
        output_changed = bool(output_filter.get("rewritten"))

        self._write_event(
            {
                **audit_context,
                "stage": "request_summary",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_action": input_result["action"],
                "output_action": output_action,
                "final_action": result["final_action"],
                "final_allowed": result["final_allowed"],
                "category": category,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "model_forwarded": result["model_forwarded"],
                "sanitize_applied": input_sanitize or output_sanitize,
                "sanitize_changed": input_changed or output_changed,
                "fallback_used": result["fallback_used"],
                "semantic_model_status": result["semantic_model_status"],
                "latency_ms": result["latency_ms"],
            },
            persist,
        )
        return result

    def stats(
        self,
        since: datetime | None = None,
        *,
        portable_paths: bool = False,
    ) -> dict:
        """聚合日志统计并附加语义模型与 LLM 运行状态（管理页数据源）。"""
        stats = self.logger.stats(since=since)
        semantic_status = dict(self.semantic_classifier.status())
        semantic_status["required"] = self.semantic_required
        semantic_status["config_path"] = self.semantic_config_path
        if portable_paths:
            semantic_status["config_path"] = self._portable_path(self.semantic_config_path)
            semantic_status["model_path"] = self.semantic_model_path
        stats["semantic_classifier"] = semantic_status
        stats["model_loaded"] = semantic_status.get("loaded", False)
        stats["model_error"] = semantic_status.get("error")
        stats["llm"] = self.llm.status()
        return stats

    @staticmethod
    def _public_output_result(result: dict) -> dict:
        """输出结果的对外投影：pass 原样返回；有风险时原文相关字段全部置空、
        命中词脱敏为 [REDACTED]，确保风险原文不离开服务端。"""
        if result.get("action") == "pass":
            return result
        public = dict(result)
        for field in ("original_text", "normalized_text", "sanitized_raw_output"):
            public[field] = None
        public["matched_rules"] = [
            {**rule, "match": "[REDACTED]"}
            for rule in result.get("matched_rules", [])
        ]
        public["detections"] = [
            {**detection, "matches": ["[REDACTED]"] if detection.get("matches") else []}
            for detection in result.get("detections", [])
        ]
        return public

    def _portable_path(self, value: str) -> str:
        """把绝对路径转为相对项目根的可移植路径（日志/对外展示用）。"""
        path = Path(value)
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return path.name

    def _write_event(self, event: dict, persist: bool) -> None:
        """写入一条审计事件；写失败只告警不中断主流程（不改变安全响应）。"""
        if persist:
            try:
                self.logger.write(event)
            except Exception as exc:
                warnings.warn(
                    f"audit event could not be persisted: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )

    @staticmethod
    def _deduplicate_detections(detections: list) -> list:
        """按 (类别, 来源, 命中词组) 去重，保留首次出现的检测。"""
        unique = []
        seen = set()
        for detection in detections:
            key = (detection.category, detection.source, tuple(detection.matches))
            if key not in seen:
                seen.add(key)
                unique.append(detection)
        return unique

    @staticmethod
    def deduplicate_detections(detections: list) -> list:
        """按 (类别, 来源, 命中词组) 去重，保留首次出现的检测（公共接口）。"""
        return SafeChatPipeline._deduplicate_detections(detections)

    def serialize_detections(self, detections: list) -> list[dict]:
        """将 Detection 对象序列化为可入库的字典（公共接口，含用户 overlay 脱敏）。"""
        return self._serialize_detections(detections)
