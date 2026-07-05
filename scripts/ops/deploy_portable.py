#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PonyChat 便携部署脚本
用于初始化项目内便携运行环境。
"""

import os
import sys
import subprocess
import io
from pathlib import Path
from datetime import datetime

# 修复 Windows 控制台编码
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass
    os.system("")  # Enable ANSI colors

# 仓库根目录；嵌入式工具仍在 misc/tools
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MISC = _REPO_ROOT / "misc"
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root

PROJECT_ROOT = resolve_project_root(_REPO_ROOT)
_MISC_DIR = _MISC
os.chdir(PROJECT_ROOT)

# ANSI 颜色
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"

def print_header(text):
    print(f"\n{CYAN}{'='*50}{RESET}")
    print(f"{CYAN}  {text}{RESET}")
    print(f"{CYAN}{'='*50}{RESET}\n")

def print_ok(text):
    print(f"  {GREEN}[OK]{RESET} {text}")

def print_warn(text):
    print(f"  {YELLOW}[!]{RESET}  {text}")

def print_error(text):
    print(f"  {RED}[X]{RESET}  {text}")

def print_info(text):
    print(f"       {text}")


# 工具路径配置 — 统一在 P:\Tools
PYTHON_HOME = Path("P:/Tools/python")
PYTHON_EXE = PYTHON_HOME / "python.exe"
PYTHON_SCRIPTS = PYTHON_HOME / "Scripts"

JDK_HOME = Path("P:/Tools/jdk-17")
JAVA_EXE = JDK_HOME / "bin" / "java.exe"

ANDROID_SDK = Path("P:/Tools/android-sdk")
ADB_EXE = ANDROID_SDK / "platform-tools" / "adb.exe"

GTK_BIN = _MISC_DIR / "tools" / "gtk" / "bin"
GTK_CAIRO_DLL = GTK_BIN / "libcairo-2.dll"

if (PROJECT_ROOT / "android-local" / "app").is_dir():
    APP_DIR = PROJECT_ROOT / "android-local" / "app"
elif (PROJECT_ROOT / "Android-App" / "app").is_dir():
    APP_DIR = PROJECT_ROOT / "Android-App" / "app"
else:
    APP_DIR = PROJECT_ROOT / "app"
GRADLEW = APP_DIR.parent / "gradlew.bat"

if (PROJECT_ROOT / "backend-server" / "backend" / "conf").is_dir():
    CONFIG_DIR = PROJECT_ROOT / "backend-server" / "backend" / "conf"
elif (PROJECT_ROOT / "Backend" / "conf").is_dir():
    CONFIG_DIR = PROJECT_ROOT / "Backend" / "conf"
else:
    CONFIG_DIR = PROJECT_ROOT / "backend" / "conf"
REQUIREMENTS_FILE = CONFIG_DIR / "requirements.txt"


def find_local_python():
    """在项目目录中查找 Python。"""
    # 方案 1: tools/python/python.exe（直接路径）
    if PYTHON_EXE.exists():
        return PYTHON_EXE
    
    # 方案 2: tools/python/python-3.x/python.exe（子目录）
    python_base = _MISC_DIR / "tools" / "python"
    if python_base.exists():
        for d in sorted(python_base.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("python-3."):
                exe = d / "python.exe"
                if exe.exists():
                    return exe
    
    return None


def check_tools():
    """检查内嵌工具。"""
    print_header("检查内嵌工具")
    
    tools_status = {}
    
    # 检查 Python
    python_exe = find_local_python()
    tools_status["Python"] = python_exe is not None
    if python_exe:
        print_ok(f"Python = {python_exe}")
    else:
        print_error("Python = 未找到，请将 Python 放到 misc/tools/python")
    
    # 检查 JDK
    tools_status["JDK"] = JAVA_EXE.exists()
    if JAVA_EXE.exists():
        print_ok(f"JDK-17 = {JAVA_EXE}")
    else:
        print_warn(f"JDK-17 = 未找到 ({JDK_HOME})")
        print_info("说明: JDK 仅在编译 Android App 时需要")
    
    # 检查 Android SDK
    tools_status["SDK"] = ADB_EXE.exists()
    if ADB_EXE.exists():
        print_ok(f"ADB = {ADB_EXE}")
    else:
        print_warn(f"ADB = 未找到 ({ANDROID_SDK})")
        print_info("说明: 便携模式要求提供 misc/tools/android-sdk")
    
    # 检查 Gradle
    tools_status["Gradle"] = GRADLEW.exists()
    if GRADLEW.exists():
        print_ok(f"Gradle = {GRADLEW}")
    else:
        print_warn(f"Gradle = 未找到 ({APP_DIR})")
        print_info("说明: Gradle 仅在 Android App 构建时需要")

    # 检查便携 Cairo 运行时
    tools_status["Cairo"] = GTK_CAIRO_DLL.exists()
    if GTK_CAIRO_DLL.exists():
        print_ok(f"Cairo DLL = {GTK_CAIRO_DLL}")
    else:
        print_warn(f"Cairo DLL = 未找到 ({GTK_CAIRO_DLL})")
        print_info("说明: SVG 自动转码可能回退依赖系统 GTK 运行时")
    
    return tools_status, python_exe


def configure_android_sdk():
    """配置 Android SDK 路径。"""
    print_header("配置 Android SDK")
    
    local_properties = APP_DIR / "local.properties"
    
    # 纯便携模式：仅使用项目内嵌 SDK
    if ANDROID_SDK.exists() and (ANDROID_SDK / "platform-tools").exists():
        sdk_path = ANDROID_SDK
        print_info(f"使用项目内 SDK: {sdk_path}")
    else:
        print_warn("未找到项目内 Android SDK")
        print_info(f"请将 SDK 放到: {ANDROID_SDK}")
        return False
    
    # 写入 local.properties
    sdk_path_str = str(sdk_path).replace("\\", "/")
    
    content = f"""# Android SDK Path Config
