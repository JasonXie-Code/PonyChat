#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复 admin_legacy.py 中剩余的中文乱码
"""
import sys
import io

# 设置标准输出为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def fix_remaining_encoding():
    """修复 admin_legacy.py 中剩余的中文乱码"""
    file_path = "backend/routes/admin_legacy.py"
    
    # 剩余乱码映射表
    remaining_fixes = {
        "璺緞閰嶇疆": "路径配置",
        "5鍒嗛挓鏃犳椿鍔ㄨ涓虹绾?": "5分钟无活动视为离线",
        "绠＄悊鍛橀厤缃枃浠?": "管理员配置文件",
        "榛樿閰嶇疆": "默认配置",
        "榛樿瀵嗙爜": "默认密码",
        "缁熻娲昏穬浼氳瘽鏁帮紙鍩轰簬 WebSocket 杩炴帴锛?": "统计活跃会话数（基于 WebSocket 连接）",
        "缁熻瀵硅瘽鏁帮紙缁熻鎵€鏈夌敤鎴风殑瀵硅瘽鏁伴噺锛?": "统计对话数（统计所有用户的对话数量）",
        "杩愯涓?": "运行中",
        "閿欒": "错误",
        "鑾峰彇绠＄悊鍚庡彴姒傝缁熻锛堝寘鍚湡瀹炲浘琛ㄦ暟鎹級": "获取管理后台概况统计（包含真实图表数据）",
        "鍒濆鍖栧浘琛ㄦ暟鎹紙杩囧幓7澶╋級": "初始化图表数据（过去7天）",
        "鍓嶇鍚?": "前端显示",
        "缁熻鐢ㄦ埛鏁版嵁": "统计用户数据",
        "鐢变簬涔嬪墠浠ｇ爜bug瀛樼殑鏄矾寰?": "由于之前代码bug存的是路径",
        "鎴戜滑灏濊瘯鑾峰彇鐩綍鍒涘缓鏃堕棿": "我们尝试获取目录创建时间",
        "缁熻瑙掕壊": "统计角色",
        "缁熻瀵硅瘽": "统计对话",
        "缁熻椤跺眰鐨?timestamp 或者 messages 里的": "统计顶层的 timestamp 或者 messages 里的",
        "缁熻 session 灞傜骇": "统计 session 层级",
        "缁熻鎬绘秷鎭暟": "统计总消息数",
        "姝ゅ杩樿缁熻榛樿鐩綍鐨?": "此外还要统计默认目录的？",
        "绠€鍗曡捣瑙?": "简单起见",
        "鎴戜滑涓昏缁熻鐢ㄦ埛鐩綍鐨?": "我们主要统计用户目录的",
        "鑾峰彇缁熻澶辫触": "获取统计失败",
        "缁熻瑙掕壊鏁?": "统计角色数",
        "缁熻娑堟伅鏁?": "统计消息数",
        "鑾峰彇鎴栬缃敞鍐屾椂闂?": "获取或设置注册时间",
        "纭繚浠?info 涓姝纭璇?": "确保从 info 中正确读取",
        "鑾峰彇鎴栬缃渶鍚庢椿璺冩椂闂?": "获取或设置最后活跃时间",
        "鑾峰彇鎵€鏈夎鑹插垪琛?": "获取所有角色列表",
        "浣跨敤鏂囦欢淇敼鏃堕棿": "使用文件修改时间",
        "鑾峰彇瀵硅瘽鎽樿鍒楄〃": "获取对话摘要列表",
    }
    
    try:
        # 读取文件
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 替换乱码
        fixed_count = 0
        for garbled, correct in remaining_fixes.items():
            if garbled in content:
                content = content.replace(garbled, correct)
                fixed_count += 1
                print(f"✅ 修复: {garbled[:30]}... -> {correct}")
        
        # 写回文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"\n✅ 修复完成！共修复 {fixed_count} 处乱码")
        return True
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        return False

if __name__ == "__main__":
    fix_remaining_encoding()
