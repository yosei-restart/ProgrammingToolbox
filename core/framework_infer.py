"""
GUI 元素探查器 - UI 框架推测引擎
根据控件的类名、FrameworkId、层级特征、进程名推测 UI 框架
"""

# 框架特征库
FRAMEWORK_SIGNATURES = {
    "Electron": {
        "class_patterns": ["Chrome_RenderWidgetHostHWND", "Chrome_WidgetWin_"],
        "framework_ids": ["Win32"],
        "process_patterns": ["Code.exe", "Code", "Discord.exe", "slack.exe", "Feishu.exe", "Lark.exe", "WeChat.exe", "微信", "WeChatAppEx.exe", "notion.exe", "figma.exe", "obsidian.exe"],
        "description": "Electron / CEF（Chromium Embedded Framework）：基于 Chromium 的跨平台桌面应用框架，常见于 VS Code、Discord、Slack、飞书、微信等",
        "code_example": 'const { BrowserWindow } = require("electron");\nconst win = new BrowserWindow({ width: 800, height: 600 });\nwin.loadFile("index.html");',
    },
    "WPF": {
        "class_patterns": ["HwndWrapper"],
        "framework_ids": ["WPF"],
        "process_patterns": ["devenv.exe", "powershell.exe", "PowerShell"],
        "description": "WPF（Windows Presentation Foundation）：微软 .NET 平台的 UI 框架，使用 XAML 描述界面，常见于企业级 Windows 应用",
        "code_example": '<Button x:Name="btnSubmit" Content="提交" Click="BtnSubmit_Click" />',
    },
    "Qt": {
        "class_patterns": ["Qt", "QWidget", "QMainWindow", "QPushButton", "QComboBox"],
        "framework_ids": ["Win32"],
        "process_patterns": ["wps.exe", "VirtualBox.exe", "maya.exe", "qBittorrent.exe", "Telegram.exe"],
        "description": "Qt：跨平台 C++ GUI 框架，常见于专业桌面软件如 WPS、VirtualBox、Autodesk Maya 等",
        "code_example": 'from PySide6.QtWidgets import QPushButton\nbtn = QPushButton("提交", parent)\nbtn.clicked.connect(on_click)',
    },
    "Win32 / MFC": {
        "class_patterns": ["#32770", "Button", "Static", "Edit", "ComboBox", "ListBox", "SysListView32", "SysTreeView32", "MSTaskListWClass", "Shell_TrayWnd"],
        "framework_ids": ["Win32"],
        "process_patterns": ["explorer.exe", "exploreexe", "notepad.exe", "mspaint.exe", "cmd.exe", "taskmgr.exe"],
        "description": "Win32 / MFC：Windows 原生控件，使用 Win32 API 或 MFC 框架创建，常见于系统工具、任务栏、旧版 Windows 应用",
        "code_example": 'HWND hBtn = CreateWindow(L"BUTTON", L"提交", WS_CHILD | WS_VISIBLE, 10, 10, 100, 30, hParent, (HMENU)IDC_BTN, hInst, NULL);',
    },
    "WinUI / UWP": {
        "class_patterns": ["Windows.UI.", "WinUI"],
        "framework_ids": ["Win32", "UWP"],
        "process_patterns": ["ApplicationFrameHost.exe", "SystemSettings.exe"],
        "description": "WinUI / UWP：微软新一代 Windows UI 框架，使用 Fluent Design，常见于 Windows 11 系统应用和 Modern App",
        "code_example": '<Button x:Name="btnSubmit" Content="提交" Click="BtnSubmit_Click" Style="{StaticResource AccentButtonStyle}" />',
    },
    "Windows Forms": {
        "class_patterns": ["WindowsForms10."],
        "framework_ids": ["WinForm"],
        "process_patterns": ["devenv.exe", "sqlserver.exe"],
        "description": "Windows Forms：微软 .NET 平台的经典 UI 框架，使用 C#/VB.NET 开发，常见于传统企业应用",
        "code_example": 'Button btn = new Button() { Text = "提交", Location = new Point(10, 10), Size = new Size(100, 30) };',
    },
    "Java Swing": {
        "class_patterns": ["SunAwtFrame", "SunAwtCanvas"],
        "framework_ids": ["Win32"],
        "process_patterns": ["idea64.exe", "eclipse.exe", "netbeans.exe", "java.exe", "javaw.exe"],
        "description": "Java Swing / AWT：Java 跨平台 GUI 框架，常见于 Java 桌面应用如 IntelliJ IDEA、Eclipse 等",
        "code_example": 'JButton btn = new JButton("提交");\nbtn.setBounds(10, 10, 100, 30);\npanel.add(btn);',
    },
    "Windows Shell": {
        "class_patterns": ["MSTaskListWClass", "Shell_TrayWnd", "ReBarWindow32", "MSTaskSwWClass", "TrayButton"],
        "framework_ids": ["Win32"],
        "process_patterns": ["explorer.exe", "exploreexe"],
        "description": "Windows Shell / 任务栏：Windows 系统外壳界面，包括任务栏、系统托盘、开始菜单等，由 explorer.exe 进程管理",
        "code_example": "// Windows Shell 控件由系统管理，无法直接创建\n// 可通过 ITaskbarList3 等 COM 接口与任务栏交互",
    },
}


