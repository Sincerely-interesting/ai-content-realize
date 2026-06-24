import cv2
import os

def extract_frames(video_path, output_dir, fps_interval=1):
    """
    从视频中抽取帧
    
    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        fps_interval: 抽帧间隔（秒），默认1秒1帧
    """
    if not os.path.exists(video_path):
        print(f"Video not found: {video_path}")
        return
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    
    if video_fps <= 0:
        video_fps = 30  # 默认30fps
    
    # 计算总时长（秒）
    duration = total_frames / video_fps
    print(f"视频时长: {duration:.1f}秒, 帧率: {video_fps:.1f}fps, 总帧数: {total_frames}")
    
    # 计算抽帧间隔（按帧数）
    frame_interval = int(video_fps * fps_interval)
    
    # 生成抽帧位置：每秒抽一帧，视频多少秒就抽多少帧
    frame_indices = []
    current_pos = 0
    
    while current_pos < total_frames:
        frame_indices.append(current_pos)
        current_pos += frame_interval
    
    print(f"抽帧策略: 每{fps_interval}秒抽1帧, 共抽取 {len(frame_indices)} 帧（视频时长{duration:.1f}秒）")
    
    for i, pos in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if ret:
            frame_path = os.path.join(output_dir, f"frame_{i:02d}.jpg")
            cv2.imwrite(frame_path, frame)
            # print(f"Saved {frame_path}") # Suppress print for library use
    
    cap.release()
    print(f"✅ 抽帧完成，保存至: {output_dir}")
