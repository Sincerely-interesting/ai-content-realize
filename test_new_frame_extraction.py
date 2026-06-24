"""测试新的抽帧策略"""
import os
from extract_frames import extract_frames

# 测试视频
test_video = "downloaded_materials/442417213"

# 查找视频文件
import glob
vids = glob.glob(os.path.join(test_video, '*.mp4'))

if vids:
    video_path = vids[0]
    print(f"📹 测试视频: {video_path}")
    
    # 输出目录
    output_dir = os.path.join(test_video, 'test_frames')
    
    # 测试新策略：每秒1帧，最多30帧
    print("\n🎯 测试新抽帧策略（每秒1帧）...")
    extract_frames(video_path, output_dir, fps_interval=1, max_frames=30)
    
    # 统计结果
    frames = glob.glob(os.path.join(output_dir, '*.jpg'))
    print(f"\n✅ 生成了 {len(frames)} 帧图片")
    
    if frames:
        print("📸 帧文件列表:")
        for f in sorted(frames):
            print(f"  - {os.path.basename(f)}")
else:
    print(f"❌ 在 {test_video} 中未找到视频文件")
