# test_semantic.py
from safechat_guard.semantic_classifier import SemanticClassifier

def main():
    print("🧪 开始测试语义分类器...\n")
    
    # 1. 加载模型
    classifier = SemanticClassifier()
    
    # 2. 准备测试用例（覆盖五种类别）
    test_cases = [
        # 正常句子（应该安全通过）
        ("今天天气真好，适合出门散步。", "normal"),
        ("我喜欢吃火锅，尤其是麻辣味的。", "normal"),
        ("明天下午三点我们在会议室开会。", "normal"),
        
        # 广告类（应该命中 ad）
        ("加我微信有福利", "ad"),
        ("淘宝刷单兼职日赚千元", "ad"),
        
        # 色情类（应该命中 porn）
        ("约炮软件哪个靠谱", "porn"),
        ("有没有成人网站推荐", "porn"),
        
        # 暴力类（应该命中 violence）
        ("怎么杀死一个人", "violence"),
        ("买枪的渠道", "violence"),
        
        # 敏感谣言类（应该命中 sensitive）
        ("世界末日预言是真的吗", "sensitive"),
        ("塔罗牌占卜运势", "sensitive"),
    ]
    
    print("-" * 60)
    print(f"{'输入文本':<30} | {'预测结果':<15} | {'风险分数':<10}")
    print("-" * 60)
    
    for text, expected in test_cases:
        results = classifier.detect(text)
        
        if results:
            # 取第一个检测结果（通常只有一个）
            r = results[0]
            # 截断过长的文本用于显示
            display_text = text[:28] + "..." if len(text) > 30 else text
            print(f"{display_text:<30} | {r.category:<15} | {r.score:<10}")
        else:
            display_text = text[:28] + "..." if len(text) > 30 else text
            print(f"{display_text:<30} | {'✅ 安全(无风险)':<15} | {'N/A':<10}")
    
    print("-" * 60)
    print("\n✅ 测试完成！如果广告/色情/暴力等违规词都被正确识别，说明模型工作正常。")

if __name__ == "__main__":
    main()