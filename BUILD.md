# 打包与构建指南

## 📦 两种使用方式

### 方式一：直接下载 EXE（推荐）

前往 [Releases](https://github.com/yosei-restart/ProgrammingToolbox/releases) 页面下载最新版本的 `ProgrammingToolbox.exe`，双击即可运行，无需安装 Python 环境。

### 方式二：源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/yosei-restart/ProgrammingToolbox.git
cd ProgrammingToolbox

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动程序
python main.py
```

---

## 🏗️ 打包为 EXE

### 环境要求

- Windows 10 / 11
- Python 3.10+
- PyInstaller 6.0+

### 快速开始

```bash
# 方式一：使用打包脚本（推荐）
python build_exe.py

# 方式二：使用批处理脚本
run_build.bat

# 打包完成后，EXE 文件位于：
# dist/ProgrammingToolbox.exe
```

### 打包脚本说明

项目根目录提供 `build_exe.py` 脚本，包含完整的打包配置：

```python
import subprocess
import sys
import os
import shutil

def build():
    project_root = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(project_root, "assets", "icon.ico")
    
    # 核心/工具/AI/UI 目录作为数据文件打包
    # 供动态追踪器子进程加载模块使用
    core_dir = os.path.join(project_root, "core")
    utils_dir = os.path.join(project_root, "utils")
    ai_dir = os.path.join(project_root, "ai")
    ui_dir = os.path.join(project_root, "ui")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ProgrammingToolbox",
        "--onefile",              # 单文件
        "--windowed",             # 无控制台窗口
        "--icon=" + icon_path,    # 应用图标
        "--add-data", f"{icon_path};assets",
        "--add-data", f"{core_dir};core",      # 核心模块
        "--add-data", f"{utils_dir};utils",    # 工具模块
        "--add-data", f"{ai_dir};ai",          # AI 模块
        "--add-data", f"{ui_dir};ui",          # UI 模块
        "--clean",
        "--noconfirm",
        # 隐藏导入（PyInstaller 无法自动检测的模块）
        "--hidden-import", "uiautomation",
        "--hidden-import", "pynput",
        "--hidden-import", "pynput.keyboard",
        "--hidden-import", "pynput.mouse",
        "--hidden-import", "keyboard",
        "--hidden-import", "mss",
        "--hidden-import", "Pillow",
        "--hidden-import", "psutil",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtNetwork",
        "--hidden-import", "PySide6.QtSvg",
        # 收集所有资源
        "--collect-all", "PySide6",
        "--collect-all", "pynput",
        "--collect-all", "keyboard",
        "--collect-all", "uiautomation",
        os.path.join(project_root, "main.py"),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    
    # 复制图标到 dist/assets
    dist_dir = os.path.join(project_root, "dist")
    assets_dist = os.path.join(dist_dir, "assets")
    os.makedirs(assets_dist, exist_ok=True)
    if os.path.exists(icon_path):
        shutil.copy2(icon_path, os.path.join(assets_dist, "icon.ico"))
```

### 关键打包参数说明

| 参数 | 说明 | 原因 |
|------|------|------|
| `--onefile` | 打包为单个 EXE 文件 | 方便分发，用户双击即用 |
| `--windowed` | 无控制台窗口 | 桌面应用，不显示黑色控制台 |
| `--add-data core/;core` | 将 `core/` 目录作为数据打包 | 动态追踪器子进程需要从 `sys._MEIPASS` 加载 `core.dynamic_tracer` 模块 |
| `--add-data utils/;utils` | 同上 | 日志、主题等工具类 |
| `--add-data ai/;ai` | 同上 | AI 客户端、配置、提示词 |
| `--add-data ui/;ui` | 同上 | UI 模块 |
| `--collect-all PySide6` | 收集 PySide6 全部资源 | 避免运行时缺失 Qt 插件 |
| `--hidden-import uiautomation` | 手动声明隐藏导入 | PyInstaller 无法自动检测动态导入 |

### 打包后的文件结构

```
dist/
├── ProgrammingToolbox.exe    # 主程序（约 250 MB）
└── assets/
    └── icon.ico              # 应用图标（外部副本）
```

> 💡 `--onefile` 模式下，EXE 运行时会将所有内容解压到临时目录（`sys._MEIPASS`），首次启动稍慢（约 3-5 秒）。

---

## ⚠️ 常见问题

### 问题 1：打包后运行报错 "ImportError: DLL load failed"

**解决方案**：确保所有依赖已正确安装，特别是 PySide6。

```bash
# 重新安装 PySide6
pip uninstall PySide6 -y
pip install PySide6 --force-reinstall
```

### 问题 2：打包后运行报错 "ModuleNotFoundError: No module named 'core.dynamic_tracer'"

**原因**：`--onefile` 模式下，`core/dynamic_tracer.py` 被编译进 PYZ 归档，但动态追踪器的子进程（QProcess + 临时脚本）无法从 PYZ 中导入模块。

**解决方案**：使用 `--add-data` 将 `core/`、`utils/`、`ai/`、`ui/` 目录作为数据文件打包，子进程从 `sys._MEIPASS` 临时目录加载。`build_exe.py` 已包含此配置。

### 问题 3：动态追踪器启动后又打开了工具箱主界面

**原因**：`--onefile` 模式下 `sys.executable` 指向 EXE 本身。`_detect_interpreters` 中如果把 EXE 当成 Python 解释器去执行，就会重启整个程序。

**解决方案**：代码中已用 `getattr(sys, 'frozen', False)` 判断是否为打包模式，冻结模式下跳过 `sys.executable` 作为解释器的添加。

### 问题 4：EXE 启动后界面显示异常

**解决方案**：
1. 确保系统已安装 VC++ 运行时库（[下载](https://aka.ms/vs/17/release/vc_redist.x64.exe)）
2. 确认使用 `--windowed` 参数而非 `--console`

### 问题 5：打包后文件过大

**当前大小**：约 250 MB（PySide6 占大部分）

**优化方向（可选）**：
1. 使用 UPX 压缩（需先安装 UPX）
2. 移除不需要的 Qt 模块（如 QtQml、QtQuick 等）
3. 改用 `--onedir` 模式（多文件，但首次启动快）

```bash
# 使用 UPX 压缩
pyinstaller --upx-dir=C:\path\to\upx ...
```

### 问题 6：Windows 防火墙拦截网络访问

**原因**：首次运行时，AI 功能需要访问网络，Windows 防火墙会弹出提示。

**解决方案**：
1. 弹出防火墙提示时，勾选"专用网络"和"公用网络"，点击"允许访问"
2. 或手动在「高级安全 Windows Defender 防火墙」中添加入站规则

---

## 🚀 发布到 GitHub Releases

### 手动发布

1. 创建 GitHub Release：
   - 进入仓库 → Releases → Draft a new release
   - 填写版本号（如 `v1.0.0`）
   - 添加发布说明

2. 上传 EXE 文件：
   - 点击 "Attach binaries by dropping them here or selecting them"
   - 选择 `dist/ProgrammingToolbox.exe`

3. 发布：
   - 点击 "Publish release"

### Release 发布说明模板

```markdown
## 🎉 Programming Toolbox v1.0.0

### ✨ 新功能

- GUI 元素探查器（控件识别 + 截图标注 + AI 提示词）
- 变量生命周期追踪器（静态 AST 分析 + 动态运行时追踪）
- 函数调用链分析器
- 内存使用监控器
- ML 模型选择器
- 快速截图标注（热键触发 + 红框/箭头/文本）
- AI 分析（支持 6 家供应商 + 自定义提示词）

### 🔧 技术栈

- Python 3.10+
- PySide6 (Qt6) - LGPLv3，商用友好
- uiautomation - HPND
- pynput - LGPLv3
- mss - HPND
- Pillow - HPND
- psutil - BSD-3
- requests - Apache-2.0
- keyboard - MIT

### 📦 下载

- [ProgrammingToolbox.exe](https://github.com/yosei-restart/ProgrammingToolbox/releases/download/v1.0.0/ProgrammingToolbox.exe)

### 🚀 使用说明

1. 下载 `ProgrammingToolbox.exe`
2. 双击运行（无需安装）
3. 按 `Ctrl+F2` 进入控件拾取模式
4. 点击目标控件进行识别
```

### CI/CD 自动打包（可选）

可以使用 GitHub Actions 自动打包：

```yaml
name: Build Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller
          
      - name: Build EXE
        run: python build_exe.py
        
      - name: Upload to Release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/ProgrammingToolbox.exe
```

保存为 `.github/workflows/build.yml`，每次推送 `v*` 标签时自动打包并上传到 Releases。

---

**提示**：打包后的 EXE 文件大小约 250 MB，首次启动需要 3-5 秒解压到临时目录。
