"""
安装调试 App - 交互式菜单
功能：检查设备、编译、安装、启动、查看日志等
适用于 PonyChat 项目
"""

import base64
import os
import re
import sys
import subprocess
import platform
import json
from pathlib import Path
from pathlib import PurePosixPath
from datetime import datetime

# ANSI 颜色转义码
if platform.system() == "Windows":
    # Windows 10+ 终端支持 ANSI，但可能需要初始化
    os.system('')

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"

def print_success(msg):
    print(f"{GREEN}✓ {msg}{RESET}")

def print_error(msg):
    print(f"{RED}✗ {msg}{RESET}")

def print_warning(msg):
    print(f"{YELLOW}⚠ {msg}{RESET}")

def print_info(msg):
    print(f"{CYAN}→ {msg}{RESET}")

# 仓库根：misc/tools 位于此目录（与 Backend、Android-App 同级；勿把 Backend/ 当作根）
_p = Path(__file__).resolve().parent
for _ in range(16):
    if (_p / "misc" / "project_paths.py").is_file():
        sys.path.insert(0, str(_p / "misc"))
        break
    if _p.parent == _p:
        raise RuntimeError("未找到 misc/project_paths.py（请确认仓库根目录含 misc/）")
    _p = _p.parent
else:
    raise RuntimeError("未找到 misc/project_paths.py")

from project_paths import resolve_repo_root

PROJECT_ROOT = resolve_repo_root(Path(__file__))
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 应用配置（Android 工程在 Android-App/）
ANDROID_ROOT = PROJECT_ROOT / "Android-App"
GRADLE_KTS = ANDROID_ROOT / "app" / "build.gradle.kts"
APP_PACKAGE = "top.ponychat.webview"
APP_ACTIVITY = "top.ponychat.webview.MainActivity"
APK_PATH = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
APK_RELEASE_PATH = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"


def get_app_version() -> tuple[int, str]:
    """
    从 Android-App/app/build.gradle.kts 读取 versionCode 与 versionName。
    失败时返回 (0, "0.0.0")。
    """
    if not GRADLE_KTS.is_file():
        return 0, "0.0.0"
    try:
        text = GRADLE_KTS.read_text(encoding="utf-8")
    except OSError:
        return 0, "0.0.0"
    m_code = re.search(r"versionCode\s*=\s*(\d+)", text)
    m_name = re.search(r'versionName\s*=\s*"([^"]*)"', text)
    code = int(m_code.group(1)) if m_code else 0
    name = m_name.group(1) if m_name else "0.0.0"
    return code, name


def versioned_apk_filename(prefix: str = "PonyChat", debug: bool = True) -> str:
    """例如 PonyChat-v3.2.2-3-debug.apk"""
    code, name = get_app_version()
    safe_name = name.replace("/", "-").replace("\\", "-")
    kind = "debug" if debug else "release"
    return f"{prefix}-v{safe_name}-{code}-{kind}.apk"


def _parse_semver(s: str) -> tuple[int, int, int]:
    """将 'X.Y.Z' 解析为 (X, Y, Z)，解析失败抛 ValueError。"""
    parts = s.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"版本格式必须为 X.Y.Z，实际: {s!r}")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def bump_version(delta_str: str) -> tuple[int, str] | None:
    """
    将 build.gradle.kts 中的 versionName 加上 delta_str，versionCode +1，写回文件。
    delta_str 格式：'0.0.1' / '0.1.0' / '1.0.0'
    返回新的 (versionCode, versionName)，失败返回 None。
    """
    try:
        da, db, dc = _parse_semver(delta_str)
    except ValueError as e:
        print_error(str(e))
        return None

    cur_code, cur_name = get_app_version()
    try:
        ma, mb, mc = _parse_semver(cur_name)
    except ValueError:
        print_error(f"无法解析当前 versionName: {cur_name!r}")
        return None

    new_a = ma + da
    if da > 0:
        new_b, new_c = 0, 0
    elif db > 0:
        new_b, new_c = mb + db, 0
    else:
        new_b, new_c = mb + db, mc + dc
    new_name = f"{new_a}.{new_b}.{new_c}"
    new_code = cur_code + 1

    text = GRADLE_KTS.read_text(encoding="utf-8")
    text = re.sub(r"(versionCode\s*=\s*)\d+", lambda m: f"{m.group(1)}{new_code}", text)
    text = re.sub(r'(versionName\s*=\s*")[^"]*(")', lambda m: f'{m.group(1)}{new_name}{m.group(2)}', text)
    GRADLE_KTS.write_text(text, encoding="utf-8")

    print_success(f"版本已更新: v{cur_name} (versionCode {cur_code})  →  v{new_name} (versionCode {new_code})")
    return new_code, new_name

