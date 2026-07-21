<div align="center">

# 🧰 Programming Toolbox

### 编程工具箱 — 一站式 Windows 桌面开发辅助工具集

[![License](https://img.shields.io/badge/License-LGPL%20v3-blue.svg?style=flat-square)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-6.5%2B-41CD52.svg?style=flat-square&logo=qt&logoColor=white)](https://wiki.qt.io/Qt_for_Python)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com)
[![Stars](https://img.shields.io/github/stars/yosei-restart/ProgrammingToolbox?style=flat-square&logo=github)](https://github.com/yosei-restart/ProgrammingToolbox)

**8 大工具 · 1 个工具箱 · 0 成本 · 商用友好**

[功能特性](#-功能特性) · [快速开始](#-快速开始) · [使用说明](USAGE.md) · [打包指南](BUILD.md) 

</div>

---

## 📖 项目简介

**Programming Toolbox（编程工具箱）** 是一款专为 Windows 桌面开发者打造的**集成式辅助工具集**。它将 GUI 控件探查、变量生命周期追踪、函数调用链分析、内存监控、代码差异对比、ML 模型推荐、截图标注和 AI 分析等**8 大常用开发辅助功能**整合到一个工具中，帮助开发者**一键完成日常调试、分析和文档化工作**。

### 💡 为什么选择 Programming Toolbox？

| 传统方式 | Programming Toolbox |
|---------|---------------------|
| 多个工具切换，频繁开窗 | **一个工具箱，8 大功能** |
| 手工把控件信息拼成文本喂给 AI | **一键生成 AI 提示词** |
| 肉眼观察变量变化，凭经验猜测 | **AST + 动态追踪，精确到行** |
| 截图后用画图软件标注 | **热键触发，红框/箭头/文本一键标注** |
| 不知道选什么 ML 模型 | **渐进式问答，自动推荐** |

### 🎯 目标用户

- **GUI 自动化测试工程师**：需要快速识别控件属性和层级
- **桌面应用开发者**：需要调试 UI 框架和控件行为
- **Python 开发者**：需要分析变量生命周期、函数调用关系
- **数据科学家**：需要选择合适的机器学习模型
- **技术支持人员**：需要生成带标注的截图描述问题
- **AI 应用开发者**：需要将控件信息快速转化为 AI 提示词

---

## ✨ 功能特性

### 🔍 工具一：GUI 元素探查器

**点击任意控件，识别类型/属性/层级，生成 AI 提示词**

- 🎯 **全局热键拾取**：按 `Ctrl+F2`（可配置）进入检查模式，点击任意 GUI 控件即可识别
- 📊 **完整属性提取**：类型、类名、名称、AutomationId、位置、尺寸、状态、所属进程、FrameworkId、窗口句柄、支持的 Pattern、Value
- 🌲 **控件层级追溯**：从当前控件向上遍历父级链（最多 30 层），展示完整层级树
- 🎨 **截图标注**：全屏截图（红色高亮边框 + 半透明遮罩 + 标签）+ 控件特写截图
- 🔍 **UI 框架推测**：加权识别 8 种框架（Electron / WPF / Qt / Win32/MFC / WinUI/UWP / Windows Forms / Java Swing / Windows Shell），给出置信度
- 🤖 **AI 提示词生成**：一键生成结构化提示词，直接粘贴到 ChatGPT / DeepSeek / 智谱 AI 等
- 💾 **JSON 导出**：按 schema_version 1.0 输出结构化数据

### � 工具二：变量生命周期追踪器（静态）

**AST 分析变量从诞生到消亡的完整生命周期**

- 🌐 **跨文件追踪**：支持多文件项目，追踪变量跨文件引用
- 📅 **四阶段记录**：诞生（首次定义）/ 赋值（值变化）/ 使用（读取/传参）/ 销毁（作用域结束）
- 📈 **HTML 报告**：导出可视化 HTML 报告，支持代码片段和行号定位
- 🎯 **精确到行**：每个事件精确到源码行号

### 🔄 工具三：变量生命周期追踪器（动态）

**运行程序实时追踪变量值的变化**

- ⚡ **sys.settrace 方案**：基于 Python 官方追踪机制，性能开销低
- 📊 **运行时类型**：记录变量在运行时的真实类型和值
- 🎯 **目标变量过滤**：仅追踪指定变量，避免噪音
- 🔴 **强制停止按钮**：标题栏红色按钮，随时终止追踪
- 📁 **预计算目标文件**：O(1) 集合查找，性能优化

### 🔗 工具四：函数调用链分析器

**AST 分析 Python 源码，构建函数调用关系图**

- 🌲 **双向调用关系**：查看函数的调用链和被调用方
- 📊 **可视化图表**：函数调用关系一目了然
- 📁 **多文件支持**：支持整个项目的函数调用分析

### 📈 工具五：内存使用监控器

**实时监控 Python 进程内存使用**

- 📊 **双指标监控**：RSS（常驻内存）+ VMS（虚拟内存）
- 📈 **实时曲线图**：动态绘制内存使用曲线
- � **瓶颈定位**：快速定位内存泄漏和高占用点

### 📝 工具六：代码差异对比器

**逐行对比两个文件差异**

- 🎨 **三色着色**：新增（绿色）/ 删除（红色）/ 修改（黄色）
- 📋 **左右分栏**：同步滚动，方便对比
- 🔍 **逐行对比**：精确到每一行的变化

### 🧠 工具七：ML 模型选择器

**渐进式问答，推荐最适合的机器学习模型**

- 📋 **6 大任务类型**：分类 / 回归 / 聚类 / 降维 / 异常检测 / 时序预测
- 🎯 **智能推荐**：基于数据规模、样本量、精度要求等多维度评估
- 📊 **量化标准**：明确给出适用场景的数据量阈值
- 💡 **代码示例**：每个推荐模型附带使用示例

### 📷 工具八：快速截图标注

**热键触发全屏截图，红框/箭头/文本标注**

- ⌨️ **热键触发**：全局热键，随时截图
- 🎨 **三种标注**：红框 / 箭头 / 文本框，纯红色 RGB(255,0,0)
- � **文本框缩放**：四角缩放手柄，可移动可调整大小
- 📋 **一键复制**：复制到剪贴板或另存为文件
- 🚫 **任务栏过滤**：截图自动排除任务栏

### 🤖 AI 分析功能（跨工具）

- 🧠 **文字语言模型**：支持 OpenAI / DeepSeek / 智谱 AI / Agnes AI / 本地模型（Ollama / LM Studio）
- 👁️ **图像识别模型**：支持多模态模型，分析截图内容
- 💬 **4 种自定义提示词**：
  - 控件分析（`control_analysis`）
  - 变量分析（`variable_analysis`）
  - 图片分析（`image_analysis`）
  - 图片提示词反推（`image_prompt_reverse`）
- 🔄 **占位符替换**：支持 `{control_info}` / `{variable_name}` / `{events_summary}` 动态数据注入
- ⏱️ **超时重试**：180 秒超时，网络错误自动重试 2 次

---

## 🚀 快速开始

### 方式一：直接下载 EXE（推荐，零配置）

前往 [Releases](https://github.com/yosei-restart/ProgrammingToolbox/releases) 页面下载最新版本的 `ProgrammingToolbox.exe`，**双击即可运行**，无需安装 Python 环境。

### 方式二：源码运行（可二次开发）

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

# 或使用启动脚本
启动.bat
```

> 📖 **详细使用说明**：请参阅 [USAGE.md](USAGE.md)
> 🏗️ **打包指南**：请参阅 [BUILD.md](BUILD.md)

---



## ⚙️ 配置说明

### 热键配置

通过界面"修改热键"按钮或直接编辑 `config.json`：

```json
{
  "modifiers": ["Ctrl"],
  "key": "f2"
}
```

| 字段 | 类型 | 可选值 | 默认值 |
|------|------|--------|--------|
| `modifiers` | string[] | `Ctrl`、`Shift`、`Alt`、`Win` | `["Ctrl"]` |
| `key` | string | 字母或功能键名（小写） | `"f2"` |

### AI 模型配置

在**设置窗口**中配置：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| Base URL | API 地址 | `https://api.deepseek.com/v1` |
| API Key | 密钥（本地存储，不上传） | `sk-****` |
| 模型名称 | 调用的模型 | `deepseek-chat` |
| 网络模型 | 预设供应商 | OpenAI / DeepSeek / 智谱 AI / Agnes AI / 本地 |

**预设供应商**：

| 供应商 | Base URL | 默认模型 |
|--------|----------|---------|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 智谱 AI | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| Agnes AI | `https://api.agnes-ai.com/v1` | `agnes-2.0-flash` |
| 本地 Ollama | `http://localhost:11434/v1` | `qwen2.5` |
| 本地 LM Studio | `http://localhost:1234/v1` | `loaded-model` |

> 🔒 **安全说明**：API Key 存储在用户目录 `~/.gui_inspector/ai_config.json`，**不在项目目录中，不会被上传到 GitHub**。日志中所有密钥均经过脱敏处理（如 `sk-x****6789`）。



---

## 📁 目录结构

```
programming-toolbox/
├── main.py                      # 主程序入口
├── build_exe.py                 # PyInstaller 打包脚本
├── requirements.txt             # 依赖清单
├── 启动.bat                      # Windows 启动脚本
├── README.md                    # 项目介绍（本文件）
├── USAGE.md                     # 详细使用说明书
├── BUILD.md                     # 打包指南
├── LICENSE                      # LGPL-3.0 许可证
├── NOTICE.md                    # 第三方库许可证声明
├── licenses/                    # 各第三方库完整许可证文本
├── .gitignore
├── ai/                          # AI 模块
│   ├── ai_client.py             # AI API 客户端（含超时重试）
│   ├── ai_config.py             # AI 配置管理
│   ├── ai_prompt_generator.py   # AI 提示词生成
│   └── prompts_config.py        # 提示词模板配置
├── core/                        # 核心引擎
│   ├── inspector_engine.py      # 控件识别引擎
│   ├── lifecycle_tracer.py      # 静态变量追踪
│   ├── dynamic_tracer.py        # 动态变量追踪
│   ├── call_chain_analyzer.py   # 函数调用链分析
│   ├── memory_monitor.py        # 内存监控
│   ├── diff_engine.py           # 代码差异对比
│   ├── ml_selector_engine.py    # ML 模型选择引擎
│   ├── framework_infer.py       # UI 框架推测
│   ├── renderer_engine.py       # 截图标注引擎
│   ├── screenshot_engine.py      # 截图引擎
│   └── html_exporter.py         # HTML 报告导出
├── ui/                          # UI 窗口
│   ├── toolbox_main.py          # 工具箱主窗口
│   ├── inspector_window.py      # 控件探查器窗口
│   ├── tracer_window.py         # 静态追踪窗口
│   ├── dynamic_tracer_window.py # 动态追踪窗口
│   ├── call_chain_window.py     # 调用链窗口
│   ├── memory_monitor_window.py # 内存监控窗口
│   ├── diff_window.py           # 差异对比窗口
│   ├── ml_selector_window.py    # ML 选择器窗口
│   ├── screenshot_annotator.py  # 截图标注窗口
│   └── settings_window.py       # 设置窗口
├── utils/                       # 工具类
│   ├── theme.py                 # 主题样式
│   ├── hotkey_handler.py        # 热键处理
│   ├── clipboard_utils.py        # 剪贴板工具
│   ├── control_descriptions.py  # 控件描述库（37 种）
│   └── logging_utils.py         # 日志工具
├── assets/                      # 静态资源
│   ├── icon.ico                 # 应用图标
│   └── icon_source.jpg          # 图标源文件
├── screenshots/                 # 截图输出（运行时生成）
└── logs/                        # 日志输出（运行时生成）
```

---

## 📊 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11（依赖 UIAutomation COM API） |
| Python | 3.10+ |
| 权限 | 普通用户即可运行；拾取管理员权限应用时，本工具也需以管理员权限运行 |
| 磁盘空间 | 源码运行：< 50 MB；打包 EXE：约 250 MB |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

本项目采用 **[LGPLv3](https://www.gnu.org/licenses/lgpl-3.0)** 许可证。



---

## 📧 联系方式

- **GitHub Issues**：[提交 Issue](https://github.com/yosei-restart/ProgrammingToolbox/issues)
- **GitHub Discussions**：[参与讨论](https://github.com/yosei-restart/ProgrammingToolbox/discussions)

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐ Star！**

**Programming Toolbox** — 编程工具箱，让开发更高效

</div>
