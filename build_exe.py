import subprocess
import sys
import os
import shutil


def build():
    project_root = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(project_root, "assets", "icon.ico")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ProgrammingToolbox",
        "--onefile",
        "--windowed",
        "--icon=" + icon_path,
        "--add-data", f"{icon_path};assets",
        "--clean",
        "--noconfirm",
        "--hidden-import", "uiautomation",
        "--hidden-import", "pynput",
        "--hidden-import", "mss",
        "--hidden-import", "Pillow",
        "--hidden-import", "psutil",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtNetwork",
        "--hidden-import", "PySide6.QtSvg",
        "--collect-all", "PySide6",
        os.path.join(project_root, "main.py"),
    ]
    
    print("🚀 开始打包...")
    print("命令:", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ 打包命令执行成功")
        if result.stdout:
            print("stdout:", result.stdout[:500])
        if result.stderr:
            print("stderr:", result.stderr[:500])
    except subprocess.CalledProcessError as e:
        print("❌ 打包失败:", e)
        if e.stdout:
            print("stdout:", e.stdout)
        if e.stderr:
            print("stderr:", e.stderr)
        sys.exit(1)
    
    dist_dir = os.path.join(project_root, "dist")
    assets_dist = os.path.join(dist_dir, "assets")
    
    os.makedirs(assets_dist, exist_ok=True)
    
    if os.path.exists(icon_path):
        shutil.copy2(icon_path, os.path.join(assets_dist, "icon.ico"))
        print("✅ 资源文件已复制")
    
    exe_path = os.path.join(dist_dir, "ProgrammingToolbox.exe")
    if os.path.exists(exe_path):
        file_size = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n🎉 打包完成！")
        print(f"📁 EXE 文件: {exe_path}")
        print(f"📐 文件大小: {file_size:.1f} MB")
    else:
        print(f"❌ EXE 文件未生成: {exe_path}")
        sys.exit(1)


if __name__ == "__main__":
    build()