IS_WINDOWS = platform.system() == "Windows"

# 全局工具盘（P:\Tools）优先；回退到项目内嵌 misc\tools
_GLOBAL_TOOLS = Path("P:/Tools")


def _resolve_jdk_dir() -> Path:
    """按优先级查找 JDK-17 目录：全局工具盘 → 项目内嵌。"""
    for candidate in (
        _GLOBAL_TOOLS / "jdk-17",
        PROJECT_ROOT / "misc" / "tools" / "jdk-17",
    ):
        if candidate.exists():
            return candidate
    # 均不存在时返回项目内嵌路径（保持原行为，后续 .exists() 判断会给出警告）
    return PROJECT_ROOT / "misc" / "tools" / "jdk-17"


JDK_DIR = _resolve_jdk_dir()
GRADLEW = ANDROID_ROOT / ("gradlew.bat" if IS_WINDOWS else "gradlew")

# 日志保存目录（仓库根 var/applogs/，与 var/ 下其他运行数据并列）
LOGS_DIR = PROJECT_ROOT / "var" / "applogs"

# WiFi 调试历史 IP 存储（最多 5 个）
WIFI_HISTORY_FILE = PROJECT_ROOT / "misc" / "debug" / "debug_wifi_ips.json"
WIFI_HISTORY_MAX = 5

APK_UPLOAD_SERVER = "usa"  # 目标服务器固定为 Server-USA
# 服务器上存放 APK 的目录（与后端 _resolve_apk_path 约定一致）
APK_REMOTE_DEFAULT_DIR = "/opt/ponychat/PonyChat-Website/Main/deploy/releases"

# 最低版本设置配置缓存
MIN_VERSION_CONFIG_FILE = PROJECT_ROOT / "misc" / "debug" / "debug_min_version.json"
# 服务器上 Backend 目录的默认路径
REMOTE_BACKEND_DEFAULT = "/opt/ponychat/Backend"

# [L]/[S] 等：行级黑名单（子串匹配）。仅剔除已观察到的系统/SDK 刷屏行，其余原样保留。
FILTER_PATTERNS = [
    # --- 通用 / Chromium / GPU 探测 ---
    "ViewRootImplStubImpl",   # MIUI 动画日志
    "onAnimationUpdate",       # 动画更新刷屏
    "AdrenoVK",                # GPU shader 警告
    "AudioCapabilities",       # 音频能力检测
    "VideoCapabilities",       # 视频能力检测
    "cr_VAUtil",               # Chromium 视频编解码检测
    "RenderInspector",         # 渲染检查超时
    "getMiuiFreeformStackInfo",# MIUI 窗口信息
    "VRI[",                    # MIUI ViewRootImpl 窗口日志（各 Activity）
    "FrameInsert",             # 帧插入错误
    "ProfileInstaller",        # Profile 安装
    "MIUIInput",               # MIUI 输入事件
    "HandWritingStubImpl",     # 手写输入
    # --- 同进程系统框架（MIUI / AOSP 常见刷屏）---
    "ActivityThread(",         # 进程初始化、TrafficStats 等
    "MiuiDownscaleImpl(",
    "NativeTurboSchedManager(",
    "TurboSchedMonitor(",
    "FramePredict(",
    "WmSystemUiDebug(",
    "ContentCatcherManager(",
    "ContentCatcher(",
    "InsetsSource(",
    "InsetsController(",
    "InsetsPolicy(",
    "DecorViewImmersiveImpl(",
    "MiuiNBIManagerImpl(",
    "DisplayManager(",
    "MiuiMultiWindowUtils(",
    "ImeTracker(",
    "Resume onConfigurationChanged",  # D/Activity 超长 configuration 行
    "SKIA    (",               # CreateGraphicsPipeline / cache
    "/HWUI",                   # pipeline info 等
    "/libEGL",                 # Post task / Run task
    "OpenGLRenderer(",
    "BLASTBufferQueue",
    "SurfaceSyncGroup",
]


def get_adb():
    """
    按优先级查找 adb：全局工具盘 → 项目内嵌 SDK（便携模式）。
    """
    for candidate in (
        _GLOBAL_TOOLS / "android-sdk" / "platform-tools" / "adb.exe",
        PROJECT_ROOT / "misc" / "tools" / "android-sdk" / "platform-tools" / "adb.exe",
    ):
        if candidate.exists():
            return str(candidate)
    # 均不存在时返回全局工具盘期望路径，调用方会给出更明确的错误提示
    return str(_GLOBAL_TOOLS / "android-sdk" / "platform-tools" / "adb.exe")


# 当前选中的设备（用于多设备场景）
SELECTED_DEVICE = None


