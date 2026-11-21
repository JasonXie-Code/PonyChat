

def load_min_version_config() -> dict:
    """加载最低版本设置缓存（远端 Backend 目录）"""
    if not MIN_VERSION_CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(MIN_VERSION_CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_min_version_config(remote_backend_dir: str) -> None:
    """保存远端 Backend 目录路径到缓存"""
    try:
        MIN_VERSION_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        MIN_VERSION_CONFIG_FILE.write_text(
            json.dumps({"remote_backend_dir": _normalize_remote_path(remote_backend_dir)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _normalize_remote_path(path: str) -> str:
    """远端是 Linux 路径；兼容历史缓存/用户输入里的 Windows 反斜杠。"""
    s = str(path or "").strip().replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    if s and not s.startswith("/"):
        s = "/" + s
    return s.rstrip("/") or REMOTE_BACKEND_DEFAULT


def set_min_app_version():
    """[I] 设置服务器可接受的最低 App 版本（更新远端 config.py 中的 MIN_APP_VERSION_NAME）"""
    section("设置服务器最低接受 App 版本")

    serverkeys_dir = PROJECT_ROOT.parent / "ServerKeys"
    if not serverkeys_dir.exists():
        print_error(f"未找到 ServerKeys 目录: {serverkeys_dir}")
        print("请确认 ServerKeys/ 与项目目录同级")
        return False
    if str(serverkeys_dir) not in sys.path:
        sys.path.insert(0, str(serverkeys_dir))
    try:
        from ssh_lib import load_server  # type: ignore
    except ImportError as e:
        print_error(f"无法导入 ssh_lib: {e}")
        return False

    try:
        server = load_server(APK_UPLOAD_SERVER)
    except Exception as e:
        print_error(f"加载服务器配置失败: {e}")
        return False

    print_info(f"目标服务器: {server.label}  ({server.user}@{server.host}:{server.port})")

    current_min = read_local_min_version()
    print_info(f"当前最低版本 (本地 config.py): v{current_min}")
    print()

    new_version = input(
        f"请输入新的最低版本 (格式 X.Y.Z，如 3.1.1) [当前: {current_min}]: "
    ).strip()
    if not new_version:
        print("已取消")
        return False

    try:
        major, _, _ = _parse_semver(new_version)
    except ValueError as e:
        print_error(str(e))
        return False

    print()
    print_info(f"将设置最低接受版本: v{new_version}（MIN_APP_VERSION 整数: {major}）")
    confirm = input("确认？(Y/N, 默认 Y): ").strip().upper() or "Y"
    if confirm != "Y":
        print("已取消")
        return False

    # 远端 Backend 目录（仅作为搜索起点/提示，脚本会自动探测）
    cfg = load_min_version_config()
    last_dir = _normalize_remote_path(cfg.get("remote_backend_dir", REMOTE_BACKEND_DEFAULT))
    raw_dir = input(f"\n远端 Backend 目录 (默认 {last_dir}，留空自动搜索): ").strip()
    remote_backend_dir = _normalize_remote_path(raw_dir if raw_dir else last_dir)
    remote_config_path = f"{remote_backend_dir}/config.py"
    print_info(f"远端配置文件: {remote_config_path}（不存在时将自动搜索）")

    # 构建在服务器上运行的 Python 脚本（base64 传输，避免 shell 转义问题）
    # 若指定路径不存在，自动在服务器上搜索含 MIN_APP_VERSION_NAME 的 config.py
    py_lines = [
        "import re, sys, shutil, subprocess, os",
        f"f = {json.dumps(remote_config_path)}",
        "if not os.path.isfile(f):",
        "    print(f'[INFO] {f} 不存在，自动搜索中...')",
        "    res = subprocess.run(",
        "        ['find', '/root', '/home', '/opt', '/srv', '/var/www', '/app',",
        "         '-maxdepth', '10', '-name', 'config.py'],",
        "        capture_output=True, text=True,",
        "    )",
        "    candidates = []",
        "    for p in res.stdout.strip().splitlines():",
        "        try:",
        "            c = open(p, encoding='utf-8', errors='replace').read()",
        "            if 'MIN_APP_VERSION_NAME' in c:",
        "                candidates.append(p)",
        "        except Exception:",
        "            pass",
        "    if not candidates:",
        "        print('[ERR] 自动搜索未找到含 MIN_APP_VERSION_NAME 的 config.py')",
        "        sys.exit(1)",
        "    f = candidates[0]",
        "    print(f'[INFO] 自动找到: {f}')",
        "try:",
        "    t = open(f, encoding='utf-8').read()",
        "except Exception as e:",
        "    print(f'[ERR] 无法读取: {e}'); sys.exit(1)",
        "name_pat = r'(MIN_APP_VERSION_NAME\\s*=\\s*os\\.getenv\\([^,]+,\\s*\")[^\"]*\"'",
        "code_pat = r'(MIN_APP_VERSION\\s*=\\s*int\\(os\\.getenv\\([^,]+,\\s*\")[^\"]*\"'",
        "t2, n_name = re.subn(name_pat, " + repr(f"\\g<1>{new_version}\"") + ", t)",
        "t2, n_code = re.subn(code_pat, " + repr(f"\\g<1>{major}\"") + ", t2)",
        "if n_name + n_code == 0:",
        "    print('[WARN] 未匹配到配置模式，文件未变更')",
        "    sys.exit(2)",
        "if t2 == t:",
        f"    print('[OK] 服务器最低版本已是 v{new_version}，无需修改')",
        "    print(f'[PATH] {f}')",
        "    sys.exit(0)",
        "shutil.copy2(f, f + '.bak_minver')",
        "open(f, 'w', encoding='utf-8').write(t2)",
        f"print('[OK] 已将服务器最低版本更新为 v{new_version}')",
        "print(f'[PATH] {f}')",
    ]
    py_script = "\n".join(py_lines)
    encoded = base64.b64encode(py_script.encode("utf-8")).decode("ascii")
    bash_script = f"echo '{encoded}' | base64 -d | python3\n"

    print()
    print_info("正在更新远端 config.py ...")
    rc, output = _ssh_bash_s_capture(server, bash_script)

    # 从输出中解析实际使用的路径，并更新本地缓存
    for line in output.splitlines():
        if line.startswith("[PATH] "):
            actual_path = line[len("[PATH] "):].strip()
            actual_dir = str(PurePosixPath(actual_path).parent)
            if actual_dir != remote_backend_dir:
                save_min_version_config(actual_dir)
                print_info(f"已更新缓存路径: {actual_dir}")
            else:
                save_min_version_config(remote_backend_dir)
            break

    already_current = "[OK] 服务器最低版本已是" in output
    if rc == 0 and already_current:
        print_success(f"远端 config.py 最低版本已是 v{new_version}，无需修改")
        return True
    elif rc == 0:
        print_success(f"远端 config.py 最低版本已更新为 v{new_version}")
    elif rc == 2:
        print_warning("远端文件未修改（未匹配到配置模式），请手动检查远端 config.py")
        return False
    else:
        print_error(f"远端更新失败（退出码: {rc}）")
        return False

    # 同步更新本地 config.py（保持本地与远端一致）
    local_config = PROJECT_ROOT / "Backend" / "config.py"
    if local_config.is_file():
        try:
            text = local_config.read_text(encoding="utf-8")
            text = re.sub(
                r'(MIN_APP_VERSION_NAME\s*=\s*os\.getenv\([^,]+,\s*")[^"]*"',
                rf'\g<1>{new_version}"',
                text,
            )
            text = re.sub(
                r'(MIN_APP_VERSION\s*=\s*int\(os\.getenv\([^,]+,\s*")[^"]*"',
                rf'\g<1>{major}"',
                text,
            )
            local_config.write_text(text, encoding="utf-8")
            print_success("本地 config.py 已同步更新")
        except Exception as e:
            print_warning(f"本地 config.py 更新失败（不影响远端）: {e}")

    # 询问是否重启后端
    print()
    print_warning("注意：配置修改需重启后端服务才能生效！")
    r = input("是否立即重启服务器后端？(Y/N, 默认 N): ").strip().upper() or "N"
    if r != "Y":
        print_info("已跳过重启。请稍后手动重启后端以使版本限制生效。")
        return True

    print_info("正在重启后端服务...")
    restart_script = (
        "SERVICE=$(systemctl list-units --type=service --state=loaded --no-legend 2>/dev/null"
        " | awk '{print $1}' | grep -iE 'pony|ponychat' | head -1)\n"
        "if [ -z \"$SERVICE\" ]; then\n"
        "    echo '[WARN] 未检测到 ponychat 相关 systemd 服务，请手动重启'\n"
        "    exit 1\n"
        "fi\n"
        "echo \"[INFO] 检测到服务: $SERVICE\"\n"
        "systemctl restart \"$SERVICE\"\n"
        "systemctl is-active \"$SERVICE\" && echo '[OK] 服务已重启并进入 active 状态'"
        " || echo '[ERR] 重启失败，请手动检查'\n"
    )
    rc_restart, _ = _ssh_bash_s_capture(server, restart_script)
    if rc_restart == 0:
        print_success("后端服务已成功重启，新版本限制即刻生效")
    else:
        print_error(f"后端重启失败（退出码: {rc_restart}），请手动重启")
    return True


def _ssh_bash_s_capture(server, script: str) -> tuple[int, str]:
    """
    通过 bash -s 在远端执行脚本，同时把输出打印到本地终端并捕获为字符串。
    返回 (returncode, combined_output)。
    """
    serverkeys_dir = PROJECT_ROOT.parent / "ServerKeys"
    if str(serverkeys_dir) not in sys.path:
        sys.path.insert(0, str(serverkeys_dir))
    from ssh_lib import prepare_ssh_key, cleanup_temp_key, ssh_common_opts, deploy_upload_env  # type: ignore
    import platform as _platform

    act_key, tmp = prepare_ssh_key(server.key)
    try:
        no_cfg = ["-F", "none"] if _platform.system() == "Windows" else []
        args = (
            ["ssh"] + no_cfg
            + ["-i", str(act_key), "-p", str(server.port)]
            + ssh_common_opts()
            + [server.target, "bash", "-s"]
        )
        result = subprocess.run(
            args,
            input=script.encode("utf-8"),
            capture_output=True,
            env=deploy_upload_env(),
        )
        output = ""
        for stream in (result.stdout, result.stderr):
            if stream:
                text = stream.decode("utf-8", errors="replace")
                print(text, end="")
                output += text
        return result.returncode, output
    finally:
        cleanup_temp_key(tmp)


def build_and_upload_apk():
    """[U] 编译 Release APK 并上传到 Server-USA"""
    section(f"编译 Release APK 并上传到服务器 [{APK_UPLOAD_SERVER}]")

    # 定位 ServerKeys 目录（与项目根同级）
    serverkeys_dir = PROJECT_ROOT.parent / "ServerKeys"
    if not serverkeys_dir.exists():
        print_error(f"未找到 ServerKeys 目录: {serverkeys_dir}")
        print("请确认 ServerKeys/ 与项目目录同级")
        return False

    if str(serverkeys_dir) not in sys.path:
        sys.path.insert(0, str(serverkeys_dir))
    try:
        from ssh_lib import load_server, scp_to, ssh_exec  # type: ignore
    except ImportError as e:
        print_error(f"无法导入 ssh_lib: {e}")
        return False

    try:
        server = load_server(APK_UPLOAD_SERVER)
    except Exception as e:
        print_error(f"加载服务器配置失败: {e}")
        return False

    print_info(f"目标服务器: {server.label}  ({server.user}@{server.host}:{server.port})")

    vcode, vname = get_app_version()
    print_info(f"当前 Gradle 版本: versionName={vname}, versionCode={vcode}")

    # 询问版本增量（直接回车跳过，不修改版本号）
    delta_raw = input(
        f"\n版本增量（格式 X.Y.Z，如 0.0.1 / 0.1.0 / 1.0.0；直接回车保持当前版本）: "
    ).strip()
    if delta_raw:
        result = bump_version(delta_raw)
        if result is None:
            return False
        vcode, vname = result

    auto_name = versioned_apk_filename(debug=False)
    print_info(f"上传文件名: {auto_name}")

    # 远端目录固定，文件名固定为版本化名称。
    remote_dir = APK_REMOTE_DEFAULT_DIR
    print_info(f"远端目标目录: {remote_dir}")
    remote_path = f"{remote_dir}/{auto_name}"

    # 编译 APK：改了版本号必须重新编译；否则询问
    if delta_raw:
        print_info("版本号已变更，强制重新编译...")
        if not build_apk(release=True):
            return False
    elif not APK_RELEASE_PATH.exists():
        print_info("APK 文件不存在，先执行编译...")
        if not build_apk(release=True):
            return False
    else:
        r = input(f"\nAPK 已存在，是否重新编译？(Y/N，默认 N): ").strip().upper() or "N"
        if r == "Y":
            if not build_apk(release=True):
                return False

    if not APK_RELEASE_PATH.exists():
        print_error(f"APK 文件不存在: {APK_RELEASE_PATH}")
        return False

    # 确保远端目录存在
    print_info(f"确认远端目录: {remote_dir}")
    mkdir_rc = ssh_exec(server, f"mkdir -p {remote_dir}")
    if mkdir_rc != 0:
        print_error(f"远端目录创建失败（exit {mkdir_rc}），请检查服务器权限")
        return False

    # 上传
    size = APK_RELEASE_PATH.stat().st_size
    print()
    print_info(f"正在上传 {APK_RELEASE_PATH.name}  ({size / 1024:.1f} KB)")
    print_info(f"远端路径: {server.user}@{server.host}:{remote_path}")
    print()

    try:
        rc = scp_to(server, APK_RELEASE_PATH, remote_path)
    except Exception as e:
        print_error(f"上传异常: {e}")
        return False

    if rc != 0:
        print_error(f"上传失败（scp 退出码: {rc}）")
        return False

    print_success(f"APK 已成功上传到 [{APK_UPLOAD_SERVER}]: {remote_path}")

    # ── 自动同步服务器 .env（版本号 + APK 路径）并重启后端 ──────────────
    print()
    print_info("正在同步服务器版本配置（.env）并重启后端...")
    env_script = (
        f"ENV=/opt/ponychat/.env\n"
        f"touch \"$ENV\"\n"
        f"sed -i '/^PONYCHAT_APP_VERSION_NAME=/d' \"$ENV\"\n"
        f"sed -i '/^PONYCHAT_APP_VERSION_CODE=/d' \"$ENV\"\n"
        f"sed -i '/^PONYCHAT_APP_APK_PATH=/d' \"$ENV\"\n"
        f"echo 'PONYCHAT_APP_VERSION_NAME={vname}' >> \"$ENV\"\n"
        f"echo 'PONYCHAT_APP_VERSION_CODE={vcode}' >> \"$ENV\"\n"
        f"echo 'PONYCHAT_APP_APK_PATH={remote_path}' >> \"$ENV\"\n"
        f"SERVICE=$(systemctl list-units --type=service --state=loaded --no-legend 2>/dev/null"
        f" | awk '{{print $1}}' | grep -iE 'pony|ponychat' | head -1)\n"
        f"if [ -z \"$SERVICE\" ]; then\n"
        f"    echo '[WARN] 未检测到 ponychat 相关服务，请手动重启后端'\n"
        f"    exit 0\n"
        f"fi\n"
        f"systemctl restart \"$SERVICE\" && sleep 3\n"
        f"systemctl is-active \"$SERVICE\" && echo \"[OK] 后端已重启，版本 {vname} ({vcode}) 生效\" "
        f"|| echo '[ERR] 后端重启失败，请手动检查'\n"
    )
    rc_env, _ = _ssh_bash_s_capture(server, env_script)
    if rc_env == 0:
        print_success(f"服务器版本配置已更新: v{vname} (versionCode {vcode})")
    else:
        print_warning("服务器 .env 更新或后端重启异常，请手动检查")

    return True


def main_menu():
    """主菜单循环"""
    # 检查 ADB 状态
    adb = get_adb()
    try:
        result = subprocess.run([adb, "version"], capture_output=True, text=True)
        adb_ok = result.returncode == 0
    except:
        adb_ok = False
    
    while True:
        if IS_WINDOWS:
            os.system("cls")
        else:
            os.system("clear")
        
        print(f"{CYAN}{'='*50}{RESET}")
        print(f"{CYAN}  PonyChat App - 安装调试工具{RESET}")
        print(f"{CYAN}{'='*50}{RESET}")
        print()
        
        # 状态信息
        adb_status = f"{GREEN}✓ 可用{RESET}" if adb_ok else f"{RED}✗ 未安装{RESET}"
        devices = get_connected_devices()
        device_status = f"{GREEN}✓ {len(devices)} 台设备{RESET}" if devices else f"{YELLOW}✗ 无设备{RESET}"
        
        print(f"  ADB 状态: {adb_status}")
        print(f"  设备状态: {device_status}")
        if SELECTED_DEVICE:
            print(f"  当前设备: {GREEN}{SELECTED_DEVICE}{RESET}")
        print(f"  App 目录: {ANDROID_ROOT}")
        print()
        
        print("  +-------------------------------------+")
        print("  |  [1] 检查设备连接                   |")
        print("  |  [2] 编译 Debug APK                 |")
        print("  |  [3] 编译 Release APK               |")
        print("  |  [4] 安装 Debug APK                 |")
        print("  |  [5] 安装 Release APK               |")
        print("  +-------------------------------------+")
        print("  |  [6] 启动应用                       |")
        print("  |  [7] 停止应用                       |")
        print("  |  [8] 卸载应用                       |")
        print("  +-------------------------------------+")
        print("  |  [9] 一键编译+安装+启动 (Debug)     |")
        print("  |  [R] 一键编译+安装+启动 (Release)   |")
        print("  +-------------------------------------+")
        print("  |  [L] 查看日志 (实时)                |")
        print("  |  [S] 保存日志到文件                 |")
        print("  |  [A] 查看崩溃日志                   |")
        print("  |  [C] 清除日志缓冲区                 |")
        print("  +-------------------------------------+")
        print("  |  [P] 截取屏幕                       |")
        print("  |  [D] 选择设备                       |")
        print("  |  [W] 连接无线 ADB                   |")
        print("  |  [X] 清理构建缓存                   |")
        print("  +-------------------------------------+")
        print("  |  [U] 编译并上传 Release APK 到服务器|")
        print("  |  [I] 设置服务器最低接受 App 版本    |")
        print("  +-------------------------------------+")
        print("  |  [0] 退出                           |")
        print("  +-------------------------------------+")
        print()
        choice = input("请选择操作: ").strip().upper()

        if choice == "1":
            check_device()
        elif choice == "2":
            build_apk(release=False)
        elif choice == "3":
            build_apk(release=True)
        elif choice == "4":
            install_apk(release=False)
        elif choice == "5":
            install_apk(release=True)
        elif choice == "6":
            launch_app()
        elif choice == "7":
            stop_app()
        elif choice == "8":
            uninstall_app()
        elif choice == "9":
            build_install_launch(release=False)
        elif choice == "R":
            build_install_launch(release=True)
        elif choice == "L":
            view_logs()
        elif choice == "S":
            save_logs()
        elif choice == "A":
            view_crash_logs()
        elif choice == "C":
            clear_logs()
        elif choice == "P":
            take_screenshot()
        elif choice == "D":
            section("选择设备")
            select_device()
        elif choice == "W":
            connect_wireless_adb()
        elif choice == "X":
            clean_build()
        elif choice == "U":
            build_and_upload_apk()
        elif choice == "I":
            set_min_app_version()
        elif choice == "0":
            print()
            print_success("再见！")
            break
        else:
            if choice:
                print_error("无效选项，请重新选择")

        if choice and choice != "0":
            input("\n按回车键继续...")


if __name__ == "__main__":
    main_menu()
