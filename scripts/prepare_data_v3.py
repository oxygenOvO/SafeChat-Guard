# scripts/prepare_data_v3.py
import random
import csv
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
VIOLATION_DIR = PROJECT_ROOT / "data" / "violation_sentences"
NORMAL_FILE = PROJECT_ROOT / "data" / "normal_sentences.txt"
OUTPUT_DIR = PROJECT_ROOT / "data" / "training_data"
OUTPUT_FILE = OUTPUT_DIR / "raw_train_v3.csv"

CATEGORIES = ["porn", "violence", "ad", "sensitive"]

def read_sentences_from_file(file_path):
    if not file_path.exists():
        print(f"⚠️ 警告: {file_path} 不存在")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return lines

def read_normal_sentences():
    return read_sentences_from_file(NORMAL_FILE)

def create_dataset():
    print("🚀 开始生成高质量训练数据集（V3 - 带过采样平衡）...")
    
    all_data = []
    target_count = 200  # 每类目标样本数
    
    # 1. 违规类别：过采样到 target_count
    for category in CATEGORIES:
        file_path = VIOLATION_DIR / f"{category}.txt"
        sentences = read_sentences_from_file(file_path)
        if not sentences:
            print(f"⚠️ {category}: 没有读取到任何句子")
            continue
        
        repeat_times = math.ceil(target_count / len(sentences))
        for _ in range(repeat_times):
            for sent in sentences:
                all_data.append({"text": sent, "label": category})
        print(f"📚 {category}: {len(sentences)} 条 → 过采样后 {len(sentences) * repeat_times} 条")
    
    # 2. 正常类别：也过采样到 target_count
    normal_sentences = read_normal_sentences()
    if not normal_sentences:
        normal_sentences = ["今天天气真好", "我喜欢吃火锅"]
    
    repeat_normal = math.ceil(target_count / len(normal_sentences))
    for _ in range(repeat_normal):
        for sent in normal_sentences:
            all_data.append({"text": sent, "label": "normal"})
    print(f"📖 normal: {len(normal_sentences)} 条 → 过采样后 {len(normal_sentences) * repeat_normal} 条")
    
    # 3. 打乱顺序
    random.shuffle(all_data)
    
    # 4. 统计
    label_counts = {}
    for item in all_data:
        label = item["label"]
        label_counts[label] = label_counts.get(label, 0) + 1
    
    # 5. 写入CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(all_data)
    
    print(f"\n✅ 数据集已生成！共 {len(all_data)} 条样本。")
    print(f"📂 保存路径: {OUTPUT_FILE}")
    print(f"\n📊 类别分布（已平衡）:")
    for label, count in sorted(label_counts.items()):
        print(f"   {label}: {count} 条")

if __name__ == "__main__":
    create_dataset()
