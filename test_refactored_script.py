"""
测试重构后的图片处理逻辑
"""
import os
import glob
from minimax_mcp_label_materials import (
    encode_image, 
    analyze_image_with_vision, 
    parse_api_response,
    get_enhanced_label_and_reason
)

# 测试几个之前失败的文件夹
test_folders = [
    '447830141',  # 之前报告"未检测到图片内容"
    '443538478',  # 之前报告"请提供需要分析的图片"
    '441641549',  # 之前成功
]

materials_dir = 'downloaded_materials'

print("=" * 60)
print("🧪 开始测试重构后的图片处理逻辑")
print("=" * 60)

for folder_id in test_folders:
    folder_path = os.path.join(materials_dir, folder_id)
    
    if not os.path.exists(folder_path):
        print(f"\n❌ 文件夹不存在: {folder_id}")
        continue
    
    print(f"\n{'='*60}")
    print(f"📁 测试文件夹: {folder_id}")
    print(f"{'='*60}")
    
    # 查找图片
    imgs = (glob.glob(os.path.join(folder_path, '*.jpg')) + 
            glob.glob(os.path.join(folder_path, '*.jpeg')) + 
            glob.glob(os.path.join(folder_path, '*.png')))
    
    if not imgs:
        print(f"⚠️  未找到图片文件")
        continue
    
    test_image = imgs[0]
    print(f"🖼️  测试图片: {os.path.basename(test_image)}")
    print(f"📏 文件大小: {os.path.getsize(test_image)} 字节")
    
    # 测试1: 图片编码
    print("\n[测试1] 图片编码...")
    encoded = encode_image(test_image)
    if encoded:
        print(f"✅ 编码成功 (大小: {len(encoded)/1024:.1f}KB)")
    else:
        print(f"❌ 编码失败")
        continue
    
    # 测试2: 完整打标流程
    print("\n[测试2] 完整打标流程...")
    label, reason, mcp_info = get_enhanced_label_and_reason(
        test_image,
        folder_id,
        consecutive_529=0,
        use_search=False,  # 暂时禁用MCP服务，专注于图片处理
        use_embeddings=False
    )
    
    print(f"📋 标签: {label}")
    print(f"📝 原因: {reason[:100]}")
    
    if mcp_info.get('mcp_errors'):
        print(f"⚠️  MCP错误: {mcp_info['mcp_errors']}")

print("\n" + "=" * 60)
print("✅ 测试完成")
print("=" * 60)
