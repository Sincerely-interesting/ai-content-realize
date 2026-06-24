import os
import base64
import requests
import json
import pandas as pd
from PIL import Image
import io
import argparse
import glob
from datetime import datetime
import time # For potential rate limiting or delays

# Import the modified extract_frames function
from extract_frames import extract_frames

# Gemini API configuration
GEMINI_API_MODEL = "gemini-2.5-flash" 
GEMINI_CACHE_FILE = 'gemini_label_cache.json' # Cache file for storing results

YESCODE_GEMINI_PROXY_BASE_URL = os.getenv("YESCODE_GEMINI_PROXY_BASE_URL") or "https://co.yes.vg/gemini"


def get_gemini_api_key():
    """Resolve the Gemini-compatible API key from the environment at runtime."""
    api_key = os.getenv("YESCODE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "YESCODE_API_KEY or GEMINI_API_KEY environment variable not set. "
            "Please set one of them before running the script."
        )
    return api_key

def load_cache():
    """Loads existing labels from the cache file."""
    if os.path.exists(GEMINI_CACHE_FILE):
        with open(GEMINI_CACHE_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Cache file {GEMINI_CACHE_FILE} is corrupted or empty. Starting with empty cache.")
                return {}
    return {}

def save_cache(cache_data):
    """Saves current labels to the cache file."""
    with open(GEMINI_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)

def encode_image_to_base64(image_path):
    """Encodes an image file to a base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def analyze_image_with_gemini(image_path, prompt):
    """Sends an image and a prompt to the Gemini API via YesCode proxy for analysis."""
    api_key = get_gemini_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}" # YesCode usually uses Authorization header
    }
    
    try:
        # Resize image if it's too large to prevent "Request payload too large" error
        img = Image.open(image_path)
        # Convert RGBA to RGB if necessary
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        # Max dimension 1024 to keep it reasonable
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / float(max(img.size))
            new_size = tuple([int(x * ratio) for x in img.size])
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"    (Resized image from {img.size} to {new_size})")

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        encoded_image = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")
        return None

    # Constructing payload for native Gemini API format
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}}
                ]
            }
        ]
    }
    
    # YesCode proxies the original Gemini endpoint
    gemini_endpoint_path = f"/v1beta/models/{GEMINI_API_MODEL}:generateContent"
    full_api_url = f"{YESCODE_GEMINI_PROXY_BASE_URL}{gemini_endpoint_path}"
    
    try:
        response = requests.post(full_api_url, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            print(f"Error calling Gemini API for {image_path}: HTTP {response.status_code}")
            print(f"Response Body: {response.text[:500]}")
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling Gemini API for {image_path}: {e}")
        return None

def is_celebrity_outfit(media_path):
    """
    Determines the material category based on professional fashion and sports analysis.
    Returns (label, reason).
    """
    prompt = """
    你是一位专业的时尚与运动产品分析师。请分析以下图片/视频帧，并将其归类为以下精准标签之一。
    
    ### 标签分类及判定标准：

    1. **性能测试**
       - **标准要求**：视频/图片中人物在实际运动场景（如篮球场、跑道、健身房）中穿着产品，并有明显的运动行为（如起跳、奔跑、急停）。
       - **核心特征**：包含对产品“科技点”（如中底缓震、外底抓地力、支撑性）的口播或文字讲解。
       - **排除项**：非单纯的行走展示，必须有功能性测试或专业参数拆解。

    2. **明星穿搭**
       - **标准要求**：识别到知名明星（娱乐、体育、时尚界公众人物）出镜。
       - **场景要求**：画面通常为专业资讯扒图、街拍、活动现场或综艺片场。
       - **核心特征**：内容侧重于明星同款分享、明星个人风格展示，而非普通达人实拍。

    3. **穿搭精选 (核心)-穿搭种草**
       - **视觉标准**：全身图 (Full)。画面中同时清晰识别到：头部 + 躯干 + 脚部。
       - **构图要求**：人物占比通常 > 50%，视角完整，重点在于整体服装搭配风格。
       - **排除项**：无明显的“科技点”深度讲解（区别于性能测试）。

    4. **穿搭精选 (次要)-穿搭种草**
       - **视觉标准**：半身图 (Half)。识别到头部 + 躯干，但未识别到脚部。
       - **核心特征**：中近景构图，展示上半身与服饰的搭配细节。

    5. **单品展示 (剔除出穿搭)-上脚**
       - **视觉标准**：局部/上脚图 (Detail)。仅识别到膝盖以下及脚部，未识别到头部或躯干。
       - **核心特征**：画面中心集中在鞋部，纯粹展示产品在足部的效果。

    6. **创意静物**
       - **场景要求**：图片/视频中完全无人物出镜。
       - **核心特征**：具有明显的艺术置景、氛围灯光或AI渲染效果，旨在传达品牌调性。
       - **排除项**：非简单的白底或平铺图。

    7. **静物展示**
       - **核心特征**：纯底拍摄、平铺展示或简单的商品特写，无人物交互，无复杂置景。

    8. **其他**
       - 不属于以上任何分类的情况。

    ### 输出格式要求：
    请输出一个 JSON 格式的结果，包含 'label' 和 'reason' 两个字段。
    'reason' 字段必须包含以下三个结构化部分，且使用换行符分隔：
    1. **场景与行为符合标准**：描述画面中的环境、人物动作及视觉构构图。
    2. **核心内容符合定义**：说明为何符合该标签的业务定义。
    3. **排除法分析**：解释为何不属于其他相似的标签（如：为何是穿搭种草而非性能测试）。

    示例输出格式：
    {
        "label": "穿搭精选 (核心)-穿搭种草",
        "reason": "场景与行为符合标准：画面为户外街景，达人全身出镜，头部、躯干及脚部位置清晰，人物占比约60%。\\n核心内容符合定义：内容侧重于展示运动鞋与休闲装的整体搭配效果，属于典型的穿搭种草。\\n排除法分析：画面中无运动测试行为，也未提及产品科技参数，因此排除性能测试；因包含完整人体，排除单品展示。"
    }
    """
    
    response_data = analyze_image_with_gemini(media_path, prompt)
    
    if response_data and "candidates" in response_data and response_data["candidates"]:
        try:
            full_text_response = "".join(part["text"] for part in response_data["candidates"][0]["content"]["parts"])
            # Attempt to find the JSON object within the string, as models sometimes embed it
            json_start = full_text_response.find('{')
            json_end = full_text_response.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_string = full_text_response[json_start:json_end]
                result = json.loads(json_string)
                label = result.get("label", "其他")
                reason = result.get("reason", "未能从 Gemini API 获得明确的判断理由。")
                return label, reason
            else:
                print(f"Error: No JSON object found in Gemini response for {media_path}. Raw response: {full_text_response[:200]}...")
                return "其他", "Gemini API 返回结果未包含有效的JSON对象。"
        except json.JSONDecodeError:
            print(f"Error: Could not parse JSON from Gemini response for {media_path}. Raw response: {full_text_response[:200]}...")
            return "其他", "Gemini API 返回结果格式不正确，无法解析。"
        except Exception as e:
            print(f"An unexpected error occurred while processing Gemini response for {media_path}: {e}")
            return "其他", f"处理 Gemini 响应时发生未知错误: {e}"
    
    return "其他", "未能从 Gemini API 获得有效响应。"

def main():
    parser = argparse.ArgumentParser(description="Label materials using Gemini API.")
    parser.add_argument('--materials_dir', type=str, default='downloaded_materials',
                        help='Directory containing downloaded materials.')
    parser.add_argument('--output_file', type=str, default='gemini_labeled_results.xlsx',
                        help='Output Excel file name.')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Delay in seconds between API calls to prevent rate limiting.')
    parser.add_argument('--batch_size', type=int, default=5,
                        help='Number of new materials to process in each run.')
    parser.add_argument('--batch_delay', type=float, default=20.0,
                        help='Delay in seconds between processing batches of materials to prevent rate limiting.')
    args = parser.parse_args()

    materials_dir = args.materials_dir
    output_file = args.output_file
    api_call_delay = args.delay
    batch_size = args.batch_size
    batch_delay = args.batch_delay

    if not os.path.exists(materials_dir):
        print(f"Error: {materials_dir} not found.")
        return

    print(f"开始使用 Gemini API 对素材进行打标，并将结果输出到：{output_file}...")
    
    results = []
    processed_materials_cache = load_cache() # Load existing cache

    all_material_ids = [d for d in os.listdir(materials_dir) if os.path.isdir(os.path.join(materials_dir, d))]
    unprocessed_material_ids = [mid for mid in all_material_ids if mid not in processed_materials_cache]

    if not unprocessed_material_ids:
        print("所有素材都已打标或已存在于缓存中，无需新的打标任务。")
        # Generate the Excel file from cache if all are processed
        for mid, data in processed_materials_cache.items():
            current_date = datetime.now().strftime('%Y-%m-%d')
            row = {
                'daterange': current_date,
                'saveurl': f'Folder: {mid}',
                'dynamiclink': mid,
                'photos': '',
                'videos': '',
                'creatupdatedate': '',
                'Unnamed: 6': '',
                'Unnamed: 7': '',
                '制作组类型（细分标签）': data['label'],
                '判定依据（结合业务规则判断标准）': data['reason']
            }
            results.append(row)
        
        if results:
            columns = ['daterange', 'saveurl', 'dynamiclink', 'photos', 'videos', 'creatupdatedate', 'Unnamed: 6', 'Unnamed: 7', '制作组类型（细分标签）', '判定依据（结合业务规则判断标准）']
            df_final = pd.DataFrame(results, columns=columns)
            df_final.to_excel(output_file, index=False)
            print(f"已成功从缓存生成 '{len(results)}' 个素材的打标结果 Excel 文件：{os.path.abspath(output_file)}")
        return

    print(f"找到 {len(unprocessed_material_ids)} 个未打标素材。将分批处理，每批 {batch_size} 个，批次间隔 {batch_delay} 秒。")
    
    # Process materials in chunks of batch_size
    for i in range(0, len(unprocessed_material_ids), batch_size):
        materials_to_process_in_batch = unprocessed_material_ids[i:i + batch_size]
        
        for mid in materials_to_process_in_batch:
            material_path = os.path.join(materials_dir, mid)
            print(f"Processing material ID: {mid}")

            material_label = "其他"
            material_reason = "未能识别出可分析的媒体文件。"
            
            # If not in cache (which it shouldn't be for unprocessed_material_ids), proceed with API calls
            # Check for image files
            image_files = (glob.glob(os.path.join(material_path, '*.jpg')) +
                            glob.glob(os.path.join(material_path, '*.jpeg')) +
                            glob.glob(os.path.join(material_path, '*.png')))

            # Check for video files
            video_files = (glob.glob(os.path.join(material_path, '*.mp4')) +
                            glob.glob(os.path.join(material_path, '*.avi')) +
                            glob.glob(os.path.join(material_path, '*.mov')) +
                            glob.glob(os.path.join(material_path, '*.wmv')))
            
            if image_files:
                # For simplicity, just analyze the first image found
                print(f"  Analyzing image: {image_files[0]} (API call)")
                label, reason = is_celebrity_outfit(image_files[0])
                material_label = label
                material_reason = reason
                time.sleep(api_call_delay) # Add delay after API call
            elif video_files:
                print(f"  Extracting frames from video: {video_files[0]}")
                frames_output_dir = os.path.join(material_path, 'gemini_frames')
                os.makedirs(frames_output_dir, exist_ok=True) # Ensure directory exists
                extract_frames(video_files[0], frames_output_dir)
                
                frame_files = glob.glob(os.path.join(frames_output_dir, '*.jpg'))
                
                if frame_files:
                    video_is_celebrity_outfit = False
                    video_reasons = []
                    for frame_file in frame_files:
                        print(f"    Analyzing frame: {frame_file} (API call)")
                        label, reason = is_celebrity_outfit(frame_file)
                        video_reasons.append(f"帧 {os.path.basename(frame_file)}: {reason}")
                        if label == "明星穿搭":
                            video_is_celebrity_outfit = True
                            # Continue processing other frames to collect all reasons, but we already know the overall label
                        time.sleep(api_call_delay) # Add delay after each frame API call
                    
                    material_label = "明星穿搭" if video_is_celebrity_outfit else "其他"
                    material_reason = "视频分析结果：\n" + "\n".join(video_reasons)
                else:
                    material_reason = "未能从视频中提取任何帧进行分析。"
            
            # Store new result in cache immediately after processing each material
            processed_materials_cache[mid] = {
                'label': material_label,
                'reason': material_reason,
                'timestamp': datetime.now().isoformat()
            }
            save_cache(processed_materials_cache) # Save cache after each material
            print(f"  已将素材 {mid} 的结果保存到缓存。")
        
        # Add delay between batches
        if i + batch_size < len(unprocessed_material_ids):
            print(f"批次处理完成，等待 {batch_delay} 秒后继续下一批...")
            time.sleep(batch_delay)

    # After processing all batches, regenerate the full Excel from the updated cache
    results = []
    for mid, data in processed_materials_cache.items():
        current_date = datetime.now().strftime('%Y-%m-%d')
        row = {
            'daterange': current_date,
            'saveurl': f'Folder: {mid}',
            'dynamiclink': mid,
            'photos': '',
            'videos': '',
            'creatupdatedate': '',
            'Unnamed: 6': '',
            'Unnamed: 7': '',
            '制作组类型（细分标签）': data['label'],
            '判定依据（结合业务规则判断标准）': data['reason']
        }
        results.append(row)

    if results:
        columns = ['daterange', 'saveurl', 'dynamiclink', 'photos', 'videos', 'creatupdatedate', 'Unnamed: 6', 'Unnamed: 7', '制作组类型（细分标签）', '判定依据（结合业务规则判断标准）']
        df_final = pd.DataFrame(results, columns=columns)
        df_final.to_excel(output_file, index=False)
        print(f"已成功生成 '{len(results)}' 个素材的打标结果 Excel 文件：{os.path.abspath(output_file)}")
    else:
        print("未找到任何素材文件夹进行打标。")
    
    print(f"打标结果已保存到缓存文件：{GEMINI_CACHE_FILE}")

if __name__ == "__main__":
    main()
