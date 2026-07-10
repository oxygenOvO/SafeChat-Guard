# test_semantic_v2.py
from safechat_guard.semantic_classifier import SemanticClassifier

def main():
    print("🧪 测试语义分类器（详细诊断版）...\n")
    
    classifier = SemanticClassifier()
    
    # 如果模型加载失败，直接退出
    if classifier.model is None:
        print("❌ 模型加载失败，请检查 models/semantic_model.pkl 是否存在")
        return
    
    test_cases = [
        "今天天气真好，适合出门散步。",
        "加我微信有福利",
        "约炮软件哪个靠谱",
        "怎么杀死一个人",
        "世界末日预言是真的吗",
    ]
    
    print("-" * 70)
    print(f"{'输入文本':<35} | {'预测标签':<12} | {'风险分数':<10} | {'置信度':<10}")
    print("-" * 70)
    
    for text in test_cases:
        # 直接调用模型预测，不经过 detect 方法
        label = classifier.model.predict([text])[0]
        proba = classifier.model.predict_proba([text])[0]
        max_prob = max(proba)
        
        # 再调用 detect 方法看输出
        results = classifier.detect(text)
        
        display_text = text[:32] + "..." if len(text) > 35 else text
        if results:
            r = results[0]
            print(f"{display_text:<35} | {r.category:<12} | {r.score:<10} | {max_prob:.2%}")
        else:
            print(f"{display_text:<35} | ✅ 安全(无风险) | {'N/A':<10} | {max_prob:.2%}")
    
    print("-" * 70)
    print("\n💡 如果上面的预测标签显示 ad/porn/violence/sensitive，说明模型正常工作，问题在 detect 方法逻辑。")
    print("💡 如果所有预测标签都是 normal，说明模型文件可能不对，或数据有问题。")

if __name__ == "__main__":
    main()
