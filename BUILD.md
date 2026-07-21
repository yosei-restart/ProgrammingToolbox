# 打包与构建指南

## 📦 两种使用方式

### 方式一：直接下载 EXE（推荐）

前往 [Releases](https://github.com/yosei-restart/ProgrammingToolbox/releases) 页面下载最新版本的 `ProgrammingToolbox.exe`，双击即可运行，无需安装 Python 环境。

### 方式二：源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/yosei-restart/ProgrammingToolbox.git
cd programming-toolbox

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动程序
python main.py
```

## 🏗️ 打包为 EXE

### 环境要求

- Windows 10 / 11
- Python 3.10+
- PyInstaller 5.0+

### 步骤

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 执行打包（推荐使用打包脚本）
python build_exe.py

# 或手动执行：
pyinstaller ^
    --name ProgrammingToolbox ^
    --onefile ^
    --windowed ^
    --icon=assets/icon.ico ^
    --add-data "assets/icon.ico;assets" ^
    --hidden-import uiautomation ^
    --hidden-import pynput ^
    --hidden-import mss ^
    --hidden-import Pillow ^
    --hidden-import psutil ^
    --hidden-import PySide6.QtCore ^
    --hidden-import PySide6.QtGui ^
    --hidden-import PySide6.QtWidgets ^
    --hidden-import PySide6.QtNetwork ^
    main.py
```

### 打包脚本

项目根目录提供 `build_exe.py` 脚本，包含完整的打包配置：

```python
import subprocess
import sys
import os

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ProgrammingToolbox",
        "--onefile",
        "--windowed",
        "--icon=assets/icon.ico",
        "--add-data", "assets/icon.ico;assets",
        "--clean",
        "main.py",
    ]
    subprocess.run(cmd, check=True)
    
    # 复制资源文件到 dist 目录
    dist_dir = os.path.join(os.path.dirname(__file__), "dist")
    os.makedirs(dist_dir, exist_ok=True)
    
    # 复制 icon.ico
    icon_src = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
    icon_dst = os.path.join(dist_dir, "assets", "icon.ico")
    os.makedirs(os.path.dirname(icon_dst), exist_ok=True)
    if os.path.exists(icon_src):
        import shutil
        shutil.copy2(icon_src, icon_dst)
        print("✅ 资源文件已复制")

if __name__ == "__main__":
    build()
    print("✅ 打包完成！EXE 文件位于 dist/ProgrammingToolbox.exe")
```

### 执行打包

```bash
# 使用打包脚本
python build_exe.py

# 打包成功后，EXE 文件位于：
# dist/ProgrammingToolbox.exe
```

### 常见问题

#### 问题 1：打包后运行报错 "ImportError: DLL load failed"

**解决方案**：确保所有依赖已正确安装，特别是 PySide6。

```bash
# 重新安装 PySide6
pip uninstall PySide6 -y
pip install PySide6 --force-reinstall
```

#### 问题 2：打包后运行报错 "ModuleNotFoundError: No module named 'uiautomation'"

**解决方案**：在打包命令中添加 `--hidden-import uiautomation`。

#### 问题 3：EXE 启动后界面显示异常

**解决方案**：
1. 确保系统已安装 VC++ 运行时库（[下载](https://aka.ms/vs/17/release/vc_redist.x64.exe)）
2. 尝试使用 `--windowed` 参数而非 `--console`

#### 问题 4：打包后文件过大

**解决方案**：
1. 使用 `--onefile` 参数打包为单文件
2. 使用 UPX 压缩（需要先安装 UPX）

```bash
# 安装 UPX
# 下载地址：https://upx.github.io/

# 使用 UPX 压缩
pyinstaller --upx-dir=C:\path\to\upx ...
```

## 🚀 发布到 GitHub Releases

### 步骤

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

- 添加 AI 分析功能
- 支持自定义提示词模板
- 新增图像识别模型配置

### 🐛 修复

- 修复控件识别偶尔失败的问题
- 修复截图生成路径错误
- 修复热键冲突

### 📦 下载

- [ProgrammingToolbox.exe](https://github.com/yosei-restart/ProgrammingToolbox/releases/download/v1.0.0/ProgrammingToolbox.exe)

### 📝 使用说明

1. 下载 `ProgrammingToolbox.exe`
2. 双击运行（无需安装）
3. 按 `Ctrl+F2` 进入检查模式
4. 点击目标控件进行识别

### 🔧 技术栈

- Python 3.10+
- PySide6 (Qt6)
- uiautomation
- pynput
- mss
- Pillow

### 📄 许可证

LGPLv3
```

## 📊 打包后的文件结构

```
dist/
├── ProgrammingToolbox.exe    # 主程序（约 50-80 MB）
└── assets/
    └── icon.ico               # 应用图标
```

## 🔧 CI/CD 自动打包（可选）

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
          python-version: '3.10'
          
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

将以上内容保存为 `.github/workflows/build.yml`，每次推送 `v*` 标签时自动打包并上传到 Releases。

---

**提示**：打包后的 EXE 文件大小约 50-80 MB（取决于依赖），首次启动可能需要几秒钟加载。