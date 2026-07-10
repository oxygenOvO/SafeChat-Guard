# scripts/train_classifier.py
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
# 旧数据（已弃用，注释掉）
# DATA_PATH = PROJECT_ROOT / "data" / "training_data" / "raw_train.csv"

# 新数据（正在使用）
DATA_PATH = PROJECT_ROOT / "data" / "training_data" / "raw_train_v3.csv"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODEL_DIR / "semantic_model.pkl"

def train():
    print("🚀 开始训练语义分类模型...")
    
    # 1. 读取数据
    df = pd.read_csv(DATA_PATH)
    X = df['text'].values
    y = df['label'].values
    print(f"📊 总样本数: {len(X)}")
    print(f"📈 类别分布: \n{df['label'].value_counts()}")

    # 2. 划分训练/测试集
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"✂️ 训练集: {len(X_train)} 条, 测试集: {len(X_test)} 条")
    
    # 3. 创建 Pipeline
    vectorizer = TfidfVectorizer(
        max_features=10000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.8
    )
    # 兼容不同版本的 sklearn
    try:
        # 新版可能不支持 multi_class 参数，直接不带
        clf = LogisticRegression(max_iter=1000, C=10.0, random_state=42)
    except TypeError:
        # 如果报错，尝试用旧版参数名
        clf = LogisticRegression(multi_class='ovr', max_iter=1000, C=1.0, random_state=42)
    
    model = Pipeline([
        ('vec', vectorizer),
        ('clf', clf)
    ])
    
    # 4. 训练
    print("⏳ 训练中...")
    model.fit(X_train, y_train)
    
    # 5. 评估
    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)
    print(f"🎯 训练集准确率: {train_acc:.2%}")
    print(f"🎯 测试集准确率: {test_acc:.2%}")
    
    # 6. 详细报告
    y_pred = model.predict(X_test)
    print("\n📋 详细分类报告:")
    print(classification_report(y_test, y_pred))
    
    # 7. 保存模型
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"✅ 模型已保存至: {MODEL_PATH}")

if __name__ == "__main__":
    train()