# 空值标记
_EMPTY_VALUES = {"(无)", "(未知)", "", None}


def _clean(val: str) -> str:
    """清洗空值标记，返回空字符串"""
    return "" if val in _EMPTY_VALUES else (val or "")


def _match_class(pattern: str, class_name: str) -> bool:
    """检查类名是否匹配模式"""
    pattern_lower = pattern.lower()
    class_lower = (class_name or "").lower()
    return pattern_lower in class_lower


def _match_process(pattern: str, process_name: str) -> bool:
    """检查进程名是否匹配模式"""
    pattern_lower = pattern.lower()
    proc_lower = (process_name or "").lower()
    return pattern_lower in proc_lower


def infer_framework(class_name: str, framework_id: str, parent_chain: list, process_name: str = "") -> dict:
    """
    根据控件特征推测 UI 框架

    Args:
        class_name: 控件类名
        framework_id: UIAutomation 返回的 FrameworkId
        parent_chain: 父级控件层级链
        process_name: 所属进程名

    Returns:
        {
            "framework": "推测的框架名",
            "confidence": "高/中/低",
            "description": "框架描述",
            "code_example": "代码示例",
            "reason": "推测依据",
        }
    """
    # 清洗空值
    class_name = _clean(class_name)
    framework_id = _clean(framework_id)
    process_name = _clean(process_name)

    # 收集所有类名用于匹配
    all_class_names = [class_name]
    if parent_chain:
        for node in parent_chain:
            cn = _clean(node.get("class_name", ""))
            if cn:
                all_class_names.append(cn)

    best_match = None
    best_score = 0

    for fw_name, fw_info in FRAMEWORK_SIGNATURES.items():
        score = 0

        # 1. 检查 framework_id 匹配（权重 3）
        if framework_id and framework_id in fw_info["framework_ids"]:
            score += 3

        # 2. 检查类名模式匹配（权重 5-10）
        for pattern in fw_info["class_patterns"]:
            for cn in all_class_names:
                if _match_class(pattern, cn):
                    if pattern.lower() == cn.lower():
                        score += 10
                    else:
                        score += 5

        # 3. 检查进程名匹配（权重 8）
        if process_name:
            for pattern in fw_info.get("process_patterns", []):
                if _match_process(pattern, process_name):
                    score += 8
                    break

        if score > best_score:
            best_score = score
            best_match = fw_name

    # 确定置信度
    if best_score >= 10:
        confidence = "高"
    elif best_score >= 5:
        confidence = "中"
    else:
        confidence = "低"
        best_match = best_match or "Win32 / MFC"

    fw_info = FRAMEWORK_SIGNATURES.get(best_match, FRAMEWORK_SIGNATURES["Win32 / MFC"])

    # 构建推测依据
    reasons = []
    if framework_id:
        reasons.append(f"FrameworkId={framework_id}")
    if process_name:
        reasons.append(f"进程={process_name}")
    for cn in all_class_names:
        if cn:
            for pattern in fw_info["class_patterns"]:
                if _match_class(pattern, cn):
                    reasons.append(f"类名\"{cn}\"匹配\"{pattern}\"")
                    break
    for pattern in fw_info.get("process_patterns", []):
        if _match_process(pattern, process_name):
            if not any("进程" in r for r in reasons):
                reasons.append(f"进程名\"{process_name}\"匹配\"{pattern}\"")
            break

    return {
        "framework": best_match,
        "confidence": confidence,
        "description": fw_info["description"],
        "code_example": fw_info["code_example"],
        "reason": "；".join(reasons[:3]) if reasons else "根据类名和 FrameworkId 综合推测",
    }