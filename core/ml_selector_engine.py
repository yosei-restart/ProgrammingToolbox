"""
机器学习模型选择器 — 决策引擎

类似瑞文标准推理测验，通过渐进式问题逐步缩小范围，
最终推荐最适合用户场景的 ML 模型。
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Question:
    """决策节点：一个问题，多个选项，每个选项指向下一个节点"""
    id: str
    text: str                          # 问题文本
    hint: str = ""                     # 辅助说明（对初学者的解释）
    options: list[Option] = field(default_factory=list)


@dataclass
class Option:
    """选项：标签 + 描述 + 指向的下一个节点 ID"""
    label: str
    desc: str = ""
    next_id: str = ""


@dataclass
class Recommendation:
    """推荐结果（叶子节点）"""
    id: str
    model_name: str                    # 模型名称
    model_name_cn: str = ""            # 中文名称
    reason: str = ""                   # 为什么推荐
    pros: list[str] = field(default_factory=list)    # 优点
    cons: list[str] = field(default_factory=list)    # 缺点
    alternatives: list[str] = field(default_factory=list)  # 备选模型
    sklearn_class: str = ""            # scikit-learn 类名（如有）
    difficulty: str = ""               # 学习难度：入门/中等/高级
    next_steps: list[str] = field(default_factory=list)  # 下一步做什么
    glossary: dict[str, str] = field(default_factory=dict)  # 术语解释


# ============================================================
# 决策树定义
# ============================================================

# 共享术语表 — 所有推荐共用的基础概念，各推荐还可追加自身特有术语
BASE_GLOSSARY: dict[str, str] = {
    "训练集": "用来让模型学习的数据，就像学生的练习题（有答案）",
    "测试集": "用来检验模型水平的数据，就像考试题（模型没见过）",
    "特征": "输入的每一列数据，如'年龄''收入''性别'，是模型做判断的依据",
    "标签": "你要预测的那一列。分类的标签是类别，回归的标签是数字",
    "过拟合": "模型在训练集上表现完美，但新数据上效果很差。像学生只背了习题答案，不会做新题",
    "欠拟合": "模型连训练集都学不好，说明模型太简单或数据特征不够",
    "标准化": "把数据缩放到均值0、标准差1，让不同量纲的特征可以公平比较",
    "交叉验证": "把数据分成几份，轮流用其中一份做测试、其余做训练，取平均结果，更可靠",
    "超参数": "模型训练前需要人为设定的参数，如树的深度、学习率，不是从数据中学到的",
    "正则化": "给模型加'惩罚'，防止它记太多无关细节，是防止过拟合的常用手段",
}

DECISION_TREE: dict[str, Question | Recommendation] = {

    # ── Step 1: 任务类型 ──
    "q01_task": Question(
        id="q01_task",
        text="你的任务目标是什么？",
        hint="机器学习分两大范式：\n① 监督学习 — 你有'题目'也有'答案'（标注过的数据），模型学会从题目推答案。分类和回归属于监督学习。\n② 无监督学习 — 只有'题目'没有'答案'，模型自己发现规律。聚类和降维属于无监督学习。\n\n简单判断：\n• 答案是一个'类别'（OK/NG、是/否、猫/狗）→ 分类\n• 答案是一个'数字'（价格、温度、销量）→ 回归\n• 没有答案，让机器自己找规律 → 聚类或降维\n\n⚠ 分类 vs 异常检测的区别（Andrew Ng标准）：\n• 两个条件同时满足才走分类：①异常样本≥20个 ②异常占比≥2%（如10000条中需≥200条异常）\n• 任一条件不满足 → 走异常检测。因为模型会偷懒说'全正常'就能拿高准确率\n\n💡 不确定选哪个？使用下方的计算器，输入总样本数和异常数，自动帮你判断。\n\n🔧 工业场景（多工况数据）：一台设备在不同条件下测了多次，样本数怎么算？\n打个比方——抽检了50根水管，每根分别用低压、中压、高压测试，总数据 = 50×3 = 150条。\n其中3根有裂缝（NG），低压时不漏，高压时才漏——裂缝是真实存在的，只是特定条件才暴露。\n把\u201c测试压力\u201d也作为一条信息【特征】喂给模型，模型训练后会学到：同样的信号，低压下是OK，高压下才是NG。\n注意：同一根水管的3条数据都归属于这根水管，不能拆散。",
        options=[
            Option("分类", "判断数据属于哪个类别。例如：垃圾邮件检测、图片识别、客户是否会流失", "q02_cls"),
            Option("回归", "预测一个连续的数值。例如：房价预测、温度预测、股票价格", "q02_reg"),
            Option("聚类", "把相似的数据自动分组。例如：用户分群、文档归类、市场细分", "q02_clu"),
            Option("降维", "压缩数据维度，保留核心信息。例如：数据可视化、特征压缩、去噪", "q02_dim"),
            Option("异常检测", "找出数据中的异常点。例如：欺诈交易检测、设备故障预警、入侵检测", "q02_ano"),
            Option("时间序列预测", "基于历史时间数据预测未来。例如：销量预测、流量预测、天气预测", "q02_ts"),
        ],
    ),

    # ════════════════════════════════════════════════════════
    # 分类分支
    # ════════════════════════════════════════════════════════

    "q02_cls": Question(
        id="q02_cls",
        text="你的数据规模有多大？",
        hint="数据量直接影响模型选择。小数据(<1000条)适合简单模型，大数据(>10万条)适合复杂模型。",
        options=[
            Option("小（< 1,000 条）", "样本很少，需要简单且不易过拟合的模型", "q03_cls_small"),
            Option("中（1,000 ~ 100,000 条）", "常规规模，大多数模型都适用", "q03_cls_mid"),
            Option("大（> 100,000 条）", "数据充足，可以使用复杂模型追求更高精度", "q03_cls_large"),
        ],
    ),

    "q03_cls_small": Question(
        id="q03_cls_small",
        text="你的数据是什么格式？",
        hint="表格数据=Excel/CSV/数据库表，每行一个样本；文本数据=评论/文章/邮件；图像数据=照片/扫描件。",
        options=[
            Option("表格数据（数值型）", "特征都是数字，如年龄、收入、身高、温度", "q04_need_explain"),
            Option("表格数据（类别型）", "特征是标签/分类，如性别、城市、是否购买", "q04_need_explain"),
            Option("表格数据（混合型）", "既有数值也有类别特征，如客户信息表", "q04_need_explain"),
            Option("文本数据", "如评论、文章、邮件内容，需要自然语言处理(NLP)", "q04_need_explain"),
            Option("图像数据", "如照片、扫描件、截图，需要计算机视觉(CV)", "q04_need_explain"),
        ],
    ),

    "q03_cls_mid": Question(
        id="q03_cls_mid",
        text="你的数据是什么格式？",
        hint="表格数据=Excel/CSV/数据库表；文本数据=评论/文章/邮件；图像数据=照片/扫描件。",
        options=[
            Option("表格数据（数值型）", "特征都是数字，如年龄、收入、身高、温度", "q04_need_explain"),
            Option("表格数据（类别型）", "特征是标签/分类，如性别、城市、是否购买", "q04_need_explain"),
            Option("表格数据（混合型）", "既有数值也有类别特征，如客户信息表", "q04_need_explain"),
            Option("文本数据", "如评论、文章、邮件内容，需要自然语言处理(NLP)", "q04_need_explain"),
            Option("图像数据", "如照片、扫描件、截图，需要计算机视觉(CV)", "q04_need_explain"),
        ],
    ),

    "q03_cls_large": Question(
        id="q03_cls_large",
        text="你的数据是什么格式？",
        hint="大数据场景下，不同数据格式需要不同的处理管道。",
        options=[
            Option("表格数据（混合型）", "结构化数据，如用户行为日志、交易记录", "q04_need_explain"),
            Option("文本数据", "如评论、文章、邮件内容，需要自然语言处理(NLP)", "q04_need_explain"),
            Option("图像数据", "如照片、扫描件、截图，需要计算机视觉(CV)", "q04_need_explain"),
        ],
    ),

    "q04_need_explain": Question(
        id="q04_need_explain",
        text="你需要模型可解释吗？",
        hint="可解释性意味着你能理解模型为什么做出某个预测。医疗、金融等场景通常需要。",
        options=[
            Option("需要可解释", "必须能解释每个预测的原因，如医疗诊断、信贷审批", "r_cls_explain"),
            Option("不需要，精度优先", "只要能准确预测就行，如广告点击率预估", "r_cls_accurate"),
        ],
    ),

    # 分类推荐结果
    "r_cls_explain": Recommendation(
        id="r_cls_explain",
        model_name="Logistic Regression / Decision Tree",
        model_name_cn="逻辑回归 / 决策树",
        reason="你的数据规模较小且需要可解释性。逻辑回归是分类任务的基线模型，系数可直接解释每个特征的影响方向；决策树以if-else规则呈现，普通人也能理解。",
        pros=["高度可解释，每个预测都有明确路径", "训练速度快，资源占用小", "不容易过拟合（逻辑回归）", "不需要大量数据预处理"],
        cons=["对复杂非线性关系拟合能力有限", "特征工程工作量较大", "大数据场景下精度不如集成模型"],
        alternatives=["朴素贝叶斯（Naive Bayes）", "线性SVM", "规则学习（RuleFit）"],
        sklearn_class="sklearn.linear_model.LogisticRegression / sklearn.tree.DecisionTreeClassifier",
        difficulty="入门",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 准备数据：确保数据是表格格式（CSV/Excel），每一行是一个样本，每一列是一个特征",
            "3. 处理缺失值：用 fillna() 填充或用 dropna() 删除",
            "4. 拆分训练集和测试集：from sklearn.model_selection import train_test_split",
            "5. 训练模型：model.fit(X_train, y_train) → 预测：model.predict(X_test)",
            "6. 评估：用 accuracy_score 或 classification_report 查看准确率",
        ],
        glossary={
            "训练集": "用来让模型学习的数据，就像学生的练习题（有答案）",
            "测试集": "用来检验模型水平的数据，就像考试题（模型没见过）",
            "特征": "输入的每一列数据，如'年龄''收入''性别'，是模型做判断的依据",
            "标签": "你要预测的那一列，如'是否购买'。分类的标签是类别，回归的标签是数字",
            "准确率": "预测正确的比例。100个样本中预测对了85个，准确率=85%",
            "过拟合": "模型在训练集上表现完美，但新数据上效果很差。像学生只背了习题答案",
            "欠拟合": "模型连训练集都学不好，说明模型太简单或数据特征不够",
        },
    ),

    "r_cls_accurate": Recommendation(
        id="r_cls_accurate",
        model_name="Random Forest / XGBoost",
        model_name_cn="随机森林 / XGBoost",
        reason="数据量中等，追求精度。随机森林通过多棵决策树投票减少过拟合，XGBoost 是 Kaggle 竞赛的常胜算法，在结构化数据上表现极佳。",
        pros=["高精度，结构化数据上表现优秀", "自动处理缺失值", "特征重要性排名", "对异常值鲁棒"],
        cons=["模型较大，推理速度较慢", "可解释性差（黑盒）", "超参数调优需要经验"],
        alternatives=["LightGBM", "CatBoost", "梯度提升树（GBDT）"],
        sklearn_class="sklearn.ensemble.RandomForestClassifier / xgboost.XGBClassifier",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install scikit-learn xgboost",
            "2. 准备数据：整理为表格格式（CSV/Excel），确保标签列是类别值",
            "3. 编码类别特征：用 LabelEncoder 或 OneHotEncoder 将文字转为数字",
            "4. 拆分训练集和测试集：from sklearn.model_selection import train_test_split",
            "5. 训练模型：RandomForestClassifier(n_estimators=100).fit(X_train, y_train) 或 XGBClassifier().fit(X_train, y_train)",
            "6. 评估：用 classification_report 查看各类别精度，用 feature_importances_ 查看哪些特征最关键",
        ],
        glossary={
            "集成学习": "组合多个弱模型为一个强模型，就像'三个臭皮匠顶个诸葛亮'。随机森林用投票，XGBoost 用接力修正",
            "特征重要性": "模型告诉你每个特征对预测的贡献大小，数值越大越重要，可以用来删掉没用的特征",
            "决策树": "像流程图一样的模型，每一步问一个问题（如'年龄>30？'），最终走到叶子节点得出预测结果",
            "XGBoost": "eXtreme Gradient Boosting 的缩写，是梯度提升树的工业级实现，竞赛圈'神器'，速度快精度高",
        },
    ),

    # ════════════════════════════════════════════════════════
    # 回归分支
    # ════════════════════════════════════════════════════════

    "q02_reg": Question(
        id="q02_reg",
        text="你的数据规模和特征关系如何？",
        hint="线性关系意味着 y=ax+b 就能描述（散点图大致是一条直线），非线性则需要更复杂的模型。\n\n数据规模：小＜5,000条 / 中5,000~100,000条 / 大＞100,000条。",
        options=[
            Option("小（<5,000条），线性关系", "特征和目标值之间大致是直线关系，数据量小适合简单模型", "r_reg_linear"),
            Option("中（5,000~100,000条），非线性关系", "特征和目标值之间关系复杂，曲线变化，中等数据量", "r_reg_tree"),
            Option("大（>100,000条），非线性关系", "海量数据且关系复杂，追求最高精度", "r_reg_deep"),
        ],
    ),

    "r_reg_linear": Recommendation(
        id="r_reg_linear",
        model_name="Linear Regression / Ridge / Lasso",
        model_name_cn="线性回归 / 岭回归 / Lasso回归",
        reason="数据量小且关系简单，线性回归是最优选择。Ridge（L2正则化）防止过拟合，Lasso（L1正则化）还能自动做特征选择。",
        pros=["极度可解释，每个系数代表影响程度", "训练和预测都极快", "数学基础扎实，统计推断方便"],
        cons=["只能拟合线性关系", "对异常值敏感", "特征之间不能有强相关性（多重共线性）"],
        alternatives=["ElasticNet", "支持向量回归（SVR）", "多项式回归"],
        sklearn_class="sklearn.linear_model.LinearRegression / Ridge / Lasso",
        difficulty="入门",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 准备数据：整理为表格格式（CSV/Excel），去除明显异常值",
            "3. 检查线性关系：用 scatter plot 画每个特征与目标值的散点图，确认大致是直线关系",
            "4. 标准化特征：from sklearn.preprocessing import StandardScaler，这对 Ridge/Lasso 很重要",
            "5. 拆分并训练：train_test_split → LinearRegression().fit(X_train, y_train)",
            "6. 评估：用 r2_score、mean_squared_error、mean_absolute_error 三个指标综合判断",
        ],
        glossary={
            "R²": "又称决定系数，取值范围0~1，越接近1说明模型解释力越强。R²=0.8 表示模型解释了80%的数据变化",
            "MSE": "均方误差，预测值与真实值差值的平方的平均值。越小越好，但对大误差惩罚很重（因为是平方）",
            "多重共线性": "两个或多个特征之间高度相关（如'身高厘米'和'身高英寸'），会让回归系数不稳定、不可靠",
            "L1/L2正则化": "L1（Lasso）能把不重要的特征系数直接压到0，相当于自动选特征；L2（Ridge）把系数整体缩小但不归零，更平滑",
        },
    ),

    "r_reg_tree": Recommendation(
        id="r_reg_tree",
        model_name="Random Forest Regressor / XGBoost Regressor",
        model_name_cn="随机森林回归 / XGBoost回归",
        reason="数据中等、关系复杂。树模型天然支持非线性关系，不需要手动做特征工程，对异常值鲁棒。",
        pros=["自动捕捉非线性关系", "特征重要性排名", "对数据分布无要求", "处理缺失值能力强"],
        cons=["外推能力差（预测值不会超出训练数据范围）", "可解释性差", "超参数多"],
        alternatives=["LightGBM", "CatBoost", "梯度提升回归树"],
        sklearn_class="sklearn.ensemble.RandomForestRegressor",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install scikit-learn xgboost",
            "2. 准备数据：整理为表格格式，不需要标准化（树模型不受量纲影响）",
            "3. 拆分训练集和测试集：train_test_split(X, y, test_size=0.2)",
            "4. 训练模型：RandomForestRegressor(n_estimators=100).fit(X_train, y_train) 或 XGBRegressor().fit(X_train, y_train)",
            "5. 评估：用 mean_squared_error 和 r2_score 查看预测精度",
            "6. 分析特征重要性：model.feature_importances_ 查看哪些特征对预测贡献最大",
        ],
        glossary={
            "集成学习": "组合多棵决策树的结果取平均（随机森林）或逐步修正（XGBoost），比单棵树更稳定、更准",
            "特征重要性": "模型告诉你每个特征对预测的贡献大小，数值越大越重要",
            "外推": "预测训练数据范围之外的数值。树模型外推能力差，比如训练数据最高房价500万，它几乎不会预测出600万",
            "残差": "预测值与真实值之间的差距。好的模型残差应该随机分布，不呈现任何规律",
        },
    ),

    "r_reg_deep": Recommendation(
        id="r_reg_deep",
        model_name="深度神经网络（DNN）",
        model_name_cn="深度神经网络",
        reason="数据量极大，传统模型难以捕捉所有模式。深度神经网络可以学习任意复杂的函数映射。",
        pros=["拟合能力极强", "自动特征提取", "适合高维稀疏数据"],
        cons=["需要大量数据和计算资源", "完全黑盒，不可解释", "调参复杂，容易过拟合", "训练时间长"],
        alternatives=["XGBoost（大数据版）", "Transformer", "TabNet"],
        sklearn_class="（需使用 PyTorch / TensorFlow）",
        difficulty="高级",
        next_steps=[
            "1. 安装 PyTorch：pip install torch torchvision",
            "2. 准备数据：标准化所有特征（StandardScaler），转换为 PyTorch Tensor",
            "3. 构建网络：用 nn.Sequential 搭建 3-5 层全连接网络，中间用 ReLU 激活，最后输出1个数值（不加激活函数）",
            "4. 选择损失函数：回归任务用 nn.MSELoss 或 nn.L1Loss",
            "5. 训练：用 DataLoader 分批喂数据，Adam 优化器，设置合适的 epoch 数（建议从100开始），监控训练集和验证集的 loss 防止过拟合",
            "6. 评估：在测试集上计算 R² 和 MSE，与简单的线性回归对比，确认深度模型确实带来了提升",
        ],
        glossary={
            "深度学习": "用多层神经网络从数据中自动学习层级化特征表示，层数越多学的模式越复杂",
            "激活函数": "给神经网络加入非线性能力的函数。ReLU 是最常用的：正数原样输出，负数直接变0",
            "epoch": "模型把所有训练数据完整看一遍叫一个 epoch。通常需要几十到几百个 epoch 才能学好",
            "batch": "每次喂给模型的一小批数据。batch=32 表示每次拿32条数据计算梯度更新一次参数，比一次看全部数据更快更省内存",
        },
    ),

    # ════════════════════════════════════════════════════════
    # 聚类分支
    # ════════════════════════════════════════════════════════

    "q02_clu": Question(
        id="q02_clu",
        text="你的聚类需求是什么？",
        hint="不同聚类算法适用于不同形状的数据分布和不同数据量。数据量：＜100,000条为中等，＞100,000条为很大。",
        options=[
            Option("分多少组我不确定，让算法自己找", "数据量中等（<100,000条），簇形状大致是球形", "r_clu_kmeans"),
            Option("簇的形状可能不规则", "数据分布复杂，簇可能是任意形状", "r_clu_dbscan"),
            Option("数据量很大（>100,000条），且需要层级结构", "需要知道大类套小类的层级关系", "r_clu_hier"),
            Option("每个数据点可以属于多个组", "软聚类，如一个文档属于多个主题", "r_clu_gmm"),
        ],
    ),

    "r_clu_kmeans": Recommendation(
        id="r_clu_kmeans",
        model_name="K-Means",
        model_name_cn="K均值聚类",
        reason="最经典、最易理解的聚类算法。适合球形分布的数据，速度快，结果直观。",
        pros=["简单直观，易于理解和解释", "计算速度快，适合大数据", "scikit-learn 实现非常成熟"],
        cons=["需要预先指定聚类数 K", "只能发现球形簇", "对初始中心点敏感", "对异常值敏感"],
        alternatives=["Mini-Batch K-Means（大数据版）", "K-Medoids（对异常值鲁棒）"],
        sklearn_class="sklearn.cluster.KMeans",
        difficulty="入门",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 标准化数据：from sklearn.preprocessing import StandardScaler（K-Means 对尺度敏感，必须标准化）",
            "3. 用肘部法则确定 K 值：对 K=2~10 分别训练，记录 inertia_，画折线图找'拐点'",
            "4. 训练模型：KMeans(n_clusters=最佳K, random_state=42).fit(X_scaled)",
            "5. 获取结果：model.labels_ 得到每个样本的簇编号，model.cluster_centers_ 得到每个簇的中心点",
            "6. 可视化：用 scatter plot 画前两个特征（或 PCA 降维后），按 cluster 着色，检查聚类效果",
        ],
        glossary={
            "簇": "聚类算法把相似的数据分到一组，这组就叫一个'簇'（cluster）",
            "肘部法则": "随着 K 增大，聚类误差（inertia）会下降。找到下降速度突然变缓的那个'拐点'，就是最佳 K 值，形状像手肘",
            "轮廓系数": "衡量聚类质量的指标，取值-1到1。越接近1说明簇内紧凑、簇间分离，聚类效果好",
            "质心": "每个簇的'中心点'，是该簇所有样本在各维度上取平均得到的虚拟点",
        },
    ),

    "r_clu_dbscan": Recommendation(
        id="r_clu_dbscan",
        model_name="DBSCAN",
        model_name_cn="基于密度的聚类",
        reason="不需要预设聚类数，能自动发现任意形状的簇，还能自动识别噪声点。",
        pros=["不需要预设聚类数", "能发现任意形状的簇", "自动识别异常点/噪声", "对数据顺序不敏感"],
        cons=["密度差异大时效果差", "高维数据效果差（维度灾难）", "参数 eps 和 min_samples 需要调参"],
        alternatives=["HDBSCAN（改进版）", "OPTICS", "Mean Shift"],
        sklearn_class="sklearn.cluster.DBSCAN",
        difficulty="中等",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 标准化数据：StandardScaler().fit_transform(X)（距离计算对尺度敏感）",
            "3. 调参 eps：用 K-距离图（对每个点计算到第 k 近邻的距离，排序后画图，找'拐点'作为 eps 值）",
            "4. 调参 min_samples：一般设为特征数的2倍，最小不低于3",
            "5. 训练模型：DBSCAN(eps=调好的值, min_samples=调好的值).fit(X_scaled)",
            "6. 分析结果：标签为-1的是噪声点，非负数是簇编号。用 scatter plot 按簇着色，噪声点用灰色标注",
        ],
        glossary={
            "密度聚类": "不靠距离划分，而是找'密度高'的区域作为簇。就像看人群分布——人扎堆的地方就是簇，散落的人就是噪声",
            "eps": "邻域半径，决定'多近算邻居'。太大则所有点成一簇，太小则几乎所有点都是噪声",
            "min_samples": "最少邻居数，一个点周围至少要有这么多邻居才能算核心点",
            "噪声点": "不属于任何簇的孤立点，DBSCAN 用标签-1表示。这些可能是异常值，也可能是数据中的'边缘人'",
        },
    ),

    "r_clu_hier": Recommendation(
        id="r_clu_hier",
        model_name="层次聚类（Agglomerative Clustering）",
        model_name_cn="层次聚类",
        reason="生成树状图（Dendrogram），直观展示数据的层级结构，适合需要了解'大类套小类'的场景。",
        pros=["生成可视化树状图", "不需要预设聚类数（可事后裁切）", "结果稳定可复现", "适合各种距离度量"],
        cons=["计算复杂度高 O(n²)，不适合超大样本", "对噪声和异常值敏感", "一旦合并无法撤销"],
        alternatives=["BIRCH（大数据版）", "谱聚类（Spectral Clustering）"],
        sklearn_class="sklearn.cluster.AgglomerativeClustering",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install scikit-learn scipy matplotlib",
            "2. 标准化数据：StandardScaler().fit_transform(X)",
            "3. 选择 linkage 方法：ward（默认，适合球形簇）、complete、average（分别试一下看效果）",
            "4. 画树状图：from scipy.cluster.hierarchy import dendrogram, linkage → 用 linkage 计算 → dendrogram 画图",
            "5. 裁切树状图：在树状图上选一个高度横切一刀，确定簇数 K，然后 AgglomerativeClustering(n_clusters=K).fit(X_scaled)",
            "6. 评估：用轮廓系数（silhouette_score）比较不同 K 值的效果，选择最高的",
        ],
        glossary={
            "树状图": "又称 Dendrogram，像一棵倒置的树，从底部每个样本开始，逐步向上合并，展示数据之间的层级关系",
            "linkage": "合并策略——决定两个簇'距离'怎么算。ward 让合并后方差增量最小，complete 取最远点距离，average 取平均距离",
            "凝聚": "层次聚类的一种方式，从每个样本单独成一簇开始，逐步合并最近的簇，直到只剩一个簇",
        },
    ),

    "r_clu_gmm": Recommendation(
        id="r_clu_gmm",
        model_name="高斯混合模型（GMM）",
        model_name_cn="高斯混合模型",
        reason="软聚类，每个数据点给出属于每个簇的概率，而不是硬性分配。适合数据点可能属于多个类别的情况。",
        pros=["软聚类，输出概率而非硬标签", "可以拟合椭圆形簇", "有概率解释，理论基础扎实"],
        cons=["需要预设聚类数", "对初始值敏感", "假设数据服从高斯分布", "高维数据效果下降"],
        alternatives=["贝叶斯高斯混合模型", "狄利克雷过程混合模型"],
        sklearn_class="sklearn.mixture.GaussianMixture",
        difficulty="中等",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 标准化数据：StandardScaler().fit_transform(X)（GMM 对尺度敏感）",
            "3. 选择 n_components：用 BIC 或 AIC 准则，对 n=2~10 分别训练，选择 BIC/AIC 最低的 n",
            "4. 训练模型：GaussianMixture(n_components=最佳n, random_state=42).fit(X_scaled)",
            "5. 获取结果：model.predict_proba(X) 得到每个样本属于每个簇的概率，model.means_ 得到每个簇的中心",
            "6. 可视化：用 scatter plot 按最高概率簇着色，点的大小可以编码概率（概率越高点越大）",
        ],
        glossary={
            "高斯分布": "又称正态分布，就是经典的'钟形曲线'。GMM 假设每个簇都服从一个高斯分布",
            "软聚类": "与 K-Means 的'硬聚类'（每个点只能属于一个簇）不同，GMM 给出每个点属于各簇的概率，如'60%属于A簇，30%属于B簇，10%属于C簇'",
            "期望最大化": "GMM 的核心算法，交替执行两步：E步估计每个点属于各簇的概率，M步用这些概率更新簇的参数。反复迭代直到收敛",
            "BIC": "贝叶斯信息准则，用于选模型复杂度。BIC 越小越好，它会惩罚参数过多的模型，防止过拟合",
        },
    ),

    # ════════════════════════════════════════════════════════
    # 降维分支
    # ════════════════════════════════════════════════════════

    "q02_dim": Question(
        id="q02_dim",
        text="你的降维目的是什么？",
        hint="降维有两个主要目的：可视化（通常降到2-3维）或特征压缩（保留95%以上信息的同时减少维度）。",
        options=[
            Option("主要是为了可视化", "把高维数据降到2-3维，用于画图展示", "r_dim_vis"),
            Option("主要是为了压缩特征", "去掉冗余特征，加速后续模型训练", "r_dim_compress"),
            Option("数据是非线性结构", "特征之间不是简单的线性关系", "r_dim_nonlinear"),
        ],
    ),

    "r_dim_vis": Recommendation(
        id="r_dim_vis",
        model_name="t-SNE / UMAP",
        model_name_cn="t-SNE / UMAP",
        reason="t-SNE 和 UMAP 是可视化领域最流行的降维算法，能把高维数据漂亮地降到2-3维，保留局部结构。",
        pros=["可视化效果极佳，聚类模式清晰可见", "UMAP 速度快，保留全局结构更好", "t-SNE 在单细胞RNA测序等领域是标准做法"],
        cons=["结果不可复现（随机性）", "只能用于可视化，不能用于特征工程", "t-SNE 计算慢，不适合大数据", "超参数对结果影响大"],
        alternatives=["PCA（如只需线性降维）", "LargeVis", "TriMap"],
        sklearn_class="sklearn.manifold.TSNE / umap.UMAP",
        difficulty="中等",
        next_steps=[
            "1. 安装依赖：pip install scikit-learn umap-learn",
            "2. 标准化数据：StandardScaler().fit_transform(X)（距离计算对尺度敏感）",
            "3. t-SNE：TSNE(n_components=2, perplexity=30, random_state=42).fit_transform(X_scaled) → 用 scatter plot 画散点图",
            "4. UMAP（推荐先试）：umap.UMAP(n_components=2, random_state=42).fit_transform(X_scaled) → 同样用 scatter plot 画图",
            "5. 对比两者效果：t-SNE 更擅长保留局部邻居关系，UMAP 在全局结构和速度上更好",
            "6. 注意：降维结果只用于可视化展示，不要把降维后的坐标当作特征输入到下游模型",
        ],
        glossary={
            "降维": "把高维数据（几十、几百维）压缩到2-3维，方便在平面图上展示。就像把一栋楼拍成一张照片——会丢失一些信息，但结构还在",
            "perplexity": "t-SNE 的核心参数，大致表示每个点期望的'近邻数'。建议在5-50之间调整，值越大越关注全局结构",
            "局部结构": "原始数据中距离近的点，降维后也应该近。t-SNE 把这个做得特别好",
            "全局结构": "原始数据中各组之间的相对位置关系。UMAP 比 t-SNE 更好地保留了各组之间的远近关系",
        },
    ),

    "r_dim_compress": Recommendation(
        id="r_dim_compress",
        model_name="PCA（主成分分析）",
        model_name_cn="主成分分析",
        reason="PCA 是最经典、最可靠的线性降维方法。通过正交变换将原始特征转换为互不相关的主成分，保留最大方差方向。",
        pros=["数学基础扎实，理论完备", "结果可复现，速度极快", "可解释每个主成分的方差贡献率", "可作为其他模型的预处理步骤"],
        cons=["只能捕捉线性关系", "对数据缩放敏感（需要标准化）", "主成分不一定有实际含义"],
        alternatives=["TruncatedSVD（稀疏数据版）", "因子分析（Factor Analysis）", "独立成分分析（ICA）"],
        sklearn_class="sklearn.decomposition.PCA",
        difficulty="入门",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 标准化数据：StandardScaler().fit_transform(X)（PCA 对尺度极度敏感，不标准化会导致错误结果）",
            "3. 先不指定 n_components：PCA().fit(X_scaled) → 查看 explained_variance_ratio_ 累积曲线，决定保留多少维度",
            "4. 确定维度：选择保留95%方差的最小维度数，或直接设 n_components=0.95（自动选）",
            "5. 降维：pca = PCA(n_components=选定值).fit_transform(X_scaled) → 得到压缩后的数据",
            "6. 检查：pca.explained_variance_ratio_ 看每个主成分保留了多少信息，pca.components_ 看每个主成分是哪些原始特征的组合",
        ],
        glossary={
            "主成分": "原始特征的线性组合，按方差从大到小排列。第1主成分包含最多的数据变化信息，第2主成分次之，以此类推",
            "方差贡献率": "每个主成分解释了原始数据中百分之多少的变化。如果前3个主成分累计贡献率达到95%，说明压缩到3维只丢失了5%的信息",
            "正交": "主成分之间互不相关（夹角90度），每个主成分抓取的信息不重复，效率最高",
        },
    ),

    "r_dim_nonlinear": Recommendation(
        id="r_dim_nonlinear",
        model_name="自编码器（Autoencoder）",
        model_name_cn="自编码器",
        reason="自编码器用神经网络学习非线性降维，可以捕捉 PCA 无法捕捉的复杂模式，同时保留重构能力。",
        pros=["可以学习任意非线性降维映射", "降维后可以重构回原始数据", "灵活的网络结构设计", "可以用于去噪和异常检测"],
        cons=["需要大量数据和计算资源", "调参复杂", "降维结果难以解释", "可能过拟合"],
        alternatives=["核PCA（Kernel PCA）", "Isomap", "LLE（局部线性嵌入）"],
        sklearn_class="（需使用 PyTorch / TensorFlow）",
        difficulty="高级",
        next_steps=[
            "1. 安装 PyTorch：pip install torch torchvision",
            "2. 标准化数据：StandardScaler().fit_transform(X)，转为 PyTorch Tensor",
            "3. 构建自编码器：编码器（输入维 → 中间层 → 瓶颈层/低维）→ 解码器（瓶颈层 → 中间层 → 输出维），激活函数用 ReLU",
            "4. 训练：用 nn.MSELoss 作为重构损失，Adam 优化器，epoch 建议从50开始，监控重构误差",
            "5. 提取低维表示：训练完成后，只取编码器部分，encoder(X) 得到降维后的数据",
            "6. 验证：用解码器重构回来的数据与原始数据对比，检查重构误差是否可接受",
        ],
        glossary={
            "编码器": "自编码器的前半部分，把高维输入压缩到低维'瓶颈'。就像把一本书压缩成一页摘要",
            "解码器": "自编码器的后半部分，从低维'瓶颈'还原回原始维度。如果还原得好，说明瓶颈层保留了足够的信息",
            "重构误差": "原始数据与解码还原后的数据之间的差异。误差越小说明低维表示保留的信息越完整",
            "瓶颈层": "自编码器最窄的那一层，维度最低，是整个网络的信息瓶颈。降维的结果就是这一层的输出",
        },
    ),

    # ════════════════════════════════════════════════════════
    # 异常检测分支
    # ════════════════════════════════════════════════════════

    "q02_ano": Question(
        id="q02_ano",
        text="你的异常样本有多少？",
        hint="两个条件同时满足才走分类：①异常样本≥20个 ②异常占比≥2%（如10000条数据中至少200条异常）。\n\n你的场景：10000条数据但只有20条异常（占比0.2%）→ 虽然数量达标，但占比不达标 → 走异常检测。",
        options=[
            Option("≥20个异常，且占比≥2%", "异常样本数量够多且比例合理，可以训练二分类器。如500条数据中有20条异常（4%）→ 走分类", "r_ano_supervised"),
            Option("＜20个异常，或占比＜2%", "异常太少或比例太低，分类模型学不到异常模式。如10000条中只有20条异常（0.2%）→ 走异常检测", "r_ano_unsupervised"),
            Option("完全没有标注", "不知道哪些是异常，完全靠算法自己发现。先用One-Class SVM学习正常数据边界，再用少量标注微调", "r_ano_semi"),
        ],
    ),

    "r_ano_supervised": Recommendation(
        id="r_ano_supervised",
        model_name="XGBoost / Random Forest（不平衡分类）",
        model_name_cn="XGBoost / 随机森林（带类别权重）",
        reason="有标注的异常检测本质是不平衡分类问题。XGBoost 和随机森林可以通过设置 class_weight 来处理异常样本极少的情况。",
        pros=["精度高，能利用标注信息", "特征重要性排名，可解释哪些特征与异常相关", "工业界成熟方案"],
        cons=["需要足够多的异常样本标注", "标注成本高", "对未知类型异常可能漏检"],
        alternatives=["LightGBM + 类别权重", "CatBoost", "SMOTE + 分类器"],
        sklearn_class="sklearn.ensemble.RandomForestClassifier(class_weight='balanced')",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install scikit-learn xgboost",
            "2. 检查类别分布：df['label'].value_counts()，确认异常样本占比（通常<5%才算不平衡）",
            "3. 设置类别权重：RandomForestClassifier(class_weight='balanced') 或 XGBClassifier(scale_pos_weight=正常样本数/异常样本数)",
            "4. 拆分时保持类别比例：train_test_split(X, y, stratify=y, test_size=0.2)",
            "5. 训练并评估：不要只看准确率（accuracy），要重点看 precision（精确率）、recall（召回率）、F1-score",
            "6. 调整阈值：model.predict_proba(X_test)[:, 1] 得到异常概率，手动调阈值以平衡 precision 和 recall",
        ],
        glossary={
            "不平衡分类": "正负样本数量差距悬殊的分类问题，如10000笔交易中只有10笔欺诈。普通模型会倾向预测'全部正常'，看似准确率99.9%但完全没用",
            "类别权重": "给少数类（异常样本）更高的权重，让模型更重视它。class_weight='balanced' 自动按样本数反比设定权重",
            "精确率": "预测为异常的样本中，真正异常的比例。Precision=90% 意味着每10个报警中有9个是真异常",
            "召回率": "所有真异常样本中，被模型找出来的比例。Recall=80% 意味着100个异常中漏了20个",
            "F1分数": "精确率和召回率的调和平均，两者都高时F1才高。适合在不平衡分类中综合评价模型",
        },
    ),

    "r_ano_unsupervised": Recommendation(
        id="r_ano_unsupervised",
        model_name="Isolation Forest / LOF",
        model_name_cn="孤立森林 / 局部异常因子",
        reason="孤立森林通过随机划分数据来隔离异常点（异常点更容易被隔离），不需要任何标注，速度快。LOF 通过比较局部密度发现异常。",
        pros=["不需要标注数据", "Isolation Forest 速度极快", "LOF 适合发现局部异常", "对高维数据友好（Isolation Forest）"],
        cons=["对参数敏感", "异常比例需要预估", "对全局异常效果好但局部异常可能漏检"],
        alternatives=["One-Class SVM", "椭圆包络（Elliptic Envelope）", "Autoencoder 重构误差"],
        sklearn_class="sklearn.ensemble.IsolationForest / sklearn.neighbors.LocalOutlierFactor",
        difficulty="入门",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 数据预处理：标准化（StandardScaler），处理缺失值",
            "3. Isolation Forest：IsolationForest(contamination=预估异常比例, random_state=42).fit_predict(X) → 返回1（正常）或-1（异常）",
            "4. LOF：LocalOutlierFactor(n_neighbors=20, contamination=预估异常比例).fit_predict(X) → 同样返回1和-1",
            "5. 对比两种方法：看两者都标记为异常的样本，交集更可信",
            "6. 人工抽查：对标记为异常的样本，人工抽查前20-50个确认是否合理，据此调整 contamination 参数",
        ],
        glossary={
            "异常分数": "模型给每个样本打的异常程度分，分数越高越异常。Isolation Forest 用平均划分次数，LOF 用局部密度比",
            "contamination": "预估数据中异常样本的比例，如设0.05表示预计有5%的数据是异常的。这个参数直接影响检出率",
            "局部密度": "LOF 的核心概念——一个点周围邻居的密集程度。如果某点的密度明显低于邻居，就可能是局部异常",
            "隔离": "Isolation Forest 的核心思想——随机选一个特征，随机选一个切分值，把数据分成两半。异常点离群，切几下就被隔离出来了",
        },
    ),

    "r_ano_semi": Recommendation(
        id="r_ano_semi",
        model_name="One-Class SVM + 少量标注微调",
        model_name_cn="单类支持向量机 + 标注微调",
        reason="先用 One-Class SVM 在正常数据上学习'正常'的边界，再用少量标注的异常样本调整阈值，兼顾无监督和有限监督的优势。",
        pros=["只需正常样本即可训练", "理论基础扎实", "可以结合少量标注提升效果"],
        cons=["对核函数和参数敏感", "大数据集上训练慢", "需要特征缩放"],
        alternatives=["隔离森林 + 标注校准", "深度 SVDD（Deep SVDD）", "半监督自编码器"],
        sklearn_class="sklearn.svm.OneClassSVM",
        difficulty="中等",
        next_steps=[
            "1. 安装 scikit-learn：pip install scikit-learn",
            "2. 数据预处理：标准化（StandardScaler），必须做，One-Class SVM 对尺度极度敏感",
            "3. 只用正常样本训练：OneClassSVM(nu=0.01, kernel='rbf', gamma='scale').fit(X_normal_scaled)",
            "4. 调参 nu：nu 是异常比例的上限，设小一点（0.01-0.05），可通过交叉验证调整",
            "5. 预测：model.predict(X_all) → 返回1（正常）或-1（异常）；model.decision_function(X_all) 得到异常分数",
            "6. 用标注数据校准：根据少量标注的异常样本，调整 decision_function 的阈值，使召回率最大化同时控制误报率",
        ],
        glossary={
            "单类分类": "只用一类数据（正常样本）训练模型，学习'正常'的边界，边界外的都算异常",
            "核函数": "把数据映射到高维空间的数学工具。RBF核（高斯核）最常用，适合非线性边界",
            "nu参数": "One-Class SVM 的核心参数，是异常比例的上限，也是支持向量比例的下限。nu=0.01 表示预计异常不超过1%",
            "支持向量": "最靠近决策边界的那些样本点，是模型学到的关键样本。One-Class SVM 用支持向量勾勒出'正常区域'的边界",
        },
    ),

    # ════════════════════════════════════════════════════════
    # 时间序列分支
    # ════════════════════════════════════════════════════════

    "q02_ts": Question(
        id="q02_ts",
        text="你的时间序列数据有什么特点？",
        hint="不同的时间序列模式需要不同的模型。趋势=长期上升/下降，季节性=固定周期波动（如每年夏季销量高）。\n\n数据量：＞100,000个时间步为很大。",
        options=[
            Option("有明显的趋势和季节性", "数据有规律的上升下降和周期波动，如零售销量", "r_ts_trend"),
            Option("没有明显模式，平稳序列", "数据围绕一个均值波动，如某些金融指标", "r_ts_stationary"),
            Option("有多个外部因素影响", "除了时间，还有天气、促销、节假日等因素影响", "r_ts_exog"),
            Option("数据量很大（>100,000步），模式复杂", "需要深度学习捕捉复杂时间依赖", "r_ts_deep"),
        ],
    ),

    "r_ts_trend": Recommendation(
        id="r_ts_trend",
        model_name="ARIMA / SARIMA",
        model_name_cn="差分整合移动平均自回归模型 / 季节性ARIMA",
        reason="ARIMA 是时间序列预测的经典方法，SARIMA 专门处理带季节性的数据。适合有明显趋势和周期性的单变量预测。",
        pros=["理论基础扎实，统计推断可靠", "参数有明确含义（趋势、季节性、噪声）", "适合短期到中期预测", "实现成熟（statsmodels）"],
        cons=["只能处理单变量（不能加入外部因素）", "需要数据平稳", "长期预测效果下降", "手动调参较繁琐"],
        alternatives=["Prophet（Facebook，全自动）", "Holt-Winters 指数平滑", "Theta 方法"],
        sklearn_class="statsmodels.tsa.arima.model.ARIMA / statsmodels.tsa.statespace.sarimax.SARIMAX",
        difficulty="中等",
        next_steps=[
            "1. 安装依赖：pip install statsmodels pandas matplotlib",
            "2. 检查平稳性：用 adfuller 做 ADF 检验，p<0.05 说明平稳；不平稳则做差分（diff()）直到平稳",
            "3. 画 ACF/PACF 图：plot_acf 和 plot_pacf 来确定 p（AR阶数）、q（MA阶数）",
            "4. 确定 d 值：做了几次差分才平稳，d 就是几",
            "5. 训练模型：ARIMA(order=(p, d, q)).fit() 或 SARIMAX(order=(p,d,q), seasonal_order=(P,D,Q,s)).fit()",
            "6. 预测和评估：model.forecast(steps=预测步数) → 画图对比预测值和实际值，检查残差是否为白噪声",
        ],
        glossary={
            "平稳性": "时间序列的均值、方差、自相关不随时间变化。ARIMA 要求数据平稳，不平稳要先做差分",
            "差分": "当前值减去上一时刻的值，一次差分可以消除线性趋势。如果一次不够，可以做两次差分",
            "ACF/PACF": "自相关函数/偏自相关函数。ACF 图帮助确定 MA 阶数 q（截尾处），PACF 图帮助确定 AR 阶数 p（截尾处）",
            "季节性": "数据中固定周期的重复模式，如每年夏天销量上升、每周一流量增加。SARIMA 额外用 P、D、Q、s 四个参数处理季节性",
            "残差诊断": "检查预测残差（实际值-预测值）是否像白噪声（无规律）。如果残差还有规律，说明模型漏掉了信息",
        },
    ),

    "r_ts_stationary": Recommendation(
        id="r_ts_stationary",
        model_name="ARMA / 指数平滑（Exponential Smoothing）",
        model_name_cn="自回归移动平均 / 指数平滑",
        reason="平稳序列没有趋势和季节性，用简单的 ARMA 或指数平滑即可。指数平滑对近期数据赋予更高权重，直观易懂。",
        pros=["模型简单，计算快", "参数少，容易调参", "短期预测效果好", "指数平滑对近期的变化反应快"],
        cons=["无法捕捉复杂模式", "长期预测趋于常数", "不能处理外部因素"],
        alternatives=["简单移动平均", "Theta 方法", "朴素预测（Naive Forecast）"],
        sklearn_class="statsmodels.tsa.arima.model.ARIMA（设 d=0）/ statsmodels.tsa.holtwinters.SimpleExpSmoothing",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install statsmodels pandas matplotlib",
            "2. 确认平稳性：ADF 检验（adfuller），p<0.05 说明已平稳，可以直接用 ARMA",
            "3. 画 ACF/PACF 图确定 ARMA(p, q) 的 p 和 q 值",
            "4. ARMA 方案：ARIMA(order=(p, 0, q)).fit()（d=0 表示不做差分，即 ARMA）",
            "5. 指数平滑方案：SimpleExpSmoothing(y).fit(smoothing_level=0.2) → 调整 smoothing_level（0~1，越大越看重近期数据）",
            "6. 对比：用 MSE 或 MAE 比较两种方法的预测效果，选择更优的",
        ],
        glossary={
            "自回归": "用过去的值预测未来。AR(1) 表示用昨天的值预测今天，AR(2) 表示用前天和昨天的值预测今天",
            "移动平均": "用过去的预测误差来修正当前预测。不是普通的移动平均，而是对误差的建模",
            "平滑系数": "指数平滑的核心参数，0~1之间。越接近1，近期数据权重越大，模型反应越快但波动也越大",
            "白噪声": "完全随机、无规律可循的序列。好的模型预测残差应该接近白噪声，说明模型已经抓取了所有规律",
        },
    ),

    "r_ts_exog": Recommendation(
        id="r_ts_exog",
        model_name="Prophet / SARIMAX",
        model_name_cn="Prophet（Facebook）/ 带外生变量的SARIMAX",
        reason="Prophet 是 Facebook 开源的自动化时间序列工具，天然支持节假日效应和外部回归变量。SARIMAX 是 ARIMA 的扩展版，支持加入外部因素。",
        pros=["Prophet 全自动，适合业务人员使用", "天然处理节假日、特殊事件", "对缺失值和异常值鲁棒", "可解释性强，分解趋势+季节+节假日"],
        cons=["Prophet 对高频数据（分钟级）效果一般", "无深度学习能力", "可定制性有限"],
        alternatives=["XGBoost（时间特征工程）", "线性回归 + 时间特征"],
        sklearn_class="（需安装 fbprophet / statsmodels.tsa.statespace.sarimax.SARIMAX）",
        difficulty="入门",
        next_steps=[
            "1. 安装依赖：pip install prophet statsmodels pandas",
            "2. Prophet 方案：准备两列 DataFrame——ds（日期列）和 y（数值列），m = Prophet() → m.fit(df) → future = m.make_future_dataframe(periods=预测天数) → forecast = m.predict(future)",
            "3. 添加节假日：m.add_country_holidays(country_name='CN') 加入中国节假日，或自定义特殊日期",
            "4. 添加外部变量：m.add_regressor('price') 加入价格等外生因素",
            "5. 画图：m.plot(forecast) 查看趋势+季节分解，m.plot_components(forecast) 查看各组成部分",
            "6. SARIMAX 方案：SARIMAX(endog=y, exog=X_exog, order=(p,d,q), seasonal_order=(P,D,Q,s)).fit() → 纳入外部变量做预测",
        ],
        glossary={
            "外生变量": "来自时间序列外部的、也会影响预测值的因素，如促销活动、天气、节假日。这些不是时间本身能解释的",
            "节假日效应": "节假日带来的特殊变化，如春节前销量暴增、节后暴跌。Prophet 可以自动建模这些特殊日期的影响",
            "变点": "时间序列中趋势发生明显变化的时间点。Prophet 自动检测变点，允许趋势在不同阶段有不同的斜率",
            "趋势分解": "把时间序列拆成三条线——趋势（长期方向）、季节性（周期波动）、节假日（特殊日期影响），分别看每部分的贡献",
        },
    ),

    "r_ts_deep": Recommendation(
        id="r_ts_deep",
        model_name="LSTM / Transformer",
        model_name_cn="长短期记忆网络 / Transformer",
        reason="大数据+复杂模式，深度学习模型可以捕捉长距离时间依赖和多变量之间的复杂交互。LSTM 是时序经典，Transformer 是近年新趋势。",
        pros=["捕捉超长距离依赖", "多变量输入天然支持", "可以加入注意力机制", "表示学习能力强"],
        cons=["需要海量数据", "训练时间长，计算资源要求高", "完全黑盒，不可解释", "调参极其复杂"],
        alternatives=["TCN（时序卷积网络）", "N-BEATS", "DeepAR"],
        sklearn_class="（需使用 PyTorch / TensorFlow）",
        difficulty="高级",
        next_steps=[
            "1. 安装 PyTorch：pip install torch torchvision",
            "2. 准备序列数据：用滑动窗口法，每 lookback 个时间步的数据预测下一个或多个时间步。标准化所有特征",
            "3. LSTM 方案：构建 nn.LSTM(input_size, hidden_size, num_layers, batch_first=True) → 全连接层输出预测值",
            "4. Transformer 方案：构建 nn.TransformerEncoder + 位置编码 → 全连接层输出预测值",
            "5. 训练：用 nn.MSELoss 或 nn.L1Loss，Adam 优化器，DataLoader 分批训练，监控验证集 loss 防止过拟合",
            "6. 滚动预测：用训练好的模型做多步预测时，把上一步的预测值作为下一步的输入，实现连续预测",
        ],
        glossary={
            "序列到序列": "输入一个序列，输出一个序列。时间序列预测本质就是序列到序列——用历史序列预测未来序列",
            "注意力机制": "让模型自己学习'看哪些历史时刻最重要'。Transformer 的核心创新，比 LSTM 能捕捉更长的依赖关系",
            "时间步": "序列中的一个快照，如'第3天的数据'。lookback=30 表示用过去30个时间步来预测未来",
            "隐藏状态": "LSTM 内部的记忆单元，在读取序列时不断更新，像一条传送带把历史信息传递到后面的时间步",
            "长期依赖": "跨度很远的两个时间点之间的关联，如'去年双十一的促销模式影响今年的定价策略'。LSTM 和 Transformer 擅长捕捉这种长距离依赖",
        },
    ),
}


class MLSelectorEngine:
    """决策引擎：管理问题流和用户回答"""

    def __init__(self):
        self._current_id = "q01_task"
        self._answers: list[dict] = []  # 记录每步的问答

    @property
    def current_node(self) -> Question | Recommendation | None:
        return DECISION_TREE.get(self._current_id)

    @property
    def is_finished(self) -> bool:
        return isinstance(self.current_node, Recommendation)

    @property
    def answers(self) -> list[dict]:
        return self._answers

    def answer(self, option_index: int) -> Question | Recommendation | None:
        """选择一个选项，前进到下一个节点"""
        node = self.current_node
        if not isinstance(node, Question):
            return None
        if option_index < 0 or option_index >= len(node.options):
            return None

        option = node.options[option_index]
        self._answers.append({
            "question": node.text,
            "answer": option.label,
            "desc": option.desc,
        })
        self._current_id = option.next_id
        return self.current_node

    def reset(self):
        self._current_id = "q01_task"
        self._answers = []

    def go_back(self) -> Question | None:
        """回退到上一个问题"""
        if not self._answers:
            return None
        # 弹出最后一条回答
        self._answers.pop()
        # 重新计算当前节点：从第一个问题开始，按剩余回答重放
        self._current_id = "q01_task"
        for a in self._answers:
            node = DECISION_TREE.get(self._current_id)
            if isinstance(node, Question):
                for i, opt in enumerate(node.options):
                    if opt.label == a["answer"]:
                        self._current_id = opt.next_id
                        break
        return DECISION_TREE.get(self._current_id)

    def get_path_summary(self) -> str:
        """获取用户答题路径摘要"""
        lines = []
        for i, a in enumerate(self._answers):
            lines.append(f"  {i+1}. {a['question']} → {a['answer']}")
        return "\n".join(lines)