def get_connected_devices():
    """获取已连接的设备列表，返回 [(device_id, status), ...]"""
    adb = get_adb()
    try:
        result = subprocess.run([adb, "devices"], capture_output=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            return []
        devices = []
        for line in result.stdout.strip().split("\n")[1:]:  # 跳过第一行 "List of devices attached"
            line = line.strip()
            if line and "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append((parts[0], parts[1]))
        return devices
    except Exception:
        return []


def select_device():
    """如果有多个设备，让用户选择一个；如果只有一个，自动选中"""
    global SELECTED_DEVICE
    devices = get_connected_devices()
    
    if not devices:
        print_error("未检测到已连接的 Android 设备")
        SELECTED_DEVICE = None
        return None
    
    if len(devices) == 1:
        SELECTED_DEVICE = devices[0][0]
        print_success(f"已选择设备: {SELECTED_DEVICE}")
        return SELECTED_DEVICE
    
    # 多个设备，让用户选择
    print()
    print("检测到多个设备，请选择要操作的设备：")
    print()
    for i, (device_id, status) in enumerate(devices, 1):
        print(f"  [{i}] {device_id}")
    print()
    
    while True:
        choice = input(f"请输入选项 (1-{len(devices)}): ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(devices):
                SELECTED_DEVICE = devices[idx - 1][0]
                print_success(f"已选择设备: {SELECTED_DEVICE}")
                return SELECTED_DEVICE
        except ValueError:
            pass
        print("无效选项，请重新输入")


def ensure_device_selected():
    """确保已选择设备，如果多设备未选择则自动提示选择。返回 True 表示设备可用，False 表示无设备"""
    global SELECTED_DEVICE
    devices = get_connected_devices()
    
    if not devices:
        print_error("未检测到已连接的 Android 设备")
        SELECTED_DEVICE = None
        return False
    
    if len(devices) == 1:
        # 单设备自动选中
        if SELECTED_DEVICE != devices[0][0]:
            SELECTED_DEVICE = devices[0][0]
            print_info(f"自动选择设备: {SELECTED_DEVICE}")
        return True
    
    # 多设备情况
    if SELECTED_DEVICE:
        # 检查已选设备是否仍然连接
        device_ids = [d[0] for d in devices]
        if SELECTED_DEVICE in device_ids:
            return True
        else:
            print_warning(f"之前选择的设备 {SELECTED_DEVICE} 已断开")
            SELECTED_DEVICE = None
    
    # 多设备且未选择，提示用户选择
    print()
    print("检测到多个设备，请先选择要操作的设备：")
    print()
    for i, (device_id, status) in enumerate(devices, 1):
        print(f"  [{i}] {device_id}")
    print()
    
    while True:
        choice = input(f"请输入选项 (1-{len(devices)}): ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(devices):
                SELECTED_DEVICE = devices[idx - 1][0]
                print_success(f"已选择设备: {SELECTED_DEVICE}")
                print()
                return True
        except ValueError:
            pass
        print("无效选项，请重新输入")


def get_adb_cmd(extra_args=None):
    """获取 ADB 命令列表，如果有选中的设备，自动加上 -s 参数"""
    adb = get_adb()
    cmd = [adb]
    if SELECTED_DEVICE:
        cmd.extend(["-s", SELECTED_DEVICE])
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def _addr_to_ip(addr):
    """从「IP」或「IP:端口」中提取 IP"""
    if not addr or not addr.strip():
        return ""
    s = addr.strip()
    return s.split(":", 1)[0].strip() if ":" in s else s


def load_wifi_history():
    """加载已保存的 WiFi 调试 IP 列表（只存 IP，不存端口；最多 WIFI_HISTORY_MAX 个）"""
    if not WIFI_HISTORY_FILE.exists():
        return []
    try:
        with open(WIFI_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        # 兼容旧数据：历史里可能是 IP:端口，统一只保留 IP
        ips = []
        for item in data[:WIFI_HISTORY_MAX]:
            ip = _addr_to_ip(str(item))
            if ip and ip not in ips:
                ips.append(ip)
        return ips
    except Exception:
        return []


def save_wifi_history(addr):
    """将成功连接的地址加入历史并保存（只存 IP，去重、置顶、最多保留 WIFI_HISTORY_MAX 个）"""
    ip = _addr_to_ip(addr)
    if not ip:
        return
    history = load_wifi_history()
    if ip in history:
        history.remove(ip)
    history.insert(0, ip)
    history = history[:WIFI_HISTORY_MAX]
    try:
        WIFI_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WIFI_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def get_env_with_java():
    """返回带 JAVA_HOME 的环境变量（若存在本地 JDK）"""
    env = os.environ.copy()
    if JDK_DIR.exists():
        env["JAVA_HOME"] = str(JDK_DIR)
    return env


def find_android_sdk():
    """检测 Android SDK 路径：全局工具盘 → 项目内嵌 SDK。"""
    for candidate in (
        _GLOBAL_TOOLS / "android-sdk",
        PROJECT_ROOT / "misc" / "tools" / "android-sdk",
    ):
        if candidate.exists() and (candidate / "platform-tools").exists():
            return candidate
    return None


def ensure_local_properties():
    """确保 App/local.properties 存在且 sdk.dir 指向有效目录，否则尝试检测并写入"""
    prop_file = ANDROID_ROOT / "local.properties"
    current_sdk = None
    if prop_file.exists():
        try:
            for line in prop_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("sdk.dir="):
                    value = line.split("=", 1)[1].strip().replace("\\\\", "\\")
                    if value:
                        p = Path(value)
                        if p.exists() and (p / "platform-tools").exists():
                            return True
                        current_sdk = value
                    break
        except Exception:
            pass
    sdk = find_android_sdk()
    if sdk is None:
        print_error("未找到 Android SDK。请将 SDK 放到以下任意位置之一：")
        print(f"  {_GLOBAL_TOOLS / 'android-sdk'}  （推荐，全局工具盘）")
        print(f"  {PROJECT_ROOT / 'misc' / 'tools' / 'android-sdk'}")
        print("  并确保包含 platform-tools\\adb.exe")
        return False
    # 使用正斜杠，Gradle 在 Windows 上也能识别
    sdk_str = sdk.as_posix() if hasattr(sdk, "as_posix") else str(sdk).replace("\\", "/")
    content = "sdk.dir=" + sdk_str + "\n"
    prop_file.parent.mkdir(parents=True, exist_ok=True)
    prop_file.write_text(content, encoding="utf-8")
    print_info(f"已写入 SDK 路径: {sdk_str}")
    return True


def update_gradle_config():
    """
    更新 gradle.properties 中的 org.gradle.java.home
    确保其指向当前项目内嵌的 tools/jdk-17，实现便携性
    """
    if not JDK_DIR.exists():
        return

    gradle_props_path = ANDROID_ROOT / "gradle.properties"
    if not gradle_props_path.exists():
        return

    # 转换路径格式 (Windows 下必须用正斜杠或双反斜杠)
    jdk_path_str = str(JDK_DIR).replace("\\", "/")

    try:
        new_lines = []
        key_found = False
        
        with open(gradle_props_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            if line.strip().startswith('org.gradle.java.home='):
                new_lines.append(f"org.gradle.java.home={jdk_path_str}\n")
                key_found = True
            else:
                new_lines.append(line)
        
        if not key_found:
            new_lines.append(f"\n# 自动添加的 JDK 路径\norg.gradle.java.home={jdk_path_str}\n")
            
        with open(gradle_props_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            
    except Exception:
        pass


def run(cmd, env=None, check=False, shell=False):
    """执行命令，返回 (returncode, stdout, stderr) 或直接继承终端"""
    if env is None:
        env = os.environ.copy()
    try:
        capture = not (cmd[0] == get_adb() and "logcat" in cmd)
        result = subprocess.run(
            cmd,
            env=env,
            shell=shell,
            check=check,
            capture_output=capture,
            # 使用 UTF-8 编码并忽略无法解码的字符，避免 Windows 下 GBK 解码错误
            encoding='utf-8',
            errors='replace',
        )
        if result.stdout is not None:
            return result.returncode, result.stdout or "", result.stderr or ""
        return result.returncode, "", ""
    except FileNotFoundError:
        return -1, "", "命令未找到"
    except Exception as e:
        return -1, "", str(e)


def section(title):
    """打印分节标题"""
    print()
    print("=" * 40)
    print(title)
    print("=" * 40)
    print()


def check_device():
    """[1] 检查设备连接"""
    section("检查设备连接")
    adb = get_adb()
    code, out, err = run([adb, "devices"])
    if code != 0:
        print_error("ADB 未找到或执行失败")
        print("请检查：")
        print(f"  1. 是否存在 ADB: {_GLOBAL_TOOLS / 'android-sdk' / 'platform-tools' / 'adb.exe'}")
        print(f"     或项目内嵌: misc\\tools\\android-sdk\\platform-tools\\adb.exe")
        print("  2. 设备是否已开启 USB 调试并授权")
        return False
    if out:
        print(out)
    devices = get_connected_devices()
    if not devices:
        print_error("未检测到已连接的 Android 设备")
        print("请检查：")
        print("  1. 手机是否已开启 USB 调试")
        print("  2. 数据线是否支持 USB 传输")
        print("  3. 是否已授权本机进行 USB 调试")
        return False
    print_success(f"已检测到 {len(devices)} 台 Android 设备")
    return True


def build_apk(release=False):
    """[2] 编译 APK"""
    apk_type = "Release" if release else "Debug"
    section(f"编译 {apk_type} APK")
    
    # 更新 Gradle 配置
    update_gradle_config()
    
    if not ensure_local_properties():
        return False
    env = get_env_with_java()
    if JDK_DIR.exists():
        print_info(f"使用 JDK: {JDK_DIR}")
    else:
        print_warning("未检测到本地 Java，使用系统 Java")
    # 停止旧 Gradle 守护进程，避免其仍使用迁移前的 org.gradle.java.home（如 tools/jdk-17）
    try:
        subprocess.run(
            [str(GRADLEW), "--stop"],
            env=env,
            cwd=ANDROID_ROOT,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass
    print("提示: 首次编译会启动 Gradle Daemon 并可能下载依赖，约需 1～3 分钟，请耐心等待。")
    print()
    
    # 编译命令
    task = "assembleRelease" if release else "assembleDebug"
    gradlew_cmd = [str(GRADLEW), task, "--console=plain"]
    print_info(f"正在编译 {apk_type} APK，请稍候...")
    code = subprocess.run(gradlew_cmd, env=env, cwd=ANDROID_ROOT).returncode
    if code != 0:
        print_error(f"APK 编译失败，请检查上述错误信息")
        return False
    
    apk_path = APK_RELEASE_PATH if release else APK_PATH
    if not apk_path.exists():
        print_error(f"APK 文件未找到: {apk_path}")
        return False
    size = apk_path.stat().st_size
    print_success(f"APK 已生成: {apk_path}")
    print(f"文件大小: {size / 1024:.1f} KB")
    return True


def clean_build():
    """清理构建缓存"""
    section("清理构建缓存")
    env = get_env_with_java()
    gradlew_cmd = [str(GRADLEW), "clean", "--console=plain"]
    print_info("正在清理构建缓存...")
    code = subprocess.run(gradlew_cmd, env=env, cwd=ANDROID_ROOT).returncode
    if code == 0:
        print_success("构建缓存已清理")
        return True
    print_error("清理失败")
    return False


def install_apk(release=False):
    """[3] 安装 APK（先尝试更新，失败后再卸载重装）"""
    apk_type = "Release" if release else "Debug"
    section(f"安装 {apk_type} APK")
    if not ensure_device_selected():
        return False
    
    apk_path = APK_RELEASE_PATH if release else APK_PATH
    if not apk_path.exists():
        print_error(f"APK 文件未找到: {apk_path}")
        r = input("是否先编译 APK？(Y/N, 默认 Y): ").strip().upper() or "Y"
        if r == "N":
            print("已取消安装")
            return False
        if not build_apk(release=release):
            return False
    
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    
    # 第一步：尝试覆盖安装（保留用户数据）
    print_info("尝试更新安装（使用 -r 参数覆盖安装）...")
    cmd_update = get_adb_cmd(["install", "-r", str(apk_path)])
    code, out, err = run(cmd_update)
    
    if code == 0 and "Success" in (out + err):
        print_success("APK 更新安装成功（已保留用户数据）")
        return True
    
    # 更新失败，分析错误原因
    msg = (err or out) or ""
    print_warning("更新安装失败，可能是签名不匹配或其他原因")
    if msg:
        print(f"错误信息: {msg[:200]}")  # 只显示前200字符
    
    # 第二步：卸载旧版本后重新安装
    print_info(f"正在卸载旧版本 {APP_PACKAGE}...")
    code_uninstall, _, _ = run(get_adb_cmd(["uninstall", APP_PACKAGE]))
    if code_uninstall == 0:
        print_success("旧版本卸载成功")
    else:
        print_warning("卸载跳过（App 可能尚未安装）")
    
    # 重新安装
    print_info("正在重新安装 APK...")
    cmd_install = get_adb_cmd(["install", str(apk_path)])
    code, out, err = run(cmd_install)
    if code != 0:
        msg = (err or out) or ""
        print_error("APK 安装失败，请检查设备连接与权限")
        if msg:
            print(msg)
        return False
    print_success("APK 已安装（注意：用户数据可能已被清除）")
    return True


def launch_app():
    """[4] 启动应用"""
    section("启动应用")
    if not ensure_device_selected():
        return False
    print_info("正在启动应用...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    code, _, _ = run(get_adb_cmd(["shell", "am", "start", "-n", f"{APP_PACKAGE}/{APP_ACTIVITY}"]))
    if code != 0:
        print_error("启动失败，请检查应用是否已安装、设备是否已连接")
        return False
    print_success("应用已启动")
    return True


def stop_app():
    """[5] 停止应用"""
    section("停止应用")
    if not ensure_device_selected():
        return False
    print_info("正在停止应用...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    code, _, _ = run(get_adb_cmd(["shell", "am", "force-stop", APP_PACKAGE]))
    if code != 0:
        print_error("停止应用失败")
        return False
    print_success("应用已停止")
    return True


def get_app_pid():
    """获取应用的 PID，如果应用未运行则返回 None"""
    code, out, _ = run(get_adb_cmd(["shell", "pidof", APP_PACKAGE]))
    if code == 0 and out.strip():
        # 可能有多个进程，取第一个
        return out.strip().split()[0]
    return None


def view_logs():
    """[L] 查看日志（实时：本进程 logcat + 行级黑名单过滤已知系统刷屏）"""
    section("查看日志（实时）")
    if not ensure_device_selected():
        return False
    
    pid = get_app_pid()
    if pid:
        print_info(f"正在实时显示本应用进程日志 (PID: {pid})，按 Ctrl+C 退出...")
        print("        应用重启后需重新进入此菜单刷新 PID")
    else:
        print_warning("应用未运行，请先启动应用")
        print("        提示：请先选择 [6] 启动应用")
        return False
    
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    print_info("已启用行级黑名单（过滤 Insets/HWUI/SKIA 等已知刷屏；其余 tag 均保留）")
    print("-" * 50)
    
    cmd = get_adb_cmd(["logcat", "-v", "time", "--pid", pid])
    
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        for line in proc.stdout:
            # 检查是否应该过滤此行
            should_filter = any(pattern in line for pattern in FILTER_PATTERNS)
            if not should_filter:
                print(line, end='')
        proc.wait()
    except KeyboardInterrupt:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait()
            except Exception:
                pass
        print("\n已退出日志查看")
    except Exception as e:
        print_error(f"{e}")
    print()
    print("=" * 40)
    print("日志查看已结束")
    print("=" * 40)
    return True


def clear_logs():
    """[7] 清除日志缓冲区"""
    section("清除日志缓冲区")
    if not ensure_device_selected():
        return False
    print_info("正在清除设备日志缓冲区...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    code, _, err = run(get_adb_cmd(["logcat", "-c"]))
    if code != 0:
        print_error("清除日志失败")
        return False
    print_success("日志缓冲区已清除")
    return True


def uninstall_app():
    """[8] 卸载应用"""
    section("卸载应用")
    if not ensure_device_selected():
        return False
    print_warning(f"即将卸载: {APP_PACKAGE}")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    r = input("确认卸载？(Y/N, 默认 N): ").strip().upper() or "N"
    if r != "Y":
        print("已取消卸载")
        return True
    print_info("正在卸载...")
    code, _, _ = run(get_adb_cmd(["uninstall", APP_PACKAGE]))
    if code != 0:
        print_error("卸载失败")
        return False
    print_success("应用已卸载")
    return True


def build_install_launch(release=False):
    """[9] 一键执行（编译 + 安装 + 启动）"""
    apk_type = "Release" if release else "Debug"
    section(f"一键执行（编译+安装+启动 {apk_type}）")
    
    # 先选择设备（如果有多个）
    device = select_device()
    if not device:
        print_error("未选择设备，无法继续")
        return False
    
    if not check_device():
        print_error("设备检查失败，无法继续")
        return False
    if not build_apk(release=release):
        print_error("编译失败，无法继续")
        return False
    if not install_apk(release=release):
        print_error("安装失败，无法继续")
        return False
    if not launch_app():
        print_error("启动失败，无法继续")
        return False
    print()
    print("=" * 40)
    print("一键执行完成")
    print("=" * 40)
    print()
    print("已完成：")
    print_success(f"{apk_type} APK 已编译")
    print_success("APK 已安装")
    print_success("应用已启动")
    print()
    print("可选择选项 6 查看实时日志")
    return True


def take_screenshot():
    """截取设备屏幕"""
    section("截取屏幕")
    if not ensure_device_selected():
        return False
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.png"
    local_path = PROJECT_ROOT / filename
    
    print_info("正在截取屏幕...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    
    # 截图并拉取
    run(get_adb_cmd(["shell", "screencap", "-p", "/sdcard/screen.png"]))
    run(get_adb_cmd(["pull", "/sdcard/screen.png", str(local_path)]))
    run(get_adb_cmd(["shell", "rm", "/sdcard/screen.png"]))
    
    if local_path.exists():
        print_success(f"截图已保存: {local_path}")
        return True
    print_error("截图失败")
    return False


def view_crash_logs():
    """[A] 查看崩溃日志"""
    section("查看崩溃日志")
    if not ensure_device_selected():
        return False
    print_info("正在显示最近的崩溃日志...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    print()
    
    # 获取应用 PID
    pid = get_app_pid()
    if pid:
        # 只显示本应用的错误日志
        cmd = get_adb_cmd(["logcat", "-d", "-v", "time", "--pid", pid, "*:E"])
    else:
        # 应用未运行，显示所有 AndroidRuntime 错误
        cmd = get_adb_cmd(["logcat", "-d", "-v", "time", "AndroidRuntime:E", "*:S"])
    
    code, out, err = run(cmd)
    if out:
        print(out)
    else:
        print_info("未发现崩溃日志")
    print()
    print("=" * 40)
    print("崩溃日志查看完成")
    print("=" * 40)
    print()
    print("提示：如果看到崩溃信息，请检查：")
    print("  1. 应用权限是否已授予")
    print("  2. Android 版本是否兼容")
    print("  3. WebView 是否正常工作")
    return True


def connect_wireless_adb():
    """[W] 连接无线 ADB 设备"""
    global SELECTED_DEVICE
    section("连接无线 ADB 设备")
    
    history = load_wifi_history()
    
    print("无线 ADB 连接方式：")
    print()
    print("  [1] 输入 IP:端口 直接连接（需设备已开启无线调试）")
    print("  [2] 通过配对码配对新设备（Android 11+）")
    print("  [3] 从历史 IP 选择（选后只需输入端口即可连接）")
    if history:
        print("  （有历史时也可直接输入端口，用第一个 IP 连接）")
    print()
    if history:
        for i, ip in enumerate(history, 1):
            print(f"       {i}. {ip}")
        print()
    
    mode = input("请选择 (1/2/3 或直接输入端口): ").strip()
    
    # 直接输入端口：用第一个历史 IP 连接
    # 注意：1/2/3 是菜单选项，不能在这里被当作端口
    if mode.isdigit() and history and mode not in ("1", "2", "3"):
        addr = f"{history[0]}:{mode}"
        print_info(f"正在连接 {addr}...")
        adb = get_adb()
        code, out, err = run([adb, "connect", addr])
        if code == 0 and "connected" in (out + err).lower():
            print_success(f"已连接到 {addr}")
            SELECTED_DEVICE = addr
            save_wifi_history(addr)
            return True
        else:
            print_error("连接失败")
            if out:
                print(out)
            if err:
                print(err)
            return False
    
    if mode == "3":
        # 从历史选择 IP，再输入端口连接
        if not history:
            print_warning("暂无历史 IP，请先用 [1] 或 [2] 连接一次")
            return False
        print()
        for i, ip in enumerate(history, 1):
            print(f"  [{i}] {ip}")
        print()
        choice = input(f"请输入选项 (1-{len(history)}): ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(history):
                ip = history[idx - 1]
                port_in = input("请输入端口 (直接回车使用 5555): ").strip()
                port = port_in if port_in else "5555"
                addr = f"{ip}:{port}"
                print_info(f"正在连接 {addr}...")
                adb = get_adb()
                code, out, err = run([adb, "connect", addr])
                if code == 0 and "connected" in (out + err).lower():
                    print_success(f"已连接到 {addr}")
                    SELECTED_DEVICE = addr
                    save_wifi_history(addr)  # 只存 IP 到历史
                    return True
                else:
                    print_error("连接失败")
                    if out:
                        print(out)
                    if err:
                        print(err)
                    return False
        except ValueError:
            pass
        print_error("无效选项")
        return False
    
    if mode == "1":
        # 直接连接
        print()
        print("请输入设备的 IP 地址和端口（格式：IP:端口，或只输 IP 则用 5555）")
        print("例如：192.168.1.100:5555")
        if history:
            print("提示：有历史 IP 时也可只输入端口（如 32975），将用上一历史 IP 连接")
        print()
        addr = input("IP:端口: ").strip()
        if not addr:
            print("已取消")
            return False
        
        # 解析：可能是「IP:端口」「仅 IP」「仅端口」
        if ":" not in addr:
            if addr.isdigit() and history:
                # 只输入了端口，用历史第一个 IP
                addr = f"{history[0]}:{addr}"
            else:
                # 只输入了 IP，默认端口 5555
                addr += ":5555"
        
        print_info(f"正在连接 {addr}...")
        adb = get_adb()
        code, out, err = run([adb, "connect", addr])
        
        if code == 0 and "connected" in (out + err).lower():
            print_success(f"已连接到 {addr}")
            SELECTED_DEVICE = addr
            save_wifi_history(addr)
            return True
        else:
            print_error("连接失败")
            if out:
                print(out)
            if err:
                print(err)
            return False
    
    elif mode == "2":
        # 配对模式（Android 11+）
        print()
        print("请在手机上：")
        print("  1. 打开 设置 > 开发者选项 > 无线调试")
        print("  2. 点击「使用配对码配对设备」")
        print("  3. 手机上会显示 IP:端口 和 配对码")
        print()
        
        pair_addr = input("配对用 IP:端口: ").strip()
        if not pair_addr:
            print("已取消")
            return False
        
        pair_code = input("配对码: ").strip()
        if not pair_code:
            print("已取消")
            return False
        
        print_info(f"正在配对 {pair_addr}...")
        adb = get_adb()
        
        # 使用 subprocess 直接运行，因为 pair 命令需要交互
        proc = subprocess.Popen(
            [adb, "pair", pair_addr],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace'
        )
        out, err = proc.communicate(input=pair_code + "\n", timeout=30)
        
        if "Successfully paired" in (out + err) or "成功" in (out + err):
            print_success("配对成功！")
            print()
            print("现在需要连接设备。")
            print("请查看手机「无线调试」页面上显示的 IP 地址和端口")
            print("（注意：连接端口和配对端口可能不同）")
            print()
            
            conn_addr = input("连接用 IP:端口: ").strip()
            if conn_addr:
                code, out, err = run([adb, "connect", conn_addr])
                if code == 0 and "connected" in (out + err).lower():
                    print_success(f"已连接到 {conn_addr}")
                    SELECTED_DEVICE = conn_addr
                    save_wifi_history(conn_addr)
                    return True
                else:
                    print_error("连接失败")
                    if out:
                        print(out)
                    if err:
                        print(err)
            return False
        else:
            print_error("配对失败")
            if out:
                print(out)
            if err:
                print(err)
            return False
    
    else:
        print("无效选项")
        return False


def save_logs():
    """[S] 保存日志：本进程 logcat + 与 [L] 相同的行级黑名单"""
    section("保存日志")
    if not ensure_device_selected():
        return False
    
    # 确保日志目录存在
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 获取设备型号
    try:
        adb = get_adb()
        model_cmd = [adb]
        if SELECTED_DEVICE:
            model_cmd.extend(["-s", SELECTED_DEVICE])
        model_cmd.extend(["shell", "getprop", "ro.product.model"])
        model_res = subprocess.run(model_cmd, capture_output=True, text=True)
        device_model = model_res.stdout.strip().replace(" ", "_")
    except:
        device_model = "unknown_device"
    
    # 生成带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"{device_model}_{timestamp}.log"
    
    print_info(f"正在获取设备日志...")
    if SELECTED_DEVICE:
        print_info(f"目标设备: {SELECTED_DEVICE}")
    print_info(f"保存路径: {log_file}")
    
    pid = get_app_pid()
    if pid:
        print_info(f"应用 PID: {pid}，将保存该进程日志（已按黑名单剔除已知刷屏行）")
        cmd = get_adb_cmd(["logcat", "-d", "-v", "time", "--pid", pid])
    else:
        print_warning("应用未运行，将保存设备缓冲区中的全部日志（未按进程过滤）")
        cmd = get_adb_cmd(["logcat", "-d", "-v", "time"])
    print()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            shell=False,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        if result.returncode != 0:
            print_error("获取日志失败")
            if result.stderr:
                print(result.stderr)
            return False
        
        # 过滤刷屏日志
        filtered_lines = []
        for line in result.stdout.splitlines():
            if not any(pattern in line for pattern in FILTER_PATTERNS):
                filtered_lines.append(line)
        
        # 写入文件
        log_file.write_text("\n".join(filtered_lines), encoding="utf-8")
        file_size = log_file.stat().st_size
        print_success(f"日志已保存")
        print(f"文件: {log_file}")
        print(f"大小: {file_size / 1024:.1f} KB")
        if file_size == 0:
            print_warning("日志文件为空，可能设备日志缓冲区已被清除")
        else:
            # 显示日志的前几行作为预览
            lines = filtered_lines[:5]
            if lines:
                print()
                print("日志预览（前5行）：")
                for line in lines:
                    if line.strip():
                        print(f"  {line[:100]}")
    except subprocess.TimeoutExpired:
        print_error("获取日志超时")
        return False
    except Exception as e:
        print_error(f"保存日志文件失败: {e}")
        return False
    
    return True


def read_local_min_version() -> str:
    """从本地 Backend/config.py 读取 MIN_APP_VERSION_NAME 默认值"""
    cfg = PROJECT_ROOT / "Backend" / "config.py"
    if not cfg.is_file():
        return "未知"
    try:
        text = cfg.read_text(encoding="utf-8")
        m = re.search(r'MIN_APP_VERSION_NAME\s*=\s*os\.getenv\([^,]+,\s*"([^"]+)"', text)
        return m.group(1) if m else "未知"
    except Exception:
        return "未知"
