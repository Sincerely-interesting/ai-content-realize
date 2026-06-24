"""
测试 MiniMax API 的图片格式
验证 Anthropic 兼容格式是否正确
"""
import os
import base64
import requests
import json
from PIL import Image
import io
from dotenv import load_dotenv

load_dotenv()

MINIMAX_API_KEY = os.getenv("MIN_MAX_API_KEY", "").strip()
MINIMAX_MODEL = os.getenv("MODEL_NAME", "MiniMax-M2.7").strip()
MINIMAX_API_URL = "https://api.minimaxi.com/anthropic/v1/messages"

def encode_image(path):
    """编码图片"""
    img = Image.open(path)
    if img.mode == 'RGBA':
        img = img.convert('RGB')
    max_size = 1024
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

# 测试图片
test_image = 'downloaded_materials/440872701/440872701_pic_0.jpg'
encoded = encode_image(test_image)

print(f"图片编码长度: {len(encoded)} characters")
print(f"模型: {MINIMAX_MODEL}")
print(f"API URL: {MINIMAX_API_URL}")
print()

# 测试 1: 当前使用的 Anthropic 格式
print("=" * 60)
print("测试 1: Anthropic Messages API 格式")
print("=" * 60)

payload_anthropic = {
    "model": MINIMAX_MODEL,
    "max_tokens": 1024,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": encoded
                    }
                },
                {
                    "type": "text",
                    "text": "请描述这张图片的内容。"
                }
            ]
        }
    ]
}

headers = {
    "x-api-key": MINIMAX_API_KEY,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}

try:
    resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload_anthropic, timeout=30)
    print(f"状态码: {resp.status_code}")
    print(f"响应: {resp.text[:500]}")
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"\n完整响应结构:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
except Exception as e:
    print(f"错误: {e}")

print()
print("=" * 60)
print("测试 2: OpenAI 兼容格式 (image_url)")
print("=" * 60)

# MiniMax 可能支持 OpenAI 格式
payload_openai = {
    "model": MINIMAX_MODEL,
    "max_tokens": 1024,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded}"
                    }
                },
                {
                    "type": "text",
                    "text": "请描述这张图片的内容。"
                }
            ]
        }
    ]
}

try:
    resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload_openai, timeout=30)
    print(f"状态码: {resp.status_code}")
    print(f"响应: {resp.text[:500]}")
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"\n完整响应:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1000])
except Exception as e:
    print(f"错误: {e}")
