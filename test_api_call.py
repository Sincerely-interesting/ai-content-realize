import requests
import base64
import json

api_key = "cr_7590bd95546d053cb69b2fe854ad194b442e3ee758eb70d75a81086053eda3b2"
base_url = "https://co.yes.vg/gemini"
model = "gemini-2.5-flash"

# Create a simple test image (1x1 pixel)
import io
from PIL import Image
img = Image.new('RGB', (10, 10), color='red')
img_buffer = io.BytesIO()
img.save(img_buffer, format='JPEG')
img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')

url = f"{base_url}/v1beta/models/{model}:generateContent"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}

payload = {
    "contents": [
        {
            "parts": [
                {"text": "What color is this image? Reply in JSON: {\"color\": \"...\"}"},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_base64}}
            ]
        }
    ]
}

print(f"Testing API call to: {url}")
try:
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
    print(f"Response: {response.text[:500]}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nParsed response successfully!")
        if "candidates" in data:
            print(f"Candidates: {len(data['candidates'])}")
            
except Exception as e:
    print(f"Error: {e}")
