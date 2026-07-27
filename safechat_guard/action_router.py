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
_ACTION_PRIORITY = {"pass": 0, "sanitize": 1, "block": 2}
_RULE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PRIMARY_CLAUSE_PATTERN = re.compile(r"[^。！？!?；;\r\n]+")
_SECONDARY_DELIMITER_PATTERN = re.compile(r"[,，:：]")
_SCOPE_TRANSITIONS = (
    "但是", "不过", "然而", "随后", "然后", "接着", "另一段",
    "后半段", "页面下方", "却", "但",
)
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


@dataclass(frozen=True)
class _LegalContext:
    rule_id: str
    family_ids: frozenset[str]
    terms: tuple[str, ...]
    override_terms: tuple[str, ...]


@dataclass(frozen=True)
class _SanitizeRule:
    rule_id: str
    category: str
    terms: tuple[str, ...]
    confidence: float
    risk_score: int


@dataclass(frozen=True)
class _Clause:
    index: int
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _Evidence:
    term: str
    start: int
    end: int
    evidence_type: str
    rule_id: str
    clause_index: int

    def public(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "start": self.start,
            "end": self.end,
            "evidence_type": self.evidence_type,
            "rule_id": self.rule_id,
            "clause_index": self.clause_index,
        }


class ActionRouter:
    """Route detector evidence with clause-local, span-independent rules."""

    def __init__(self, rules_path: str | Path):
        self.rules_path = Path(rules_path)
        payload = self._load_payload(self.rules_path)
        (
            self.max_evidence_distance,
            self.negation_terms,
            self.safety_contexts,
            self.unsafe_override_terms,
            self.legal_contexts,
            self.local_insert_context_terms,
            self.local_insert_block_override_terms,
            self.sanitize_rules,
            self.rule_families,
        ) = self._validate_payload(payload)
        self._scope_context_terms = tuple(
            dict.fromkeys(
                term
                for context in (*self.safety_contexts, *self.legal_contexts)
                for term in context.terms
            )
        )

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

        routed_text = self._canonicalize(normalized_text or original_text)
        clauses = self._split_clauses(routed_text)
        clause_results = [self._route_clause(clause) for clause in clauses]
        winning_priority = max(
            (_ACTION_PRIORITY[result["action"]] for result in clause_results),
            default=0,
        )
        winning = [
            result for result in clause_results
            if _ACTION_PRIORITY[result["action"]] == winning_priority
        ]

        if winning_priority == 0:
            fallback = self._detector_fallback(
                clause_results, rule_detections, semantic_detections
            )
            if fallback is not None:
                return fallback
            reason_codes = self._merge_lists(
                result["reason_codes"] for result in winning
            ) or ["NO_RISK_EVIDENCE"]
            return self._result(
                action="pass",
                category="normal",
                risk_level="none",
                confidence=min(
                    (result["confidence"] for result in winning), default=0.98
                ),
                reason_codes=reason_codes,
                hard_block=False,
                risk_score=0,
                matched_rule_ids=self._merge_lists(
                    result["matched_rule_ids"] for result in winning
                ),
                sanitize_matches=[],
                evidence=[],
            )

        selected = sorted(
            winning,
            key=lambda item: (-item["confidence"], item["clause_index"]),
        )[0]
        reasons = self._merge_lists(result["reason_codes"] for result in winning)
        rule_categories = self._detection_categories(rule_detections)
        semantic_categories = self._detection_categories(semantic_detections)
        agreement = sorted(set(rule_categories) & set(semantic_categories))
        conflict = bool(rule_categories and semantic_categories and not agreement)
        if selected["category"] in agreement:
            reasons.append("RULE_SEMANTIC_AGREEMENT")
        elif conflict:
            reasons.append("RULE_SEMANTIC_CONFLICT")
        return self._result(
            action=selected["action"],
            category=selected["category"],
            risk_level=selected["risk_level"],
            confidence=min(
                selected["confidence"]
                + (0.02 if selected["category"] in agreement else 0.0),
                0.99,
            ),
            reason_codes=reasons,
            hard_block=selected["hard_block"],
            risk_score=selected["risk_score"],
            matched_rule_ids=self._merge_lists(
                result["matched_rule_ids"] for result in winning
            ),
            sanitize_matches=self._merge_lists(
                result["sanitize_matches"] for result in winning
            ),
            evidence=self._merge_evidence(
                result["evidence"] for result in winning
            ),
        )
    def _route_clause(self, clause: _Clause) -> dict[str, Any]:
        safe_ids = self._matched_context_ids(clause.text, self.safety_contexts)
        unsafe_override = self._matched_terms(clause.text, self.unsafe_override_terms)
        protected_families, legal_ids = self._legal_protections(clause)
        local_insert = self._matched_terms(
            clause.text, self.local_insert_context_terms
        )
        local_block_override = self._matched_terms(
            clause.text, self.local_insert_block_override_terms
        )

        family_matches = self._match_families(clause)
        effective: list[dict[str, Any]] = []
        downgraded: list[dict[str, Any]] = []
        for match in family_matches:
            family_id = match["family"].rule_id
            if family_id in protected_families:
                continue
            if safe_ids and not unsafe_override:
                continue
            if local_insert and not local_block_override:
                downgraded.append(match)
                continue
            effective.append(match)

        if effective:
            selected = effective[0]
            return self._clause_result(
                clause,
                action="block",
                category=selected["family"].category,
                risk_level="high",
                confidence=selected["family"].confidence,
                reason_codes=["COMPOUND_RULE_MATCH"],
                hard_block=True,
                risk_score=selected["family"].risk_score,
                matched_rule_ids=[item["family"].rule_id for item in effective],
                sanitize_matches=[],
                evidence=[selected["object"], selected["implementation"]],
            )

        sanitize_evidence = self._match_sanitize_rules(clause)
        if downgraded:
            selected = downgraded[0]
            evidence = [selected["object"], selected["implementation"]]
            return self._clause_result(
                clause,
                action="sanitize",
                category=selected["family"].category,
                risk_level="medium",
                confidence=0.78,
                reason_codes=["LOCAL_RISK_INSERT"],
                hard_block=False,
                risk_score=78,
                matched_rule_ids=[item["family"].rule_id for item in downgraded],
                sanitize_matches=[item.term for item in evidence],
                evidence=evidence,
            )
        if sanitize_evidence:
            selected_rule, evidence = sanitize_evidence[0]
            return self._clause_result(
                clause,
                action="sanitize",
                category=selected_rule.category,
                risk_level="medium",
                confidence=selected_rule.confidence,
                reason_codes=["SANITIZE_RULE_MATCH"],
                hard_block=False,
                risk_score=selected_rule.risk_score,
                matched_rule_ids=[rule.rule_id for rule, _ in sanitize_evidence],
                sanitize_matches=[
                    item.term for _, items in sanitize_evidence for item in items
                ],
                evidence=[item for _, items in sanitize_evidence for item in items],
            )

        object_evidence = self._object_evidence(clause)
        unprotected_objects = [
            item for item in object_evidence
            if item.rule_id not in protected_families
        ]
        if safe_ids:
            reasons = ["SAFE_CONTEXT"]
            if family_matches or object_evidence:
                reasons.append("NON_REAL_WORLD_MENTION")
            return self._clause_result(
                clause,
                action="pass",
                category="normal",
                risk_level="none",
                confidence=0.95,
                reason_codes=reasons,
                hard_block=False,
                risk_score=0,
                matched_rule_ids=safe_ids,
                sanitize_matches=[],
                evidence=[],
                protected=True,
            )
        if legal_ids and not unprotected_objects:
            return self._clause_result(
                clause,
                action="pass",
                category="normal",
                risk_level="none",
                confidence=0.95,
                reason_codes=["LEGAL_DOMAIN_CONTEXT"],
                hard_block=False,
                risk_score=0,
                matched_rule_ids=legal_ids,
                sanitize_matches=[],
                evidence=[],
                protected=True,
            )
        if unprotected_objects:
            category = self._family_by_id(unprotected_objects[0].rule_id).category
            return self._clause_result(
                clause,
                action="sanitize",
                category=category,
                risk_level="medium",
                confidence=0.65,
                reason_codes=["RISK_OBJECT_MENTION"],
                hard_block=False,
                risk_score=65,
                matched_rule_ids=[item.rule_id for item in unprotected_objects],
                sanitize_matches=[item.term for item in unprotected_objects],
                evidence=unprotected_objects,
            )
        return self._clause_result(
            clause,
            action="pass",
            category="normal",
            risk_level="none",
            confidence=0.98,
            reason_codes=["NO_RISK_EVIDENCE"],
            hard_block=False,
            risk_score=0,
            matched_rule_ids=legal_ids,
            sanitize_matches=[],
            evidence=[],
            protected=bool(legal_ids),
        )

    def _detector_fallback(
        self,
        clause_results: list[dict[str, Any]],
        rule_detections: list[Detection],
        semantic_detections: list[Detection],
    ) -> dict[str, Any] | None:
        if not rule_detections and not semantic_detections:
            return None
        if any(result.get("protected") for result in clause_results):
            return None
        category = self._select_risk_category(rule_detections, semantic_detections)
        if category is None:
            return None
        reasons = []
        if rule_detections:
            reasons.append("RULE_RISK_EVIDENCE")
        if semantic_detections:
            reasons.append("SEMANTIC_RISK_EVIDENCE")
        rule_categories = self._detection_categories(rule_detections)
        semantic_categories = self._detection_categories(semantic_detections)
        if category in set(rule_categories) & set(semantic_categories):
            reasons.append("RULE_SEMANTIC_AGREEMENT")
        elif rule_categories and semantic_categories:
            reasons.append("RULE_SEMANTIC_CONFLICT")
        confidence = self._sanitize_confidence(
            category, rule_detections, semantic_detections
        )
        return self._result(
            action="sanitize",
            category=category,
            risk_level="medium",
            confidence=confidence,
            reason_codes=reasons,
            hard_block=False,
            risk_score=round(confidence * 100),
            matched_rule_ids=[],
            sanitize_matches=[],
            evidence=[],
        )

    def _match_families(self, clause: _Clause) -> list[dict[str, Any]]:
        matches = []
        for family in self.rule_families:
            objects = self._find_evidence(
                clause, family.object_terms, "risk_object", family.rule_id,
                require_non_negated=False,
            )
            implementations = self._find_evidence(
                clause, family.implementation_terms, "implementation",
                family.rule_id, require_non_negated=True,
            )
            pairs = []
            for obj in objects:
                for implementation in implementations:
                    if self._evidence_pair_is_valid(obj, implementation):
                        pairs.append(
                            (self._evidence_distance(obj, implementation), obj, implementation)
                        )
            if pairs:
                _, obj, implementation = sorted(
                    pairs, key=lambda item: (item[0], item[1].start, item[2].start)
                )[0]
                matches.append(
                    {"family": family, "object": obj, "implementation": implementation}
                )
        return matches

    def _object_evidence(self, clause: _Clause) -> list[_Evidence]:
        return [
            evidence
            for family in self.rule_families
            for evidence in self._find_evidence(
                clause, family.object_terms, "risk_object", family.rule_id,
                require_non_negated=False,
            )
        ]

    def _match_sanitize_rules(
        self, clause: _Clause
    ) -> list[tuple[_SanitizeRule, list[_Evidence]]]:
        matches = []
        for rule in self.sanitize_rules:
            evidence = self._find_evidence(
                clause, rule.terms, "sanitize_signal", rule.rule_id,
                require_non_negated=True,
            )
            if evidence:
                matches.append((rule, evidence))
        return matches

    def _find_evidence(
        self,
        clause: _Clause,
        terms: tuple[str, ...],
        evidence_type: str,
        rule_id: str,
        *,
        require_non_negated: bool,
    ) -> list[_Evidence]:
        evidence = []
        for term in terms:
            start = 0
            while True:
                local_start = clause.text.find(term, start)
                if local_start < 0:
                    break
                local_end = local_start + len(term)
                if not require_non_negated or not self._is_negated(
                    clause.text, local_start
                ):
                    evidence.append(
                        _Evidence(
                            term=term,
                            start=clause.start + local_start,
                            end=clause.start + local_end,
                            evidence_type=evidence_type,
                            rule_id=rule_id,
                            clause_index=clause.index,
                        )
                    )
                start = local_end
        return evidence

    def _evidence_pair_is_valid(
        self, left: _Evidence, right: _Evidence
    ) -> bool:
        if left.clause_index != right.clause_index:
            return False
        if left.start < right.end and right.start < left.end:
            return False
        if left.start == right.start and left.end == right.end:
            return False
        return self._evidence_distance(left, right) <= self.max_evidence_distance

    @staticmethod
    def _evidence_distance(left: _Evidence, right: _Evidence) -> int:
        if left.end <= right.start:
            return right.start - left.end
        if right.end <= left.start:
            return left.start - right.end
        return 0
    def _legal_protections(
        self, clause: _Clause
    ) -> tuple[set[str], list[str]]:
        family_ids: set[str] = set()
        rule_ids: list[str] = []
        for context in self.legal_contexts:
            if not self._matched_terms(clause.text, context.terms):
                continue
            if self._matched_terms(clause.text, context.override_terms):
                continue
            family_ids.update(context.family_ids)
            rule_ids.append(context.rule_id)
        return family_ids, rule_ids

    def _split_clauses(self, text: str) -> list[_Clause]:
        raw_segments: list[tuple[str, int, int]] = []
        for match in _PRIMARY_CLAUSE_PATTERN.finditer(text):
            raw_segments.extend(
                self._split_scope_segment(match.group(0), match.start())
            )
        clauses = []
        for segment, start, end in raw_segments:
            cleaned_start = start
            cleaned_end = end
            while cleaned_start < cleaned_end and text[cleaned_start] in " ,，:：\t":
                cleaned_start += 1
            while cleaned_end > cleaned_start and text[cleaned_end - 1] in " ,，:：\t":
                cleaned_end -= 1
            if cleaned_start >= cleaned_end:
                continue
            clauses.append(
                _Clause(
                    index=len(clauses),
                    text=text[cleaned_start:cleaned_end],
                    start=cleaned_start,
                    end=cleaned_end,
                )
            )
        if not clauses:
            clauses.append(_Clause(index=0, text=text, start=0, end=len(text)))
        return clauses

    def _split_scope_segment(
        self, segment: str, base_start: int
    ) -> list[tuple[str, int, int]]:
        split_points = {0, len(segment)}
        for marker in _SCOPE_TRANSITIONS:
            start = 0
            while True:
                index = segment.find(marker, start)
                if index <= 0:
                    break
                if self._contains_scope_context(segment[:index]):
                    split_points.add(index)
                start = index + len(marker)
        start = 0
        while True:
            index = segment.find("结束后", start)
            if index < 0:
                break
            end = index + len("结束后")
            if self._contains_scope_context(segment[:end]):
                split_points.add(end)
            start = end
        for match in _SECONDARY_DELIMITER_PATTERN.finditer(segment):
            prefix = segment[:match.start()]
            suffix = segment[match.end():].lstrip()
            if self._contains_scope_context(prefix) or suffix.startswith(
                _SCOPE_TRANSITIONS
            ):
                split_points.add(match.end())
        ordered = sorted(split_points)
        return [
            (
                segment[ordered[index]:ordered[index + 1]],
                base_start + ordered[index],
                base_start + ordered[index + 1],
            )
            for index in range(len(ordered) - 1)
            if segment[ordered[index]:ordered[index + 1]].strip()
        ]

    def _contains_scope_context(self, text: str) -> bool:
        return bool(self._matched_terms(text, self._scope_context_terms))

    def _is_negated(self, text: str, index: int) -> bool:
        prefix = text[max(0, index - _NEGATION_WINDOW):index]
        positions = [prefix.rfind(term) for term in self.negation_terms if term in prefix]
        if not positions:
            return False
        tail = prefix[max(positions):]
        if any(marker in tail for marker in _SCOPE_TRANSITIONS):
            return False
        return True

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
        cls, payload: dict[str, Any]
    ) -> tuple[
        int,
        tuple[str, ...],
        tuple[_SafetyContext, ...],
        tuple[str, ...],
        tuple[_LegalContext, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[_SanitizeRule, ...],
        tuple[_RuleFamily, ...],
    ]:
        expected = {
            "schema_version",
            "max_evidence_distance",
            "negation_terms",
            "safety_contexts",
            "unsafe_override_terms",
            "legal_contexts",
            "local_insert_context_terms",
            "local_insert_block_override_terms",
            "sanitize_rules",
            "rule_families",
        }
        if set(payload) != expected:
            raise ValueError(
                "action rules fields do not match schema: "
                f"expected={sorted(expected)}, actual={sorted(payload)}"
            )
        if payload["schema_version"] != 2:
            raise ValueError("unsupported action rules schema_version")
        max_distance = payload["max_evidence_distance"]
        if type(max_distance) is not int or not 1 <= max_distance <= 200:
            raise ValueError(
                "GLOBAL.max_evidence_distance must be an integer between 1 and 200"
            )
        ids: set[str] = set()
        negation_terms = cls._validate_terms(
            payload["negation_terms"], "GLOBAL.negation_terms"
        )
        unsafe_override_terms = cls._validate_terms(
            payload["unsafe_override_terms"], "GLOBAL.unsafe_override_terms"
        )
        local_insert_context_terms = cls._validate_terms(
            payload["local_insert_context_terms"],
            "GLOBAL.local_insert_context_terms",
        )
        local_insert_block_override_terms = cls._validate_terms(
            payload["local_insert_block_override_terms"],
            "GLOBAL.local_insert_block_override_terms",
        )
        safety_contexts = cls._validate_safety_contexts(
            payload["safety_contexts"], ids
        )
        families = cls._validate_families(payload["rule_families"], ids)
        family_ids = {family.rule_id for family in families}
        legal_contexts = cls._validate_legal_contexts(
            payload["legal_contexts"], ids, family_ids
        )
        sanitize_rules = cls._validate_sanitize_rules(
            payload["sanitize_rules"], ids
        )
        return (
            max_distance,
            negation_terms,
            safety_contexts,
            unsafe_override_terms,
            legal_contexts,
            local_insert_context_terms,
            local_insert_block_override_terms,
            sanitize_rules,
            families,
        )

    @classmethod
    def _validate_safety_contexts(
        cls, value: Any, ids: set[str]
    ) -> tuple[_SafetyContext, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("GLOBAL.safety_contexts must be a non-empty list")
        contexts = []
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != {"id", "terms"}:
                raise ValueError("safety context must define id and terms")
            rule_id = cls._validate_rule_id(raw["id"], ids)
            contexts.append(
                _SafetyContext(
                    rule_id,
                    cls._validate_terms(raw["terms"], f"{rule_id}.terms"),
                )
            )
        return tuple(contexts)

    @classmethod
    def _validate_families(
        cls, value: Any, ids: set[str]
    ) -> tuple[_RuleFamily, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("GLOBAL.rule_families must be a non-empty list")
        families = []
        expected = {
            "id", "category", "object_terms", "implementation_terms",
            "confidence", "risk_score",
        }
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != expected:
                raise ValueError(
                    "rule family must define exactly " f"{sorted(expected)}"
                )
            rule_id = cls._validate_rule_id(raw["id"], ids)
            category = cls._validate_category(raw["category"], rule_id)
            objects = cls._validate_terms(
                raw["object_terms"], f"{rule_id}.object_terms"
            )
            implementations = cls._validate_terms(
                raw["implementation_terms"], f"{rule_id}.implementation_terms"
            )
            cls._validate_independent_terms(rule_id, objects, implementations)
            confidence = cls._validate_confidence(raw["confidence"], rule_id)
            risk_score = cls._validate_risk_score(raw["risk_score"], rule_id)
            families.append(
                _RuleFamily(
                    rule_id, category, objects, implementations,
                    confidence, risk_score,
                )
            )
        return tuple(families)
    @classmethod
    def _validate_legal_contexts(
        cls,
        value: Any,
        ids: set[str],
        family_ids: set[str],
    ) -> tuple[_LegalContext, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("GLOBAL.legal_contexts must be a non-empty list")
        contexts = []
        expected = {"id", "family_ids", "terms", "override_terms"}
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != expected:
                raise ValueError(
                    "legal context must define id, family_ids, terms, override_terms"
                )
            rule_id = cls._validate_rule_id(raw["id"], ids)
            raw_family_ids = raw["family_ids"]
            if (
                not isinstance(raw_family_ids, list)
                or not raw_family_ids
                or any(item not in family_ids for item in raw_family_ids)
            ):
                raise ValueError(
                    f"{rule_id}.family_ids contains unknown or empty family ids"
                )
            contexts.append(
                _LegalContext(
                    rule_id,
                    frozenset(raw_family_ids),
                    cls._validate_terms(raw["terms"], f"{rule_id}.terms"),
                    cls._validate_terms(
                        raw["override_terms"], f"{rule_id}.override_terms"
                    ),
                )
            )
        return tuple(contexts)

    @classmethod
    def _validate_sanitize_rules(
        cls, value: Any, ids: set[str]
    ) -> tuple[_SanitizeRule, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("GLOBAL.sanitize_rules must be a non-empty list")
        rules = []
        expected = {"id", "category", "terms", "confidence", "risk_score"}
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != expected:
                raise ValueError(
                    "sanitize rule must define exactly " f"{sorted(expected)}"
                )
            rule_id = cls._validate_rule_id(raw["id"], ids)
            rules.append(
                _SanitizeRule(
                    rule_id,
                    cls._validate_category(raw["category"], rule_id),
                    cls._validate_terms(raw["terms"], f"{rule_id}.terms"),
                    cls._validate_confidence(raw["confidence"], rule_id),
                    cls._validate_risk_score(raw["risk_score"], rule_id),
                )
            )
        return tuple(rules)

    @staticmethod
    def _validate_independent_terms(
        rule_id: str,
        object_terms: tuple[str, ...],
        implementation_terms: tuple[str, ...],
    ) -> None:
        for obj in object_terms:
            for implementation in implementation_terms:
                if obj in implementation or implementation in obj:
                    raise ValueError(
                        f"{rule_id}.object_terms conflicts with "
                        f"{rule_id}.implementation_terms: {obj!r} vs "
                        f"{implementation!r}"
                    )

    @staticmethod
    def _validate_confidence(value: Any, rule_id: str) -> float:
        if type(value) not in {int, float} or not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{rule_id}.confidence must be a numeric value between 0 and 1"
            )
        return float(value)

    @staticmethod
    def _validate_risk_score(value: Any, rule_id: str) -> int:
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError(
                f"{rule_id}.risk_score must be an integer between 0 and 100"
            )
        return value

    @staticmethod
    def _validate_category(value: Any, rule_id: str) -> str:
        if value not in RISK_CATEGORIES:
            raise ValueError(f"{rule_id}.category must be a risk category")
        return value

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

    @staticmethod
    def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
        return [term for term in terms if term in text]

    def _matched_context_ids(
        self, text: str, contexts: tuple[_SafetyContext, ...]
    ) -> list[str]:
        return [
            context.rule_id
            for context in contexts
            if self._matched_terms(text, context.terms)
        ]

    def _family_by_id(self, rule_id: str) -> _RuleFamily:
        return next(
            family for family in self.rule_families if family.rule_id == rule_id
        )

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
    ) -> str | None:
        category_order = {
            category: index for index, category in enumerate(ALLOWED_CATEGORIES)
        }
        for detections in (rule_detections, semantic_detections):
            eligible = [
                detection for detection in detections
                if detection.category in RISK_CATEGORIES
            ]
            if eligible:
                return sorted(
                    eligible,
                    key=lambda item: (
                        -int(item.score), category_order[item.category], item.source
                    ),
                )[0].category
        return None

    @staticmethod
    def _sanitize_confidence(
        category: str,
        rule_detections: list[Detection],
        semantic_detections: list[Detection],
    ) -> float:
        scores = [
            max(0, min(int(item.score), 100)) / 100
            for item in [*rule_detections, *semantic_detections]
            if item.category == category
        ]
        return round(min(max(scores, default=0.55), 0.79), 4)

    @staticmethod
    def _merge_lists(groups) -> list[str]:
        return list(dict.fromkeys(item for group in groups for item in group))

    @staticmethod
    def _merge_evidence(groups) -> list[_Evidence]:
        result = []
        seen = set()
        for group in groups:
            for item in group:
                key = (
                    item.term, item.start, item.end, item.evidence_type,
                    item.rule_id, item.clause_index,
                )
                if key not in seen:
                    seen.add(key)
                    result.append(item)
        return result

    @staticmethod
    def _clause_result(
        clause: _Clause, *, protected: bool = False, **values: Any
    ) -> dict[str, Any]:
        return {
            **values,
            "clause_index": clause.index,
            "protected": protected,
        }

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
            "evidence": [item.public() for item in values["evidence"]],
        }
        if not 0.0 <= result["confidence"] <= 1.0:
            raise AssertionError("router confidence escaped valid range")
        if not 0 <= result["risk_score"] <= 100:
            raise AssertionError("router risk_score escaped valid range")
        return result