# scripts/prepare_data.py
import os
import random
import csv
from pathlib import Path

# 设置路径
PROJECT_ROOT = Path(__file__).parent.parent
LEXICON_DIR = PROJECT_ROOT / "data" / "lexicons"
NORMAL_FILE = PROJECT_ROOT / "data" / "normal_sentences.txt"
OUTPUT_DIR = PROJECT_ROOT / "data" / "training_data"
OUTPUT_FILE = OUTPUT_DIR / "raw_train.csv"


def read_normal_sentences():
    """从 normal_sentences.txt 读取正常句子"""
    if not NORMAL_FILE.exists():
        print(f"⚠️ 警告: {NORMAL_FILE} 不存在，使用内置占位句子")
        return ["正常句子示例1", "正常句子示例2"]
    
    with open(NORMAL_FILE, 'r', encoding='utf-8') as f:
        sentences = [line.strip() for line in f if line.strip()]
    
    if not sentences:
        print("⚠️ 警告: normal_sentences.txt 为空，使用内置占位句子")
        return ["正常句子示例1", "正常句子示例2"]
    
    print(f"📖 加载了 {len(sentences)} 条正常句子")
    return sentences


def read_lexicon(category):
    """读取词库，每行一个词"""
    file_path = LEXICON_DIR / f"{category}.txt"
    if not file_path.exists():
        print(f"⚠️ 警告: {file_path} 不存在，使用空列表")
        return []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        words = [line.strip() for line in f if line.strip()]
    
    # 过滤掉注释行（以 # 开头）
    words = [w for w in words if w and not w.startswith('#')]
    return words


def generate_variants(word, count=3):
    """生成词的简单变体（模拟对抗归一化场景）"""
    variants = [word]
    prefixes = ["加", "看", "找", "私", "来", "有", "要", "想", "能", "可"]
    suffixes = ["我", "你", "吗", "啊", "吧", "的", "了", "呢", "哦"]
    
    for _ in range(count):
        new_word = word
        if random.random() > 0.5:
            new_word = random.choice(prefixes) + new_word
        if random.random() > 0.5:
            new_word = new_word + random.choice(suffixes)
        variants.append(new_word)
    return list(set(variants))


def create_dataset():
    print("🚀 开始生成训练数据集...")
    
    # 1. 读取四类词
    categories = ["porn", "violence", "ad", "sensitive"]
    label_map = {
        "porn": "porn",
        "violence": "violence",
        "ad": "ad",
        "sensitive": "sensitive"
    }
    
    all_data = []
    
    # 2. 生成违规数据（利用词库扩增）
    for cat in categories:
        words = read_lexicon(cat)
        if not words:
            words = ["示例词1", "示例词2"]
            print(f"⚠️ {cat}: 词库为空，使用占位词")
        else:
            print(f"📚 {cat}: 加载了 {len(words)} 个词")
        
        # 每个词生成样本（控制总量防止过大）
        for word in words[:50]:  # 最多取前50个词
            variants = generate_variants(word, count=2)
            for variant in variants:
                templates = [
                    f"{variant}",
                    f"这个{variant}",
                    f"关于{variant}的事情",
                    f"有没有{variant}",
                    f"我想了解{variant}",
                    f"{variant}是什么",
                    f"在哪里可以找到{variant}",
                ]
                for template in templates[:3]:  # 每个变体最多3句
                    all_data.append({
                        "text": template,
                        "label": label_map[cat]
                    })
    
    # 3. 加入正常样本（从 normal_sentences.txt 读取）
    normal_sentences = read_normal_sentences()
    for sent in normal_sentences:
        all_data.append({
            "text": sent,
            "label": "normal"
        })
    
    # 4. 打乱顺序
    random.shuffle(all_data)
    
    # 5. 统计各类别数量
    label_counts = {}
    for item in all_data:
        label = item["label"]
        label_counts[label] = label_counts.get(label, 0) + 1
    
    # 6. 写入 CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(all_data)
    
    print(f"\n✅ 数据集已生成！共 {len(all_data)} 条样本。")
    print(f"📂 保存路径: {OUTPUT_FILE}")
    print(f"\n📊 类别分布:")
    for label, count in sorted(label_counts.items()):
        print(f"   {label}: {count} 条")

if __name__ == "__main__":
    create_dataset()
