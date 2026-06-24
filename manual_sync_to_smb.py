# -*- coding: utf-8 -*-
"""手动触发SMB同步 - 从labeling_200_cache.json导出到共享盘"""
import json
import os
import shutil
import pandas as pd
from datetime import datetime
from pathlib import Path

CACHE_FILE = "d:/gitrepo/material-process/labeling_200_cache.json"
SMB_PATH = r"\\192.168.2.242\大数据中心"
SMB_FILENAME = "minimax_mcp_multimodal_results_latest.xlsx"
LOCAL_EXCEL_DIR = "d:/gitrepo/material-process/excel_exports"

def main():
    print("=" * 60)
    print("🔄 手动触发SMB同步")
    print("=" * 60)
    
    # 1. 读取缓存
    print(f"\n📂 读取缓存: {CACHE_FILE}")
    if not os.path.exists(CACHE_FILE):
        print("❌ 缓存文件不存在!")
        return
    
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"✅ 读取成功: {len(data)} 条记录")
    
    # 2. 转换为Excel
    print("\n📊 转换为Excel格式...")
    results = []
    for mid, item_data in data.items():
        info = item_data.get('info', {})
        label = item_data.get('label', '未知')
        reason = item_data.get('reason', '')
        time_str = item_data.get('time', '')
        skipped = item_data.get('skipped', False)
        
        # 判断是否为失败记录
        is_failed = (
            '失败' in label or 
            '异常' in label or 
            '处理异常' in reason or 
            '解析异常' in reason or
            label == '其他' and ('错误' in reason or '异常' in reason)
        )
        
        status = '跳过' if skipped else ('失败' if is_failed else '成功')
        
        # 提取打标时间（从缓存的time字段）
        label_date = '未知'
        if time_str:
            try:
                # 2026-04-24T17:46:45.078734 -> 2026-04-24
                label_date = time_str.split('T')[0]
            except:
                label_date = time_str[:10] if len(time_str) >= 10 else time_str
        
        results.append({
            'daterange': label_date,  # 使用打标时间，而非导出时间
            'dynamiclink': mid,
            '制作组类型（细分标签）': label,
            '判定依据（结合业务规则判断标准）': reason,
            '状态': status,
            '是否视频': info.get('frames_count', 0) > 0,
            '帧数': info.get('frames_count', 0),
            '是否有音频': info.get('has_audio', False),
            '语音文本长度': info.get('transcript_length', 0),
            '语音文本预览': str(info.get('transcript_preview', ''))[:100]
        })
    
    df = pd.DataFrame(results)
    
    # 3. 导出到本地
    os.makedirs(LOCAL_EXCEL_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    local_excel = os.path.join(LOCAL_EXCEL_DIR, f'minimax_results_{timestamp}.xlsx')
    
    print(f"\n💾 导出本地Excel: {local_excel}")
    df.to_excel(local_excel, index=False, engine='openpyxl')
    print(f"✅ 本地导出成功: {len(df)} 条记录")
    
    # 4. 同步到SMB
    smb_file = os.path.join(SMB_PATH, SMB_FILENAME)
    print(f"\n🌐 同步到SMB: {smb_file}")
    
    if not os.path.exists(SMB_PATH):
        print(f"❌ SMB路径不存在: {SMB_PATH}")
        print("   请检查网络连接和共享盘挂载状态")
        return
    
    # 删除旧文件（如果存在）
    if os.path.exists(smb_file):
        print(f"🗑️  删除旧文件: {smb_file}")
        os.remove(smb_file)
    
    # 复制到SMB
    print(f"📤 上传到SMB共享盘...")
    shutil.copy2(local_excel, smb_file)
    
    # 验证
    if os.path.exists(smb_file):
        local_size = os.path.getsize(local_excel)
        smb_size = os.path.getsize(smb_file)
        
        if local_size == smb_size:
            print(f"\n{'=' * 60}")
            print(f"✅ SMB同步成功!")
            print(f"   文件: {SMB_FILENAME}")
            print(f"   大小: {local_size} bytes")
            print(f"   记录数: {len(df)} 条")
            print(f"   路径: {smb_file}")
            print(f"{'=' * 60}")
        else:
            print(f"⚠️  文件大小不匹配: 本地={local_size}, SMB={smb_size}")
    else:
        print(f"❌ SMB文件验证失败!")
    
    # 显示标签分布和状态统计
    print(f"\n📊 标签分布:")
    print(df['制作组类型（细分标签）'].value_counts())
    
    print(f"\n📊 状态统计:")
    print(df['状态'].value_counts())

if __name__ == "__main__":
    main()
