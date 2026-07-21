"""
机器学习模型选择器 — UI 窗口

渐进式问答流程，类似瑞文标准推理测验：
每次只展示一个问题，用户选择后滑入下一步，最终给出推荐。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QProgressBar, QApplication, QSizePolicy, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, get_global_stylesheet, apply_text_selectable
from core.ml_selector_engine import MLSelectorEngine, Question, Recommendation, Option

C = COLORS


class HoverCard(QFrame):
    """悬停卡片 — 鼠标进入时子 QLabel 文字变白，离开时恢复原色

    Qt CSS 的 :hover 伪类只作用于 QFrame 自身，不会级联到子 QLabel。
    因此需要重写 enterEvent/leaveEvent 来手动切换子控件的文字颜色。

    使用 eventFilter【事件过滤器】将子 QLabel 的点击转发到父卡片，
    同时保留 TextSelectableByMouse【文字可选】——用户可拖选复制文字。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = []  # [(QLabel, original_stylesheet), ...]
        self._on_click = None  # 点击回调

    def set_click_callback(self, callback):
        """设置点击回调函数"""
        self._on_click = callback

    def register_label(self, label: QLabel, original_stylesheet: str):
        """注册子 QLabel 及其原始样式，悬停时统一切换"""
        self._labels.append((label, original_stylesheet))
        # 安装事件过滤器，点击转发到父卡片，同时保留文字可选
        label.installEventFilter(self)

    def eventFilter(self, obj, event):
        """子 QLabel 鼠标点击 → 转发到点击回调，返回 False 不消费事件以保留文字选择"""
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._on_click:
                self._on_click()
            return False
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        """QFrame 自身区域点击 → 转发到回调（与 eventFilter 互补）"""
        if event.button() == Qt.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        """鼠标进入：所有子 QLabel 文字变白加粗"""
        for label, _ in self._labels:
            label.setStyleSheet("color:#FFFFFF;background:transparent;font-weight:bold")
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开：恢复原始样式"""
        for label, orig in self._labels:
            label.setStyleSheet(orig)
        super().leaveEvent(event)


class MLSelectorWindow(QWidget):
    """机器学习模型选择器窗口"""

    STEP_COLORS = [
        C["accent"],  # 步骤1
        C["ok"],       # 步骤2
        C["hl"],       # 步骤3
        C["warn"],     # 步骤4
        C["title"],    # 步骤5
    ]

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("机器学习模型选择器")
        self.resize(900, 620)
        self.setMinimumSize(700, 500)
        self._on_back = on_back
        self._engine = MLSelectorEngine()

        self.setStyleSheet(get_global_stylesheet())
        self._build_ui()
        self._show_current()
        apply_text_selectable(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_content(), 1)
        layout.addWidget(self._build_bottom())

    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(50)
        h.setStyleSheet(f"background:{C['head']};border:none")
        hl = QHBoxLayout(h); hl.setContentsMargins(16, 8, 16, 8)
        if self._on_back:
            btn = QPushButton("← 返回工具箱")
            btn.setFont(FONT_SMALL)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['accent']};border:none}}"
            )
            btn.clicked.connect(self.close)
            hl.addWidget(btn)
        t = QLabel("机器学习模型选择器")
        t.setFont(FONT_TITLE); t.setStyleSheet(f"color:{C['accent']};background:transparent")
        hl.addWidget(t); hl.addStretch()

        # 进度指示器
        self._step_label = QLabel("")
        self._step_label.setFont(FONT_SMALL)
        self._step_label.setStyleSheet(f"color:{C['dim']};background:transparent;padding:0 12px")
        hl.addWidget(self._step_label)
        return h

    def _build_content(self):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setStyleSheet(f"QScrollArea{{background:{C['bg']};border:none}}")

        ct = QWidget()
        ct.setStyleSheet(f"background:{C['bg']}")
        self._content_layout = QVBoxLayout(ct)
        self._content_layout.setContentsMargins(24, 20, 24, 20)
        self._content_layout.setSpacing(16)

        # 问题/结果展示区
        self._card = QFrame()
        self._card.setStyleSheet(
            f"QFrame{{background:{C['panel']};border:1px solid {C['border']};border-radius:12px}}"
        )
        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(24, 20, 24, 20)
        self._card_layout.setSpacing(14)
        self._content_layout.addWidget(self._card, 1)

        self._content_layout.addStretch()
        sc.setWidget(ct)
        return sc

    def _build_bottom(self):
        f = QFrame()
        f.setMinimumHeight(60)
        f.setStyleSheet(f"background:{C['panel']};border-top:1px solid {C['border']}")
        bl = QHBoxLayout(f); bl.setContentsMargins(24, 12, 24, 12); bl.setSpacing(12)

        self._btn_reset = QPushButton("重新开始")
        self._btn_reset.setFont(FONT_BODY)
        self._btn_reset.setCursor(Qt.PointingHandCursor)
        self._btn_reset.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['dim']};border:1px solid {C['border']};border-radius:8px;padding:8px 20px;font-weight:bold}} "
            f"QPushButton:hover{{color:{C['fg']};border-color:{C['accent']}}}"
        )
        self._btn_reset.clicked.connect(self._reset)
        bl.addWidget(self._btn_reset)

        self._btn_back = QPushButton("← 上一步")
        self._btn_back.setFont(FONT_BODY)
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['dim']};border:1px solid {C['border']};border-radius:8px;padding:8px 20px;font-weight:bold}} "
            f"QPushButton:hover{{color:{C['accent']};border-color:{C['accent']}}}"
        )
        self._btn_back.clicked.connect(self._go_back)
        bl.addWidget(self._btn_back)

        bl.addStretch()
        return f

    # ================================================================
    # 展示逻辑
    # ================================================================

    def _clear_card(self):
        """清空卡片内容 — 递归清理所有控件和子布局"""
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            self._delete_layout_item(item)

    def _delete_layout_item(self, item):
        """递归删除布局项：控件先隐藏再 deleteLater，子布局递归清理"""
        if item is None:
            return
        w = item.widget()
        if w is not None:
            w.hide()           # 立即隐藏，防止 deleteLater 延迟导致重叠
            w.deleteLater()
            return
        layout = item.layout()
        if layout is not None:
            while layout.count():
                child = layout.takeAt(0)
                self._delete_layout_item(child)
            # 删除 spacer 等非 widget 非 layout 项
            layout_item = item.spacerItem()
            if layout_item is not None:
                pass  # spacer 不需要手动删除

    def _clear_buttons(self):
        """清空底部按钮区（当前仅用于重置/上一步的显隐切换）"""
        pass

    def _show_current(self):
        """根据当前引擎状态展示问题或结果"""
        self._clear_card()
        self._clear_buttons()

        node = self._engine.current_node
        if node is None:
            self._show_error("决策树数据异常，请重新开始")
            return

        if isinstance(node, Question):
            if len(self._engine.answers) == 0:
                self._btn_back.hide()
                self._btn_reset.hide()
            else:
                self._btn_back.show()
                self._btn_reset.show()
            self._show_question(node)
        elif isinstance(node, Recommendation):
            self._show_result(node)

    def _show_question(self, q: Question):
        """展示一个问题"""
        n = len(self._engine.answers) + 1
        self._step_label.setText(f"第 {n} 步")

        # 欢迎页（第1步）
        if n == 1:
            welcome = QFrame()
            welcome.setStyleSheet(
                f"QFrame{{background:{C['input']};border:1px solid {C['accent']};border-radius:12px;padding:20px}}"
            )
            wl = QVBoxLayout(welcome)
            wl.setContentsMargins(20, 20, 20, 20)
            wl.setSpacing(10)

            w_title = QLabel("欢迎使用 ML 模型选择器")
            w_title.setFont(FONT_HEADER)
            w_title.setStyleSheet(f"color:{C['accent']};background:transparent;font-weight:bold")
            w_title.setWordWrap(True)
            wl.addWidget(w_title)

            w_desc = QLabel(
                "机器学习是让计算机从数据中自动学习规律的技术。"
                "不用写复杂的规则，给机器\u201c题目\u201d和\u201c答案\u201d，它就能自己学会做判断。"
                "这个工具会通过几个简单问题，帮你找到最适合你任务的模型。"
                "即使你对机器学习完全不了解，跟着问题一步步回答就行\u2014\u2014每个问题都有通俗的解释。"
            )
            w_desc.setFont(FONT_BODY)
            w_desc.setStyleSheet(f"color:{C['fg']};background:transparent")
            w_desc.setWordWrap(True)
            wl.addWidget(w_desc)

            self._card_layout.addWidget(welcome)

        # 问题标题
        q_title = QLabel(q.text)
        q_title.setFont(FONT_HEADER)
        q_title.setStyleSheet(f"color:{C['fg']};background:transparent;font-weight:bold")
        q_title.setWordWrap(True)
        self._card_layout.addWidget(q_title)

        # 提示说明
        if q.hint:
            hint = QLabel(q.hint)
            hint.setFont(FONT_SMALL)
            hint.setStyleSheet(f"color:{C['dim']};background:transparent;padding:4px 0")
            hint.setWordWrap(True)
            self._card_layout.addWidget(hint)

        # 分类vs异常检测占比计算器（仅在 q01_task 时显示，帮助用户选择分类还是异常检测）
        if q.id == "q01_task":
            calc_frame = QFrame()
            calc_frame.setStyleSheet(
                f"QFrame{{background:{C['bg']};border:1px solid {C['accent']};border-radius:10px;padding:4px}}"
            )
            calc_inner = QHBoxLayout(calc_frame)
            calc_inner.setContentsMargins(14, 12, 14, 12)
            calc_inner.setSpacing(10)

            calc_label = QLabel("不确定选分类还是异常检测？输入数据自动算 →")
            calc_label.setFont(FONT_SMALL)
            calc_label.setStyleSheet(f"color:{C['accent']};background:transparent;font-weight:bold")
            calc_inner.addWidget(calc_label)

            # 总样本数
            calc_inner.addWidget(QLabel("总样本:"))
            self._calc_total = QLineEdit()
            self._calc_total.setPlaceholderText("如 10000")
            self._calc_total.setFixedWidth(80)
            self._calc_total.setMinimumHeight(32)
            self._calc_total.setFont(FONT_SMALL)
            self._calc_total.setStyleSheet(
                f"QLineEdit{{background:#1a3a5c;color:{C['fg']};border:1px solid #2a6090;"
                f"border-radius:6px;padding:4px 8px}}"
            )
            calc_inner.addWidget(self._calc_total)

            # 异常样本数
            calc_inner.addWidget(QLabel("异常数:"))
            self._calc_anomaly = QLineEdit()
            self._calc_anomaly.setPlaceholderText("如 20")
            self._calc_anomaly.setFixedWidth(80)
            self._calc_anomaly.setMinimumHeight(32)
            self._calc_anomaly.setFont(FONT_SMALL)
            self._calc_anomaly.setStyleSheet(
                f"QLineEdit{{background:#6b2020;color:white;border:1px solid #a03030;"
                f"border-radius:6px;padding:4px 8px}}"
            )
            calc_inner.addWidget(self._calc_anomaly)

            # 计算结果
            self._calc_result = QLabel("")
            self._calc_result.setFont(FONT_SMALL)
            self._calc_result.setStyleSheet(f"color:{C['hl']};background:transparent;font-weight:bold")
            self._calc_result.setWordWrap(True)
            self._calc_result.setVisible(False)  # 默认隐藏，有结果时显示
            calc_inner.addWidget(self._calc_result)

            calc_inner.addStretch()
            self._card_layout.addWidget(calc_frame)

            # 连接信号：输入变化时自动计算
            self._calc_total.textChanged.connect(self._on_calc_changed)
            self._calc_anomaly.textChanged.connect(self._on_calc_changed)

        # 分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C['border']}")
        self._card_layout.addWidget(sep)

        # 选项描述卡片 — 网格布局，自适应屏幕宽度，描述是核心
        n_opts = len(q.options)
        cols = 3 if n_opts >= 6 else (2 if n_opts >= 4 else n_opts)
        desc_grid = QGridLayout()
        desc_grid.setSpacing(10)
        for i, opt in enumerate(q.options):
            desc = opt.desc if opt.desc else ""
            opt_card = HoverCard()
            opt_card.setCursor(Qt.PointingHandCursor)
            opt_card.setMinimumHeight(50)
            opt_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            color = self.STEP_COLORS[i % len(self.STEP_COLORS)]
            if desc:
                opt_card.setStyleSheet(
                    f"QFrame{{background:{C['input']};border-left:4px solid {color};"
                    f"border-radius:8px;padding:10px 14px}} "
                    f"QFrame:hover{{background:{color};border-left-color:{C['fg']}}}"
                )
            else:
                opt_card.setStyleSheet(
                    f"QFrame{{background:{C['input']};border:2px solid {color};"
                    f"border-radius:8px;padding:10px 14px}} "
                    f"QFrame:hover{{background:{color}}}"
                )
            opt_card.set_click_callback(lambda idx=i: self._on_answer(idx))

            ol = QVBoxLayout(opt_card)
            ol.setContentsMargins(0, 0, 0, 0)
            ol.setSpacing(4)

            name = QLabel(opt.label)
            name.setFont(FONT_BODY)
            name_style = f"color:{C['fg']};background:transparent;font-weight:bold"
            name.setStyleSheet(name_style)
            opt_card.register_label(name, name_style)
            ol.addWidget(name)

            if desc:
                desc_label = QLabel(desc)
                desc_label.setFont(FONT_SMALL)
                desc_style = f"color:{C['dim']};background:transparent"
                desc_label.setStyleSheet(desc_style)
                desc_label.setWordWrap(True)
                opt_card.register_label(desc_label, desc_style)
                ol.addWidget(desc_label)

            desc_grid.addWidget(opt_card, i // cols, i % cols)
        self._card_layout.addLayout(desc_grid)

        self._card_layout.addStretch()

    def _show_result(self, r: Recommendation):
        """展示推荐结果"""
        self._step_label.setText("结果")
        self._btn_back.hide()
        self._btn_reset.hide()

        # 模型名称标题
        title = QLabel(f"推荐模型：{r.model_name}")
        title.setFont(FONT_TITLE)
        title.setStyleSheet(f"color:{C['accent']};background:transparent;font-weight:bold")
        title.setWordWrap(True)
        self._card_layout.addWidget(title)

        cn = QLabel(r.model_name_cn)
        cn.setFont(FONT_BODY)
        cn.setStyleSheet(f"color:{C['dim']};background:transparent")
        self._card_layout.addWidget(cn)

        # 难度标签
        diff_color = {"入门": C["ok"], "中等": C["warn"], "高级": C["err"]}
        diff = QLabel(f"学习难度：{r.difficulty}")
        diff.setFont(FONT_SMALL)
        diff.setStyleSheet(
            f"color:{diff_color.get(r.difficulty, C['dim'])};background:{C['input']};"
            f"border-radius:6px;padding:4px 12px"
        )
        diff.setFixedWidth(diff.sizeHint().width() + 24)
        self._card_layout.addWidget(diff)

        # 分隔
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C['border']}")
        self._card_layout.addWidget(sep)

        # 推荐理由
        reason_title = QLabel("推荐理由")
        reason_title.setFont(FONT_BODY)
        reason_title.setStyleSheet(f"color:{C['hl']};background:transparent;font-weight:bold")
        self._card_layout.addWidget(reason_title)

        reason = QLabel(r.reason)
        reason.setFont(FONT_BODY)
        reason.setStyleSheet(f"color:{C['fg']};background:transparent")
        reason.setWordWrap(True)
        self._card_layout.addWidget(reason)

        # 优点
        pros_title = QLabel("优点")
        pros_title.setFont(FONT_BODY)
        pros_title.setStyleSheet(f"color:{C['ok']};background:transparent;font-weight:bold")
        self._card_layout.addWidget(pros_title)

        for pro in r.pros:
            p = QLabel(f"  ✓ {pro}")
            p.setFont(FONT_BODY)
            p.setStyleSheet(f"color:{C['fg']};background:transparent")
            p.setWordWrap(True)
            self._card_layout.addWidget(p)

        # 缺点
        cons_title = QLabel("注意事项")
        cons_title.setFont(FONT_BODY)
        cons_title.setStyleSheet(f"color:{C['warn']};background:transparent;font-weight:bold")
        self._card_layout.addWidget(cons_title)

        for con in r.cons:
            c = QLabel(f"  ✗ {con}")
            c.setFont(FONT_BODY)
            c.setStyleSheet(f"color:{C['dim']};background:transparent")
            c.setWordWrap(True)
            self._card_layout.addWidget(c)

        # 备选方案
        if r.alternatives:
            alts = QLabel(f"备选方案：{'、'.join(r.alternatives)}")
            alts.setFont(FONT_SMALL)
            alts.setStyleSheet(
                f"color:{C['accent']};background:{C['input']};border-radius:6px;padding:8px 12px"
            )
            alts.setWordWrap(True)
            self._card_layout.addWidget(alts)

        # sklearn 类名
        if r.sklearn_class:
            sk = QLabel(f"scikit-learn: {r.sklearn_class}")
            sk.setFont(FONT_MONO)
            sk.setStyleSheet(
                f"color:{C['dim']};background:{C['input']};border-radius:6px;padding:8px 12px"
            )
            sk.setWordWrap(True)
            sk.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._card_layout.addWidget(sk)

        # 下一步操作
        if r.next_steps:
            ns_title = QLabel("下一步操作")
            ns_title.setFont(FONT_BODY)
            ns_title.setStyleSheet(f"color:{C['fg']};background:transparent;font-weight:bold")
            self._card_layout.addWidget(ns_title)

            for i, step in enumerate(r.next_steps):
                step_card = QFrame()
                step_card.setStyleSheet(
                    f"QFrame{{background:{C['input']};border:1px solid {C['border']};border-radius:8px;padding:10px 14px}}"
                )
                sl = QHBoxLayout(step_card)
                sl.setContentsMargins(14, 10, 14, 10)
                sl.setSpacing(12)

                num = QLabel(str(i + 1))
                num.setFont(FONT_HEADER)
                num.setStyleSheet(f"color:{C['accent']};background:transparent;font-weight:bold")
                num.setFixedWidth(24)
                sl.addWidget(num)

                step_text = QLabel(step)
                step_text.setFont(FONT_BODY)
                step_text.setStyleSheet(f"color:{C['fg']};background:transparent")
                step_text.setWordWrap(True)
                sl.addWidget(step_text, 1)

                self._card_layout.addWidget(step_card)

        # 术语解释
        if r.glossary:
            gl_title = QLabel("术语解释")
            gl_title.setFont(FONT_BODY)
            gl_title.setStyleSheet(f"color:{C['fg']};background:transparent;font-weight:bold")
            self._card_layout.addWidget(gl_title)

            for term, explanation in r.glossary.items():
                term_card = QFrame()
                term_card.setStyleSheet(
                    f"QFrame{{background:{C['input']};border:1px solid {C['border']};border-radius:6px;padding:8px 12px}}"
                )
                tl = QVBoxLayout(term_card)
                tl.setContentsMargins(12, 8, 12, 8)
                tl.setSpacing(4)

                term_label = QLabel(term)
                term_label.setFont(FONT_BODY)
                term_label.setStyleSheet(f"color:{C['fg']};background:transparent;font-weight:bold")
                tl.addWidget(term_label)

                expl_label = QLabel(explanation)
                expl_label.setFont(FONT_SMALL)
                expl_label.setStyleSheet(f"color:{C['dim']};background:transparent")
                expl_label.setWordWrap(True)
                tl.addWidget(expl_label)

                self._card_layout.addWidget(term_card)

        # 推荐学习路径
        learn_path_text = (
            "推荐学习路径：先用 scikit-learn 跑通你的第一个模型 \u2192 "
            "理解数据预处理（缺失值、标准化）\u2192 学习模型评估（准确率、混淆矩阵）\u2192 "
            "尝试调参（网格搜索）\u2192 进阶到深度学习（PyTorch/TensorFlow）"
        )
        learn_path = QLabel(learn_path_text)
        learn_path.setFont(FONT_SMALL)
        learn_path.setStyleSheet(
            f"color:{C['accent']};background:{C['input']};border-radius:6px;padding:8px 12px"
        )
        learn_path.setWordWrap(True)
        self._card_layout.addWidget(learn_path)

        # 答题路径
        path_title = QLabel("你的选择路径")
        path_title.setFont(FONT_SMALL)
        path_title.setStyleSheet(f"color:{C['dim']};background:transparent;font-weight:bold")
        self._card_layout.addWidget(path_title)

        summary = self._engine.get_path_summary()
        path = QLabel(summary)
        path.setFont(FONT_MONO)
        path.setStyleSheet(
            f"color:{C['dim']};background:{C['input']};border-radius:6px;padding:10px 14px"
        )
        self._card_layout.addWidget(path)

        self._card_layout.addStretch()

        # 底部：重新开始按钮
        btn = QPushButton("重新选择")
        btn.setFont(FONT_BODY)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:{C['head']};border:none;border-radius:8px;padding:10px 28px;font-weight:bold}} "
            f"QPushButton:hover{{background:{C['ahover']}}}"
        )
        btn.clicked.connect(self._reset)
        self._card_layout.addWidget(btn)

    def _show_error(self, msg: str):
        err = QLabel(msg)
        err.setFont(FONT_BODY)
        err.setStyleSheet(f"color:{C['err']};background:transparent")
        self._card_layout.addWidget(err)

    # ================================================================
    # 交互
    # ================================================================

    def _on_answer(self, idx: int):
        self._engine.answer(idx)
        self._show_current()

    def _reset(self):
        self._engine.reset()
        self._show_current()

    def _on_calc_changed(self):
        """异常占比计算器：总样本数和异常数变化时自动计算"""
        total_text = self._calc_total.text().strip()
        anomaly_text = self._calc_anomaly.text().strip()

        if not total_text or not anomaly_text:
            self._calc_result.setText("")
            self._calc_result.setVisible(False)
            return

        try:
            total = int(total_text)
            anomaly = int(anomaly_text)
        except ValueError:
            self._calc_result.setText("请输入整数")
            self._calc_result.setStyleSheet(f"color:{C['err']};background:transparent;font-weight:bold")
            return

        if total <= 0:
            self._calc_result.setText("总样本数必须 > 0")
            self._calc_result.setStyleSheet(f"color:{C['err']};background:transparent;font-weight:bold")
            return

        if anomaly > total:
            self._calc_result.setText("异常数不能大于总样本数")
            self._calc_result.setStyleSheet(f"color:{C['err']};background:transparent;font-weight:bold")
            return

        ratio = anomaly / total * 100
        count_ok = anomaly >= 20
        ratio_ok = ratio >= 2.0

        if count_ok and ratio_ok:
            verdict = "→ 分类"
            color = C['ok']
        else:
            reasons = []
            if not count_ok:
                reasons.append(f"异常数{anomaly}＜20")
            if not ratio_ok:
                reasons.append(f"占比{ratio:.1f}%＜2%")
            verdict = f"→ 异常检测（{'，'.join(reasons)}）"
            color = C['warn']

        self._calc_result.setText(
            f"异常{anomaly}个，占比{ratio:.1f}% {verdict}"
        )
        self._calc_result.setStyleSheet(f"color:{color};background:transparent;font-weight:bold")
        self._calc_result.setVisible(True)

    def _go_back(self):
        node = self._engine.go_back()
        if node is not None:
            self._show_current()

    # ================================================================
    # 窗口关闭处理
    # ================================================================

    def closeEvent(self, event):
        if self._on_back:
            self.hide()
            self._on_back()
            event.ignore()
        else:
            event.accept()