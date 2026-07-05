#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
键盘适配日志实时监控工具
用于调试 Android WebView 键盘适配问题
"""

import subprocess
import sys
import re
import shutil
import os
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
if str(_MISC) not in sys.path:
    sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root

_PROJECT_ROOT = resolve_project_root(Path(__file__))

# Windows 终端 UTF-8 支持
if sys.platform == 'win32':
    try:
        # 尝试设置终端为 UTF-8
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# ==================== ADB 路径自动检测 ====================
def find_adb_path() -> str:
    """
    自动检测 adb 路径，按以下优先级：
    0. 项目内嵌的 tools/android-sdk (U盘可移植)
    1. 环境变量 PATH
    2. local.properties 中的 SDK 路径
    3. 常见的 Android SDK 安装路径
    """
    # 方案 0: 检查项目内嵌的工具目录 (最高优先级)
    project_adb = _PROJECT_ROOT / "misc" / "tools" / "android-sdk" / "platform-tools" / "adb.exe"
    if project_adb.exists():
        return str(project_adb)
    
    # 方案 1: 检查环境变量 PATH
    adb_in_path = shutil.which("adb")
    if adb_in_path:
        return adb_in_path
    
    # 方案 2: 从 local.properties 读取 SDK 路径
    local_properties = _PROJECT_ROOT / "Android-App" / "app" / "local.properties"
    if local_properties.exists():
        try:
            with open(local_properties, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('sdk.dir='):
                        sdk_path = line.split('=', 1)[1].strip()
                        sdk_path = sdk_path.replace('\\\\', '\\')
                        sdk_path = sdk_path.replace('\\:', ':')
                        adb_path = Path(sdk_path) / "platform-tools" / "adb.exe"
                        if adb_path.exists():
                            return str(adb_path)
        except Exception:
            pass
    
    # 方案 3: 检查常见的 Android SDK 安装路径
    common_paths = [
        Path(os.environ.get('LOCALAPPDATA', '')) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path(os.environ.get('USERPROFILE', '')) / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
    ]
    
    for path in common_paths:
        if path.exists():
            return str(path)
    
    return "adb"


# 全局 ADB 路径
ADB_PATH = find_adb_path()

# 需要过滤的关键词（精简版，只保留核心键盘相关）
KEYWORDS = [
    'Animation ended',
    'imeHeight',
    'cssHeight',
    'keyboard-height',
    'android-keyboard',
    '键盘适配',
    'onImeVisibility',
    'Keyboard:',  # 只匹配我们的日志 tag
    '调试',
    '输入框实际样式',
    'visualViewport',
    '位置监控',
    # 🔧 [编辑模式调试] 新增关键词
    'editing-message',  # body 类名
    'is-editing',       # message-group 类名
    'edit-textarea',    # 编辑框
    'chat-input-area',  # 主输入框
    'body.classList',   # 类名列表
    'computedStyle',    # 计算样式
    'bottom:',          # CSS bottom 属性
    '编辑模式',
]

# 排除这些噪音日志
EXCLUDE_KEYWORDS = [
    'AlarmScheduler',
    'SDM',
    'sensors-hal',
    'ClashMeta',
    'ScanManager',
    'DisplayBase',
    'TIMEOUT',
    'fold',
]

# 编译正则表达式
pattern = re.compile('|'.join(KEYWORDS), re.IGNORECASE)

def main():
    device_id = None
    
    # 检查设备
    print("🔍 正在检测已连接的 Android 设备...")
    print(f"📍 ADB 路径: {ADB_PATH}\n")
    result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')[1:]  # 跳过第一行 "List of devices attached"
    
    devices = []
    for line in lines:
        if line.strip() and 'device' in line:
            device_id = line.split()[0]
            devices.append(device_id)
    
    if not devices:
        print("❌ 未检测到设备，请确保：")
        print("   1. 手机已通过 USB 连接")
        print("   2. 已启用 USB 调试")
        print("   3. 已授权此电脑调试")
        sys.exit(1)
    
    # 多设备选择
    if len(devices) > 1:
        print(f"✅ 检测到 {len(devices)} 个设备:")
        for i, dev in enumerate(devices, 1):
            print(f"   {i}. {dev}")
        
        while True:
            try:
                choice = input("\n请选择设备编号 (1-{}): ".format(len(devices))).strip()
                idx = int(choice) - 1
                if 0 <= idx < len(devices):
                    device_id = devices[idx]
                    break
                else:
                    print(f"⚠️  请输入 1-{len(devices)} 之间的数字")
            except ValueError:
                print("⚠️  请输入有效的数字")
            except KeyboardInterrupt:
                print("\n❌ 已取消")
                sys.exit(0)
    else:
        device_id = devices[0]
        print(f"✅ 检测到 1 个设备: {device_id}")
    
    print(f"📱 使用设备: {device_id}\n")
    
    # 清除旧日志
    print("🧹 清除旧日志...")
    subprocess.run([ADB_PATH, '-s', device_id, 'logcat', '-c'], capture_output=True)
    
    print("")
    print("=" * 70)
    print("🎯 开始实时监控键盘相关日志")
    print("=" * 70)
    print("📝 过滤关键词:", ', '.join(KEYWORDS[:5]), "...")
    print("")
    print("💡 测试步骤:")
    print("   1. 在手机上点击消息编辑按钮")
    print("   2. 观察日志中是否出现 'editing-message' 类名")
    print("   3. 检查 'chat-input-area' 的 bottom 值")
    print("   4. 检查 '--keyboard-height' 变量值")
    print("")
    print("⏹️  按 Ctrl+C 停止监控")
    print("=" * 70)
    print("")
    
    # 启动 logcat 实时监控
    try:
        process = subprocess.Popen(
            [ADB_PATH, '-s', device_id, 'logcat', '-v', 'time'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            # 解码时忽略错误字符
            try:
                line_str = line.decode('utf-8', errors='replace')
            except:
                line_str = line.decode('latin-1', errors='replace')
            
            # 过滤匹配关键词的行，排除噪音
            if pattern.search(line_str):
                # 检查是否是噪音日志
                if any(ex in line_str for ex in EXCLUDE_KEYWORDS):
                    continue
                    
                # 高亮显示关键信息
                if 'Animation ended' in line_str or 'cssHeight' in line_str:
                    print(f"🔑 {line_str.strip()}")
                elif 'Device:' in line_str:
                    print(f"📱 {line_str.strip()}")
                elif 'onImeVisibility' in line_str:
                    print(f"📐 {line_str.strip()}")
                elif 'error' in line_str.lower() or 'Error' in line_str:
                    print(f"❌ {line_str.strip()}")
                else:
                    print(f"📋 {line_str.strip()}")
                    
    except KeyboardInterrupt:
        print("\n")
        print("=" * 70)
        print("⏹️  监控已停止")
        print("=" * 70)
        process.terminate()
        
if __name__ == '__main__':
    main()