# 由 deploy_portable.py 自动生成
# 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

sdk.dir={sdk_path_str}
"""
    
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        local_properties.write_text(content, encoding="utf-8")
        print_ok(f"已写入 {local_properties}")
        print_info(f"SDK 路径 = {sdk_path_str}")
        return True
    except Exception as e:
        print_error(f"写入失败: {e}")
        return False


def configure_gradle_jdk():
    """配置 Gradle JDK 路径。"""
    print_header("配置 Gradle JDK")
    
    # Gradle 工程根在 app 的上级（如 Android-App/gradle.properties）
    gradle_properties = APP_DIR.parent / "gradle.properties"
    
    if not JDK_HOME.exists():
        print_warn(f"未找到 JDK: {JDK_HOME}")
        print_info("已跳过 Gradle JDK 配置")
        return False
    
    jdk_path_str = str(JDK_HOME).replace("\\", "/")
    
    if not gradle_properties.exists():
        print_warn(f"未找到 gradle.properties: {gradle_properties}")
        return False
    
    try:
        content = gradle_properties.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        key_found = False
        
        for line in lines:
            if line.strip().startswith("org.gradle.java.home="):
                new_lines.append(f"org.gradle.java.home={jdk_path_str}")
                key_found = True
            else:
                new_lines.append(line)
        
        if not key_found:
            new_lines.append("")
            new_lines.append("# 自动添加的 JDK 路径")
            new_lines.append(f"org.gradle.java.home={jdk_path_str}")
        
        gradle_properties.write_text("\n".join(new_lines), encoding="utf-8")
        print_ok(f"已更新 {gradle_properties}")
        print_info(f"JDK 路径 = {jdk_path_str}")
        return True
    except Exception as e:
        print_error(f"更新失败: {e}")
        return False


def check_python_dependencies(python_exe):
    """检查 Python 依赖。"""
    print_header("检查 Python 依赖")
    
    if python_exe is None:
        print_warn("未找到 Python，跳过依赖检查")
        return False
    
    # 检查核心依赖
    check_cmd = [
        str(python_exe), "-c",
        "import fastapi, uvicorn, httpx, psutil, PIL, dotenv, aiosqlite"
    ]
    
    result = subprocess.run(check_cmd, capture_output=True)
    
    if result.returncode == 0:
        print_ok("核心依赖已安装")
        return True
    
    # 缺少依赖时自动安装
    print_warn("检测到依赖缺失，正在安装...")
    
    if not REQUIREMENTS_FILE.exists():
        print_error(f"未找到依赖文件: {REQUIREMENTS_FILE}")
        return False
    
    install_cmd = [
        str(python_exe), "-m", "pip", "install",
        "-r", str(REQUIREMENTS_FILE),
        "--quiet"
    ]
    
    result = subprocess.run(install_cmd)
    
    if result.returncode == 0:
        print_ok("依赖安装完成")
        return True
    else:
        print_error("自动安装失败，请手动执行:")
        print_info(f"{python_exe} -m pip install -r {REQUIREMENTS_FILE}")
        return False


def configure_vscode():
    """配置 VSCode。"""
    print_header("配置 VSCode")
    
    vscode_dir = PROJECT_ROOT / ".vscode"
    settings_file = vscode_dir / "settings.json"
    
    if settings_file.exists():
        print_ok("VSCode 配置已存在（使用相对路径）")
        return True
    
    print_info("正在创建 VSCode 配置...")
    
    # 按现有工具生成配置
    settings = {
        "python.terminal.activateEnvironment": False,
        "files.encoding": "utf8"
    }
    
    python_exe = find_local_python()
    if python_exe:
        # 使用相对路径
        rel_path = python_exe.relative_to(PROJECT_ROOT)
        settings["python.defaultInterpreterPath"] = str(rel_path).replace("\\", "/")
    
    if JDK_HOME.exists():
        rel_jdk = JDK_HOME.relative_to(PROJECT_ROOT)
        settings["java.jdt.ls.java.home"] = str(rel_jdk).replace("\\", "/")
    
    try:
        vscode_dir.mkdir(parents=True, exist_ok=True)
        
        import json
        settings_file.write_text(
            json.dumps(settings, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
        print_ok(f"已创建 {settings_file}")
        return True
    except Exception as e:
        print_error(f"创建失败: {e}")
        return False


def show_tool_versions(python_exe):
    """展示工具版本。"""
    print_header("工具版本")
    
    # Python 版本
    if python_exe and python_exe.exists():
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print_info(f"Python: {result.stdout.strip()}")
    
    # Java 版本
    if JAVA_EXE.exists():
        result = subprocess.run(
            [str(JAVA_EXE), "-version"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            # Java 版本输出在 stderr
            version_line = result.stderr.split("\n")[0]
            print_info(f"Java: {version_line}")
    
    # ADB 版本
    if ADB_EXE.exists():
        result = subprocess.run(
            [str(ADB_EXE), "--version"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0]
            print_info(f"ADB: {version_line}")


def main():
    print_header("PonyChat - 便携部署")
    print(f"  项目目录: {PROJECT_ROOT}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 检查工具
    tools_status, python_exe = check_tools()
    
    # 2. 配置 Android SDK
    configure_android_sdk()
    
    # 3. 配置 Gradle JDK
    configure_gradle_jdk()
    
    # 4. 检查 Python 依赖
    check_python_dependencies(python_exe)
    
    # 5. 配置 VSCode
    configure_vscode()
    
    # 6. 显示版本
    show_tool_versions(python_exe)
    
    # 完成
    print_header("部署完成")
    
    print("  环境信息:")
    print(f"    PROJECT_ROOT     = {PROJECT_ROOT}")
    if python_exe:
        print(f"    PYTHON_HOME      = {python_exe.parent}")
    if JDK_HOME.exists():
        print(f"    JAVA_HOME        = {JDK_HOME}")
    if ANDROID_SDK.exists():
        print(f"    ANDROID_SDK_ROOT = {ANDROID_SDK}")
    if GTK_CAIRO_DLL.exists():
        print(f"    GTK_RUNTIME      = {GTK_BIN}")

    return 0


def _pause_if_interactive(no_pause: bool) -> None:
    """独立运行部署脚本时等待回车；被入口 bat 以 --no-pause 调用时跳过，便于链式执行后续步骤。"""
    if not no_pause:
        input("\n按回车退出...")


if __name__ == "__main__":
    no_pause = "--no-pause" in sys.argv
    try:
        code = main()
        _pause_if_interactive(no_pause)
        sys.exit(code)
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}[错误]{RESET} 部署失败: {e}")
        import traceback
        traceback.print_exc()
        _pause_if_interactive(no_pause)
        sys.exit(1)
