"""
Programming Toolbox (编程工具箱) - 主程序入口

License: GNU Lesser General Public License v3.0 (LGPL-3.0)
详见 LICENSE 文件。

本软件使用了以下第三方库，各库版权归其各自所有者所有：

  Library          License             Copyright Holder
  ---------------  ------------------  --------------------------------
  PySide6          LGPL-3.0            The Qt Company Ltd.
  pynput           LGPL-3.0            Moses Palmer
  uiautomation     HPND                yinkaisheng
  mss              HPND                Mickaël Schoentgen et al.
  Pillow           HPND                Jeffrey A. Clark (Alex) and contributors
  psutil           BSD-3-Clause        Jay Loden, Dave Daeschler, Giampaolo Rodola
  pyperclip        BSD-3-Clause        Al Sweigart
  requests         Apache-2.0          Python Software Foundation
  keyboard         MIT                 BoppreH

各第三方库的完整许可证文本详见 NOTICE.md 和 licenses/ 目录。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.toolbox_main import main

if __name__ == "__main__":
    main()