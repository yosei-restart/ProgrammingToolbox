"""
GUI 元素探查器 - 控件作用知识库
提供每种控件类型的中文功能描述，帮助用户理解控件用途
"""


# 控件类型 → 作用描述
CONTROL_DESCRIPTIONS = {
    "ButtonControl": "按钮：用于触发某个操作或命令，是用户与程序交互最常用的控件。例如「确定」「取消」「提交」等。",
    "EditControl": "文本输入框：允许用户输入和编辑文本内容。常见于登录框、搜索框、表单输入等场景。",
    "CheckBoxControl": "复选框：用于表示二元状态（选中/未选中），允许多选。常用于设置页面中的开关选项。",
    "RadioButtonControl": "单选按钮：在一组互斥的选项中，用户只能选择一个。常用于性别选择、支付方式等场景。",
    "ComboBoxControl": "下拉选择框：点击后展开选项列表，用户从中选择一个。节省界面空间，适合选项较多的场景。",
    "ListControl": "列表：以列表形式展示一组数据项，用户可从中选择一项或多项。常见于文件管理器、设置列表等。",
    "ListItemControl": "列表项：列表中的单个条目，代表一条数据记录。包含文本、图标等信息。",
    "MenuControl": "菜单：弹出式命令列表，用户点击后展开可选的命令项。常见于右键菜单、下拉菜单。",
    "MenuItemControl": "菜单项：菜单中的一个命令选项，点击后执行对应的操作。",
    "TabControl": "选项卡：将多个页面组织在标签页中，用户点击标签切换页面。常用于属性设置、多文档界面。",
    "TabItemControl": "选项卡页：选项卡中的一个页面，包含该页面的所有内容。",
    "TreeControl": "树形控件：以层级树状结构展示数据，节点可展开/折叠。常见于文件目录树、组织架构图。",
    "TreeItemControl": "树节点：树形控件中的一个节点，可以有子节点。",
    "HyperlinkControl": "超链接：可点击的链接文本，点击后跳转到指定URL或执行操作。",
    "TextControl": "静态文本：用于显示不可编辑的文本信息，如标签、说明文字、提示信息等。",
    "ImageControl": "图片：显示图像内容，支持多种图片格式。",
    "ProgressBarControl": "进度条：以可视化方式展示任务完成进度。常见于文件下载、安装过程等场景。",
    "ScrollBarControl": "滚动条：用于滚动查看超出可视区域的内容。分为垂直滚动条和水平滚动条。",
    "SliderControl": "滑块：通过拖动滑块来选择一个范围内的数值。常见于音量调节、亮度调节。",
    "TitleBarControl": "标题栏：窗口顶部的区域，通常显示窗口标题，包含最小化、最大化、关闭按钮。",
    "WindowControl": "窗口：应用程序的主窗口或对话框，是容纳其他控件的顶层容器。",
    "ToolTipControl": "提示框：鼠标悬停时显示的简短提示信息，用于解释控件功能。",
    "DataGridControl": "数据表格：以网格形式展示结构化数据，支持排序、筛选、编辑等操作。",
    "GroupControl": "分组容器：将相关控件组织在一起，通常带有边框和标题。用于界面逻辑分组。",
    "PaneControl": "面板容器：通用的容器控件，用于布局和组织子控件。是最常见的布局容器。",
    "SplitButtonControl": "拆分按钮：包含默认操作的按钮和下拉箭头的组合，点击箭头可展开更多选项。",
    "StatusBarControl": "状态栏：位于窗口底部，显示程序状态信息、进度提示等。",
    "ToolBarControl": "工具栏：包含一组常用命令按钮，方便用户快速执行操作。",
    "SpinnerControl": "数值调节器：通过上下箭头按钮来增加或减少数值，也可直接输入。",
    "ThumbControl": "滚动滑块：滚动条中可拖动的部分，表示当前可视区域的位置。",
    "CalendarControl": "日历：以日历形式展示日期，用户可点击选择日期。",
    "DocumentControl": "文档：展示文档内容，支持文本编辑、排版等功能。常见于富文本编辑器。",
    "HeaderControl": "表头：表格或列表的列标题，点击可排序。",
    "HeaderItemControl": "表头项：表头中的单个列标题。",
    "SeparatorControl": "分隔符：用于在视觉上分隔不同的界面区域或菜单项。",
    "SemanticZoomControl": "缩放控件：支持内容缩放的容器，如地图、图片查看器。",
    "DataItemControl": "数据项：数据表格中的单个数据单元。",
    "CustomControl": "自定义控件：开发者自定义的特殊控件，功能由具体实现决定。",
}


def get_control_description(control_type_name: str) -> str:
    """获取控件类型的作用描述"""
    return CONTROL_DESCRIPTIONS.get(
        control_type_name,
        "此控件类型暂无详细描述。"
    )


def generate_ai_explanation_prompt(control_type_name: str, class_name: str) -> str:
    """
    生成用于向AI大模型请求深入解释的提示词

    Args:
        control_type_name: 控件类型名（如 ButtonControl）
        class_name: 控件类名（如 QPushButton）

    Returns:
        可直接发送给AI的提问文本
    """
    desc = get_control_description(control_type_name)
    return (
        f"请详细解释以下GUI控件的功能、使用场景和常见用法：\n\n"
        f"控件类型：{control_type_name}\n"
        f"控件类名：{class_name}\n"
        f"基本描述：{desc}\n\n"
        f"请从以下方面解释：\n"
        f"1. 该控件在用户界面中的核心作用\n"
        f"2. 常见的使用场景举例\n"
        f"3. 开发时绑定该控件的典型代码示例\n"
        f"4. 该控件通常支持哪些用户交互\n"
        f"5. 使用时需要注意的常见问题"
    )