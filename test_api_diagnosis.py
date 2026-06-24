"""
诊断脚本：测试 MiniMax API 的实际状态和图片处理能力
"""
import os
import base64
import requests
import json
from PIL import Image
import io
import time

# 加载配置
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MINIMAX_API_KEY = os.getenv("MIN_MAX_API_KEY", "").strip()
MINIMAX_MODEL = os.getenv("MODEL_NAME", "MiniMax-M2.7").strip()
MINIMAX_API_URL = "https://api.minimaxi.com/anthropic/v1/messages"

def test_pil():
    """测试 PIL 是否正常"""
    print("=" * 60)
    print("📋 测试 1: PIL 安装状态")
    print("=" * 60)
    try:
        from PIL import Image
        print(f"✅ PIL 版本: {Image.__version__}")
        return True
    except Exception as e:
        print(f"❌ PIL 加载失败: {e}")
        return False

def test_image_loading():
    """测试图片加载和编码"""
    print("\n" + "=" * 60)
    print("📋 测试 2: 图片加载与编码")
    print("=" * 60)
    
    test_dir = "downloaded_materials/441228357"
    if not os.path.exists(test_dir):
        print(f"❌ 测试目录不存在: {test_dir}")
        return False
    
    import glob
    imgs = glob.glob(os.path.join(test_dir, '*.jpg'))
    if not imgs:
        print("❌ 未找到测试图片")
        return False
    
    test_img = imgs[0]
    print(f"📁 测试图片: {test_img}")
    print(f"📏 文件大小: {os.path.getsize(test_img) / 1024:.1f} KB")
    
    try:
        img = Image.open(test_img)
        print(f"✅ 图片尺寸: {img.size}")
        print(f"✅ 图片模式: {img.mode}")
        
        # 测试编码
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        max_size = 1024
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            print(f"🔄 已压缩到: {img.size}")
        
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        print(f"✅ Base64 编码大小: {len(encoded) / 1024:.1f} KB")
        
        return True
    except Exception as e:
        print(f"❌ 图片处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_call():
    """测试 API 调用"""
    print("\n" + "=" * 60)
    print("📋 测试 3: MiniMax API 调用")
    print("=" * 60)
    
    if not MINIMAX_API_KEY:
        print("❌ 未设置 MIN_MAX_API_KEY")
        return False
    
    print(f"🔑 API Key 前缀: {MINIMAX_API_KEY[:10]}...")
    print(f"🤖 模型: {MINIMAX_MODEL}")
    print(f"🌐 端点: {MINIMAX_API_URL}")
    
    # 准备测试图片
    import glob
    test_dir = "downloaded_materials/441228357"
    imgs = glob.glob(os.path.join(test_dir, '*.jpg'))
    if not imgs:
        print("❌ 未找到测试图片")
        return False
    
    test_img = imgs[0]
    
    try:
        img = Image.open(test_img)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        max_size = 1024
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"❌ 图片编码失败: {e}")
        return False
    
    # 构建请求
    headers = {
        "x-api-key": MINIMAX_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 256,
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
                        "text": "请描述这张图片的内容。直接输出JSON格式：{\"description\": \"图片描述\"}"
                    }
                ]
            }
        ]
    }
    
    print(f"\n📤 发送请求...")
    start_time = time.time()
    
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=60)
        elapsed = time.time() - start_time
        
        print(f"📥 响应状态: {resp.status_code}")
        print(f"⏱️  响应时间: {elapsed:.2f}s")
        print(f"📊 响应头: {dict(resp.headers)}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ API 调用成功!")
            print(f"📝 响应内容: {json.dumps(data, ensure_ascii=False)[:500]}")
            return True
            
        elif resp.status_code == 529:
            print(f"⚠️  API 过载 (529)")
            print(f"📝 响应内容: {resp.text[:500]}")
            return False
            
        elif resp.status_code == 429:
            print(f"⚠️  速率限制 (429)")
            print(f"📝 响应内容: {resp.text[:500]}")
            return False
            
        else:
            print(f"❌ API 错误 ({resp.status_code})")
            print(f"📝 响应内容: {resp.text[:500]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
        return False
    except Exception as e:
        print(f"❌ 请求异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "=" * 60)
    print("🔍 MiniMax API 诊断工具")
    print("=" * 60 + "\n")
    
    results = {
        "PIL 安装": test_pil(),
        "图片处理": test_image_loading(),
        "API 调用": test_api_call()
    }
    
    print("\n" + "=" * 60)
    print("📊 诊断结果汇总")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有测试通过! API 服务正常")
    else:
        print("⚠️  部分测试失败，请检查上方详细信息")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
