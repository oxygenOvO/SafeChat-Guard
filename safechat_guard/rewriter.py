class EmotionPreservingRewriter:
    """Template rewriter extracted from member D's completed demo."""

    @staticmethod
    def infer_sentiment(text: str) -> str:
        negative_terms = ["不满", "生气", "难过", "失望", "讨厌", "恶心", "蠢", "滚", "差劲"]
        positive_terms = ["喜欢", "感谢", "开心", "满意", "支持"]
        if any(term in text for term in negative_terms):
            return "负向/不满"
        if any(term in text for term in positive_terms):
            return "正向"
        return "中性/信息性"

    @staticmethod
    def _mask_matches(text: str, matches: list[str]) -> str:
        masked = text
        for match in sorted(set(matches), key=len, reverse=True):
            if match and match in masked:
                masked = masked.replace(match, "***")
        return masked

    def rewrite(self, text: str, category: str, matches: list[str]) -> dict[str, str]:
        sentiment = self.infer_sentiment(text)
        masked = self._mask_matches(text, matches)
        if category == "abuse":
            rewritten = "我对这件事非常不满，希望对方能够认真改进；我们可以继续用理性、尊重的方式沟通。"
            strategy = "保留批评和不满情绪，去除辱骂与人身攻击。"
        elif category == "ad":
            rewritten = "我想了解合规的信息发布方式，请通过公开、规范的渠道进行说明，避免引流和夸张承诺。"
            strategy = "保留推广/咨询意图，去除联系方式引流和诱导性营销话术。"
        elif category == "sensitive":
            rewritten = "请基于公开、可靠、合规的信息进行说明，避免未经证实或诱导性表述。"
            strategy = "保留询问意图，转为事实核验和合规表达。"
        else:
            rewritten = f"请保留原意与情绪强度，将内容改写为文明、合规表达：{masked}"
            strategy = "保留核心语义和情感倾向，去除高风险词汇。"
        return {
            "sentiment": sentiment,
            "masked_text": masked,
            "rewrite_text": rewritten,
            "rewrite_strategy": strategy,
        }

    def unchanged(self, text: str) -> dict[str, str]:
        return {
            "sentiment": self.infer_sentiment(text),
            "masked_text": text,
            "rewrite_text": text,
            "rewrite_strategy": "无需改写，正常放行。",
        }
