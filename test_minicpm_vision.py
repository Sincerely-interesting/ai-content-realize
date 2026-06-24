#!/usr/bin/env python3
"""测试MINICPM视觉API"""
import os
import base64
import requests

# 配置
API_KEY = "sk-c526d0f74cbc22adcf70ea6cc064a981"
URL = "https://llm-center.ali.modelbest.cn/llm/v1/chat/completions"
MODEL = "minicpm-v-4"

def encode_image(image_path):
    """编码图片为base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')

# 找一张测试图片
test_dir = "downloaded_materials_smb"
if os.path.exists(test_dir):
    for root, dirs, files in os.walk(test_dir):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                test_image = os.path.join(root, f)
                print(f"找到测试图片: {test_image}")
                
                # 编码图片
                b64_image = encode_image(test_image)
                
                # 构建视觉请求
                payload = {
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64_image}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": "请描述这张图片的内容，这是电商素材吗？"
                                }
                            ]
                        }
                    ],
                    "max_tokens": 200
                }
                
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                }
                
                print(f"\n发送视觉API请求...")
                print(f"图片base64长度: {len(b64_image)}")
                
                try:
                    resp = requests.post(URL, headers=headers, json=payload, timeout=60)
                    print(f"状态码: {resp.status_code}")
                    
                    if resp.status_code == 200:
                        result = resp.json()
                        content = result['choices'][0]['message']['content']
                        print(f"\n✅ 成功!")
                        print(f"响应内容:\n{content[:500]}")
                    else:
                        print(f"❌ 失败: {resp.text}")
                        
                except Exception as e:
                    print(f"❌ 错误: {e}")
                
                break
        break
else:
    print(f"测试目录不存在: {test_dir}")
    print("请先运行打标脚本下载一些素材")
