"""清除旧的抽帧缓存，以便使用新的抽帧策略"""
import os
import glob
import shutil

base_dir = "downloaded_materials"

# 查找所有的 minimax_mcp_frames 文件夹
frames_dirs = glob.glob(os.path.join(base_dir, "*", "minimax_mcp_frames"))

print(f"🔍 找到 {len(frames_dirs)} 个抽帧缓存文件夹")

cleared_count = 0
total_frames_removed = 0

for frames_dir in frames_dirs:
    # 统计当前文件夹中的帧数
    frames = glob.glob(os.path.join(frames_dir, "*.jpg"))
    frame_count = len(frames)
    
    # 如果帧数少于10帧，清除这个缓存
    if frame_count < 10:
        material_id = os.path.basename(os.path.dirname(frames_dir))
        print(f"🗑️  清除 {material_id}: {frame_count} 帧 -> 将重新抽帧")
        
        # 删除整个frames目录
        shutil.rmtree(frames_dir)
        cleared_count += 1
        total_frames_removed += frame_count

print(f"\n✅ 清理完成!")
print(f"   清除了 {cleared_count} 个文件夹的抽帧缓存")
print(f"   共删除 {total_frames_removed} 张旧帧图片")
print(f"\n🎯 下次运行打标脚本时，这些视频素材将使用新的抽帧策略（每秒1帧）")
