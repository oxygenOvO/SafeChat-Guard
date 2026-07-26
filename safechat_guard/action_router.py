from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Detection


ALLOWED_CATEGORIES = ("normal", "ad", "porn", "violence", "sensitive")
RISK_CATEGORIES = frozenset(ALLOWED_CATEGORIES) - {"normal"}
_RULE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NEGATION_WINDOW = 10


@dataclass(frozen=True)
class _RuleFamily:
    rule_id: str
    category: str
    object_terms: tuple[str, ...]
    implementation_terms: tuple[str, ...]
    confidence: float
    risk_score: int


@dataclass(frozen=True)
class _SafetyContext:
    rule_id: str
    terms: tuple[str, ...]


class ActionRouter:
    """Map rule and semantic evidence to a stable safety action.

    A hard block requires a configured risk object and a non-negated
    implementation signal. Detector scores can strengthen confidence but never
    create a hard block by themselves.
    """

    def __init__(self, rules_path: str | Path):
        self.rules_path = Path(rules_path)
        payload = self._load_payload(self.rules_path)
        (
            self.negation_terms,
            self.safety_contexts,
            self.unsafe_override_terms,
            self.rule_families,
        ) = self._validate_payload(payload)

    def route(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list[Detection],
        semantic_detections: list[Detection],
    ) -> dict[str, Any]:
        if not isinstance(original_text, str) or not isinstance(normalized_text, str):
            raise TypeError("original_text and normalized_text must be strings")
        self._validate_detections(rule_detections, "rule_detections")
        self._validate_detections(semantic_detections, "semantic_detections")

        texts = tuple(
            dict.fromkeys(
                (
                    self._canonicalize(original_text),
                    self._canonicalize(normalized_text),
                )
            )
        )
        safe_context_ids = self._matched_safety_contexts(texts)
        unsafe_override = self._matched_terms(texts, self.unsafe_override_terms)
        family_matches = self._match_families(texts)
        effective_hard_matches = family_matches
        if safe_context_ids and not unsafe_override:
            effective_hard_matches = []

        rule_categories = self._detection_categories(rule_detections)
        semantic_categories = self._detection_categories(semantic_detections)
        agreement = sorted(set(rule_categories) & set(semantic_categories))
        conflict = bool(
            rule_categories
            and semantic_categories
            and not agreement
        )

        if effective_hard_matches:
            selected = effective_hard_matches[0]
            reason_codes = ["COMPOUND_RULE_MATCH"]
            if agreement:
                reason_codes.append("RULE_SEMANTIC_AGREEMENT")
            elif conflict:
                reason_codes.append("RULE_SEMANTIC_CONFLICT")
            confidence = selected["family"].confidence
            if selected["family"].category in agreement:
                confidence = min(confidence + 0.02, 0.99)
            return self._result(
                action="block",
                category=selected["family"].category,
                risk_level="high",
                confidence=confidence,
                reason_codes=reason_codes,
                hard_block=True,
                risk_score=selected["family"].risk_score,
                matched_rule_ids=[
                    item["family"].rule_id for item in effective_hard_matches
                ],
                sanitize_matches=[],
            )

        if safe_context_ids:
            reason_codes = ["SAFE_CONTEXT"]
            if family_matches:
                reason_codes.append("NON_REAL_WORLD_MENTION")
            if rule_categories or semantic_categories:
                reason_codes.append("DETECTOR_EVIDENCE_SUPPRESSED")
            return self._result(
                action="pass",
                category="normal",
                risk_level="none",
                confidence=0.95,
                reason_codes=reason_codes,
                hard_block=False,
                risk_score=0,
                matched_rule_ids=safe_context_ids,
                sanitize_matches=[],
            )

        object_matches = self._object_only_matches(texts)
        if rule_categories or semantic_categories or object_matches:
            category = self._select_risk_category(
                rule_detections,
                semantic_detections,
                object_matches,
            )
            reason_codes = []
            if rule_categories:
                reason_codes.append("RULE_RISK_EVIDENCE")
            if semantic_categories:
                reason_codes.append("SEMANTIC_RISK_EVIDENCE")
            if object_matches:
                reason_codes.append("RISK_OBJECT_MENTION")
            if agreement:
                reason_codes.append("RULE_SEMANTIC_AGREEMENT")
            elif conflict:
                reason_codes.append("RULE_SEMANTIC_CONFLICT")
            confidence = self._sanitize_confidence(
                category,
                rule_detections,
                semantic_detections,
                bool(object_matches),
                bool(agreement),
            )
            return self._result(
                action="sanitize",
                category=category,
                risk_level="medium",
                confidence=confidence,
                reason_codes=reason_codes,
                hard_block=False,
                risk_score=round(confidence * 100),
                matched_rule_ids=[
                    item["family"].rule_id for item in object_matches
                ],
                sanitize_matches=self._safe_sanitize_matches(object_matches),
            )

        return self._result(
            action="pass",
            category="normal",
            risk_level="none",
            confidence=0.98,
            reason_codes=["NO_RISK_EVIDENCE"],
            hard_block=False,
            risk_score=0,
            matched_rule_ids=[],
            sanitize_matches=[],
        )

    @staticmethod
    def _load_payload(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"action rules file not found: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid action rules JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError("action rules root must be an object")
        return payload

    @classmethod
    def _validate_payload(
        cls,
        payload: dict[str, Any],
    ) -> tuple[
        tuple[str, ...],
        tuple[_SafetyContext, ...],
        tuple[str, ...],
        tuple[_RuleFamily, ...],
    ]:
        expected = {
            "schema_version",
            "negation_terms",
            "safety_contexts",
            "unsafe_override_terms",
            "rule_families",
        }
        if set(payload) != expected:
            raise ValueError(
                "action rules fields do not match schema: "
                f"expected={sorted(expected)}, actual={sorted(payload)}"
            )
        if payload["schema_version"] != 1:
            raise ValueError("unsupported action rules schema_version")

        negation_terms = cls._validate_terms(
            payload["negation_terms"], "negation_terms"
        )
        unsafe_override_terms = cls._validate_terms(
            payload["unsafe_override_terms"], "unsafe_override_terms"
        )

        raw_contexts = payload["safety_contexts"]
        if not isinstance(raw_contexts, list) or not raw_contexts:
            raise ValueError("safety_contexts must be a non-empty list")
        contexts: list[_SafetyContext] = []
        ids: set[str] = set()
        for raw in raw_contexts:
            if not isinstance(raw, dict) or set(raw) != {"id", "terms"}:
                raise ValueError("each safety context must define id and terms")
            rule_id = cls._validate_rule_id(raw["id"], ids)
            contexts.append(
                _SafetyContext(
                    rule_id=rule_id,
                    terms=cls._validate_terms(raw["terms"], f"{rule_id}.terms"),
                )
            )

        raw_families = payload["rule_families"]
        if not isinstance(raw_families, list) or not raw_families:
            raise ValueError("rule_families must be a non-empty list")
        families: list[_RuleFamily] = []
        for raw in raw_families:
            expected_family_fields = {
                "id",
                "category",
                "object_terms",
                "implementation_terms",
                "confidence",
                "risk_score",
            }
            if not isinstance(raw, dict) or set(raw) != expected_family_fields:
                raise ValueError(
                    "each rule family must define exactly "
                    f"{sorted(expected_family_fields)}"
                )
            rule_id = cls._validate_rule_id(raw["id"], ids)
            category = raw["category"]
            if category not in RISK_CATEGORIES:
                raise ValueError(f"{rule_id}.category must be a risk category")
            confidence = float(raw["confidence"])
            risk_score = int(raw["risk_score"])
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"{rule_id}.confidence must be between 0 and 1")
            if not 0 <= risk_score <= 100:
                raise ValueError(f"{rule_id}.risk_score must be between 0 and 100")
            families.append(
                _RuleFamily(
                    rule_id=rule_id,
                    category=category,
                    object_terms=cls._validate_terms(
                        raw["object_terms"], f"{rule_id}.object_terms"
                    ),
                    implementation_terms=cls._validate_terms(
                        raw["implementation_terms"],
                        f"{rule_id}.implementation_terms",
                    ),
                    confidence=confidence,
                    risk_score=risk_score,
                )
            )
        return (
            negation_terms,
            tuple(contexts),
            unsafe_override_terms,
            tuple(families),
        )

    @staticmethod
    def _validate_rule_id(value: Any, seen: set[str]) -> str:
        if not isinstance(value, str) or not _RULE_ID_PATTERN.fullmatch(value):
            raise ValueError(f"invalid stable rule id: {value!r}")
        if value in seen:
            raise ValueError(f"duplicate rule id: {value}")
        seen.add(value)
        return value

    @staticmethod
    def _validate_terms(value: Any, field: str) -> tuple[str, ...]:
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(term, str) or not term.strip() for term in value)
        ):
            raise ValueError(f"{field} must be a non-empty list of strings")
        canonical = tuple(
            dict.fromkeys(ActionRouter._canonicalize(term) for term in value)
        )
        if len(canonical) != len(value):
            raise ValueError(f"{field} contains duplicate terms")
        return canonical

    @staticmethod
    def _validate_detections(detections: list[Detection], field: str) -> None:
        if not isinstance(detections, list) or any(
            not isinstance(item, Detection) for item in detections
        ):
            raise TypeError(f"{field} must be a list of Detection")

    @staticmethod
    def _canonicalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text).casefold()

    def _matched_safety_contexts(self, texts: tuple[str, ...]) -> list[str]:
        return [
            context.rule_id
            for context in self.safety_contexts
            if self._matched_terms(texts, context.terms)
        ]

    @staticmethod
    def _matched_terms(
        texts: tuple[str, ...],
        terms: tuple[str, ...],
    ) -> list[str]:
        return [
            term
            for term in terms
            if any(term in text for text in texts)
        ]

    def _non_negated_matches(
        self,
        texts: tuple[str, ...],
        terms: tuple[str, ...],
    ) -> list[str]:
        matches: list[str] = []
        for term in terms:
            accepted = False
            for text in texts:
                start = 0
                while True:
                    index = text.find(term, start)
                    if index < 0:
                        break
                    prefix = text[max(0, index - _NEGATION_WINDOW):index]
                    if not any(negation in prefix for negation in self.negation_terms):
                        accepted = True
                        break
                    start = index + max(len(term), 1)
                if accepted:
                    break
            if accepted:
                matches.append(term)
        return matches

    def _match_families(self, texts: tuple[str, ...]) -> list[dict[str, Any]]:
        matches = []
        for family in self.rule_families:
            object_terms = self._matched_terms(texts, family.object_terms)
            implementation_terms = self._non_negated_matches(
                texts, family.implementation_terms
            )
            if object_terms and implementation_terms:
                matches.append(
                    {
                        "family": family,
                        "object_terms": object_terms,
                        "implementation_terms": implementation_terms,
                    }
                )
        return matches

    def _object_only_matches(self, texts: tuple[str, ...]) -> list[dict[str, Any]]:
        matches = []
        for family in self.rule_families:
            object_terms = self._matched_terms(texts, family.object_terms)
            if object_terms:
                matches.append({"family": family, "object_terms": object_terms})
        return matches

    @staticmethod
    def _detection_categories(detections: list[Detection]) -> list[str]:
        return [
            category
            for category in dict.fromkeys(
                detection.category
                for detection in detections
                if detection.category in RISK_CATEGORIES
            )
        ]

    @staticmethod
    def _select_risk_category(
        rule_detections: list[Detection],
        semantic_detections: list[Detection],
        object_matches: list[dict[str, Any]],
    ) -> str:
        category_order = {category: index for index, category in enumerate(ALLOWED_CATEGORIES)}
        for detections in (rule_detections, semantic_detections):
            eligible = [
                detection
                for detection in detections
                if detection.category in RISK_CATEGORIES
            ]
            if eligible:
                return sorted(
                    eligible,
                    key=lambda item: (
                        -int(item.score),
                        category_order[item.category],
                        item.source,
                    ),
                )[0].category
        return object_matches[0]["family"].category

    @staticmethod
    def _sanitize_confidence(
        category: str,
        rule_detections: list[Detection],
        semantic_detections: list[Detection],
        has_object_match: bool,
        has_agreement: bool,
    ) -> float:
        evidence_scores = [
            max(0, min(int(item.score), 100)) / 100
            for item in [*rule_detections, *semantic_detections]
            if item.category == category
        ]
        confidence = max(evidence_scores, default=0.60 if has_object_match else 0.55)
        confidence = min(max(confidence, 0.55), 0.79)
        if has_object_match:
            confidence = max(confidence, 0.65)
        if has_agreement:
            confidence = min(confidence + 0.05, 0.84)
        return round(confidence, 4)

    @staticmethod
    def _safe_sanitize_matches(
        object_matches: list[dict[str, Any]],
    ) -> list[str]:
        return list(
            dict.fromkeys(
                term
                for match in object_matches
                for term in match["object_terms"]
            )
        )

    @staticmethod
    def _result(**values: Any) -> dict[str, Any]:
        result = {
            "action": values["action"],
            "category": values["category"],
            "risk_level": values["risk_level"],
            "confidence": round(float(values["confidence"]), 4),
            "reason_codes": list(dict.fromkeys(values["reason_codes"])),
            "hard_block": bool(values["hard_block"]),
            "risk_score": int(values["risk_score"]),
            "matched_rule_ids": list(dict.fromkeys(values["matched_rule_ids"])),
            "sanitize_matches": list(dict.fromkeys(values["sanitize_matches"])),
        }
        if not 0.0 <= result["confidence"] <= 1.0:
            raise AssertionError("router confidence escaped valid range")
        if not 0 <= result["risk_score"] <= 100:
            raise AssertionError("router risk_score escaped valid range")
        return result
