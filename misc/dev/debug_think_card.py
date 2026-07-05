#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
思考卡片调试工具
用于调试 .think-container 的动画和宽度问题
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
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ADB 路径检测
def find_adb_path() -> str:
    # 方案 0: 优先使用项目内嵌路径（脚本在 misc/dev，须从项目根拼路径）
    project_adb = _PROJECT_ROOT / "misc" / "tools" / "android-sdk" / "platform-tools" / "adb.exe"
    if project_adb.exists():
        return str(project_adb)
        
    adb_in_path = shutil.which("adb")
    if adb_in_path:
        return adb_in_path
    
    local_props = _PROJECT_ROOT / "Android-App" / "app" / "local.properties"
    if local_props.exists():
        with open(local_props, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('sdk.dir='):
                    sdk = line.split('=', 1)[1].strip()
                    sdk = sdk.replace('\\\\', '\\').replace('\\:', ':')
                    adb = Path(sdk) / "platform-tools" / "adb.exe"
                    if adb.exists():
                        return str(adb)
    
    # 常见路径
    common = [
        Path(os.environ.get('LOCALAPPDATA', '')) / "Android/Sdk/platform-tools/adb.exe",
        Path(os.environ.get('USERPROFILE', '')) / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
    ]
    for p in common:
        if p.exists():
            return str(p)
    
    return "adb"


ADB_PATH = find_adb_path()

# 只匹配我们在JS中添加的调试日志标签
KEYWORDS = [
    '[think-container]',
    '[width调试]',
    '[style调试]',
    '[animation调试]',
    '🧠',
    '📐',
    '🎨',
    '🎬',
]

# 必须包含的App标识
APP_TAG = 'ponychat'

EXCLUDE = ['MI-SF', 'Launcher', 'BarFollow', 'Telephony', 'Bandwidth', 'miui']
pattern = re.compile('|'.join(re.escape(k) for k in KEYWORDS), re.IGNORECASE)

def main():
    print("🔍 正在检测设备...")
    print(f"📍 ADB: {ADB_PATH}\n")
    
    result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')[1:]
    devices = [l.split()[0] for l in lines if 'device' in l and l.strip()]
    
    if not devices:
        print("❌ 未检测到设备")
        sys.exit(1)
    
    if len(devices) > 1:
        print(f"✅ 检测到 {len(devices)} 个设备:")
        for i, dev in enumerate(devices, 1):
            print(f"   {i}. {dev}")
        while True:
            try:
                choice = input(f"\n请选择设备 (1-{len(devices)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(devices):
                    device_id = devices[idx]
                    break
            except (ValueError, KeyboardInterrupt):
                print("❌ 已取消")
                sys.exit(0)
    else:
        device_id = devices[0]
    
    print(f"📱 使用设备: {device_id}\n")
    
    # 清除旧日志
    subprocess.run([ADB_PATH, '-s', device_id, 'logcat', '-c'])
    
    print("=" * 60)
    print("🎯 思考卡片调试监控")
    print("=" * 60)
    print("📝 监控: 动画、宽度、flex布局")
    print("🎬 实时监控模式")
    print("⏹️  Ctrl+C 查看分析报告\n")
    
    # 收集详细数据
    data = {
        'width_samples': [],
        'animation_states': [],
        'containers': [],
        'last_container_id': None,
        'dom_snapshots': [],  # 新增: DOM结构快照
        'dots_opacity': [],   # 新增: 点的opacity值
        'width_timeline': []  # 新增: 宽度时间线(关联流式输出状态)
    }
    
    count = 0
    
    try:
        proc = subprocess.Popen(
            [ADB_PATH, '-s', device_id, 'logcat', '-v', 'time'],
            stdout=subprocess.PIPE
        )
        
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            
            text = line.decode('utf-8', errors='replace')
            
            if APP_TAG not in text.lower() and 'chromium' not in text.lower():
                continue
            
            if pattern.search(text):
                if any(e in text for e in EXCLUDE):
                    continue
                
                count += 1
                
                # 🔇 静默采集模式 - 只采集数据，不打印
                if '[think-container]' in text:
                    # 提取ID和状态
                    if 'id=' in text:
                        parts = text.split('id=')
                        if len(parts) > 1:
                            id_part = parts[1].split(',')[0]
                            data['last_container_id'] = id_part
                    
                    is_complete = 'isComplete=true' in text
                    has_dots = 'hasDotsAnimation=true' in text
                    
                    data['containers'].append({
                        'id': data['last_container_id'],
                        'complete': is_complete,
                        'dots': has_dots
                    })
                
                elif '[width调试]' in text:
                    # 提取宽度信息
                    if 'width=' in text and 'parentWidth=' in text:
                        w = text.split('width=')[1].split('px')[0] if 'width=' in text else '?'
                        pw = text.split('parentWidth=')[1].split('px')[0] if 'parentWidth=' in text else '?'
                        
                        # 记录宽度时间线
                        try:
                            w_int = int(w)
                            pw_int = int(pw)
                            ratio = w_int / pw_int * 100 if pw_int > 0 else 0
                            data['width_timeline'].append({
                                'w': w_int,
                                'pw': pw_int,
                                'ratio': ratio,
                                'container_id': data['last_container_id']
                            })
                        except:
                            pass
                        
                        data['width_samples'].append({'w': w, 'pw': pw})
                
                elif '[animation调试]' in text:
                    # 提取动画信息
                    anim_info = text.split('animation=')[1].split('",')[0] if 'animation=' in text else 'unknown'
                    data['animation_states'].append(anim_info)
                    
                    # 提取opacity值
                    if 'opacity=' in text:
                        try:
                            opacity_val = text.split('opacity=')[1].split()[0].strip(',')
                            data['dots_opacity'].append(float(opacity_val))
                        except:
                            pass
                
                # 捕获DOM结构日志
                elif '[DOM结构]' in text or 'thinking-dots' in text.lower():
                    if 'dots_count=' in text:
                        try:
                            dots_count = int(text.split('dots_count=')[1].split()[0].strip(','))
                            data['dom_snapshots'].append({'dots_count': dots_count})
                            # ⚠️ 异常立即提醒
                            if dots_count != 3:
                                print(f"\r\033[K⚠️  异常: DOM点数量={dots_count} (应为3)", flush=True)
                        except:
                            pass
                
                # 捕获margin日志
                elif '[margin调试]' in text:
                    if 'marginLeft=' in text and 'marginRight=' in text:
                        try:
                            ml = text.split('marginLeft=')[1].split(',')[0] if 'marginLeft=' in text else '?'
                            mr = text.split('marginRight=')[1].split()[0] if 'marginRight=' in text else '?'
                            # ⚠️ 负margin异常提醒
                            if '-15px' not in ml or '-15px' not in mr:
                                print(f"\r\033[K⚠️  异常: Margin={ml}/{mr} (应为-15px)", flush=True)
                            if 'margin' not in data:
                                data['margin'] = []
                            data['margin'].append({'left': ml, 'right': mr})
                        except:
                            pass
                
                # 📊 动态进度条 (每10条更新一次，单行刷新)
                if count % 10 == 0:
                    containers_count = len(data['containers'])
                    width_count = len(data['width_samples'])
                    anim_count = len(data['animation_states'])
                    print(f"\r\033[K📊 采集中... 卡片:{containers_count} | 宽度:{width_count} | 动画:{anim_count}", end='', flush=True)
                    
    except KeyboardInterrupt:
        proc.terminate()
        
        # 清除进度条并换行
        print("\r\033[K")  # 清除当前行
        
        # 详细分析报告
        print("=" * 70)
        print("📊 详细分析报告")
        print("=" * 70)
        
        # 1. 卡片统计
        print(f"\n🧠 思考卡片: {len(data['containers'])} 个")
        thinking_count = sum(1 for c in data['containers'] if not c['complete'])
        completed_count = sum(1 for c in data['containers'] if c['complete'])
        print(f"   ⏳ 生成中: {thinking_count}  ✅ 已完成: {completed_count}")
        
        # 2. 宽度分析
        if data['width_samples']:
            print(f"\n📐 宽度分析 (采样{len(data['width_samples'])}次)")
            latest = data['width_samples'][-1]
            print(f"   最新: 卡片宽={latest['w']}px, 父容器={latest['pw']}px")
            
            try:
                ratio = int(latest['w']) / int(latest['pw']) * 100
                print(f"   比例: {ratio:.1f}% (目标95%)")
                if ratio < 90:
                    print(f"   ⚠️  宽度偏小! 应该接近父容器")
            except:
                pass
        
        # 3. 动画诊断 (关键)
        print(f"\n🎬 动画诊断 (检测{len(data['animation_states'])}次)")
        if data['animation_states']:
            # 统计动画状态
            has_running = sum(1 for a in data['animation_states'] if 'running' in str(a).lower())
            has_none = sum(1 for a in data['animation_states'] if 'none' in str(a).lower())
            has_dots = sum(1 for a in data['animation_states'] if 'dotsAnimation' in str(a))
            
            print(f"   ✅ 运行中: {has_running}次")
            print(f"   ❌ None值: {has_none}次")
            print(f"   🎯 含dotsAnimation: {has_dots}次")
            
            # 最新状态
            latest_anim = data['animation_states'][-1]
            print(f"   最新状态: {latest_anim[:80]}")
            
            # 🔧 新增: opacity分析
            if data['dots_opacity']:
                avg_opacity = sum(data['dots_opacity']) / len(data['dots_opacity'])
                visible_samples = sum(1 for o in data['dots_opacity'] if o > 0.5)
                print(f"\n   📊 Opacity统计:")
                print(f"      - 平均值: {avg_opacity:.2f}")
                print(f"      - 可见采样: {visible_samples}/{len(data['dots_opacity'])} ({visible_samples/len(data['dots_opacity'])*100:.1f}%)")
                if avg_opacity < 0.3:
                    print(f"      ⚠️  问题: 平均opacity过低,大部分时间点不可见!")
            
            # 🔧 新增: DOM结构分析
            if data['dom_snapshots']:
                dots_counts = [s['dots_count'] for s in data['dom_snapshots']]
                print(f"\n   🔍 DOM结构检测: {len(dots_counts)}次")
                if any(c != 3 for c in dots_counts):
                    anomalies = [c for c in dots_counts if c != 3]
                    print(f"      ⚠️  异常点数量: {anomalies} (应为[3,3,3...])")
                else:
                    print(f"      ✅ 点数量正常: 所有检测都为3个点")
            
            # 🔧 增强诊断逻辑
            print("\n   🔬 根因诊断:")
            issues_found = []
            
            if has_none > 0:
                issues_found.append("CSS动画规则未生效(可能被覆盖或选择器错误)")
            
            if data['dots_opacity'] and avg_opacity < 0.3:
                issues_found.append("@keyframes设计缺陷: opacity=0占比过高")
                issues_found.append("建议: 修改dotsAnimation,让opacity在更长时间内保持>0.5")
            
            if data['dom_snapshots'] and any(s['dots_count'] != 3 for s in data['dom_snapshots']):
                issues_found.append("HTML生成异常: .thinking-dots子元素数量不正确")
            
            if not issues_found:
                print("      ✅ 未发现明显问题,动画应正常运行")
            else:
                for i, issue in enumerate(issues_found, 1):
                    print(f"      {i}. {issue}")
        else:
            print("   ❌ 未检测到动画日志!")
        
        # 4. 🔧 新增: 宽度-时序关联分析
        if data['width_timeline']:
            print(f"\n📊 宽度时序分析 ({len(data['width_timeline'])}个采样点)")
            
            # 计算统计数据
            ratios = [w['ratio'] for w in data['width_timeline']]
            avg_ratio = sum(ratios) / len(ratios)
            min_ratio = min(ratios)
            max_ratio = max(ratios)
            
            print(f"   宽度比例 (卡片/父容器):")
            print(f"      - 平均: {avg_ratio:.1f}%")
            print(f"      - 范围: {min_ratio:.1f}% ~ {max_ratio:.1f}%")
            print(f"      - 目标: 95-100% (接近父容器)")
            
            if avg_ratio < 90:
                print(f"\n   ⚠️  诊断: 思考卡片宽度显著小于父容器!")
                print(f"   可能原因:")
                print(f"      1. CSS中width未设置为100%或被覆盖")
                print(f"      2. 父容器的alignItems未设置为stretch")
                print(f"      3. flex-grow/flex-shrink设置不当")
            elif max_ratio - min_ratio > 10:
                print(f"\n   ⚠️  诊断: 宽度波动较大({max_ratio-min_ratio:.1f}%),布局不稳定!")
                print(f"   可能原因:")
                print(f"      1. 流式输出时父容器宽度变化")
                print(f"      2. 动态类(.compact-loading等)导致重排")
        
        print("=" * 70)

if __name__ == '__main__':
    main()

