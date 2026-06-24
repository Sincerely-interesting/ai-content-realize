import pandas as pd
import re

def extract_id(text):
    if not isinstance(text, str):
        return None
    match = re.search(r'\d{9}', text)
    return match.group(0) if match else None

file_path = '视频理解抽样判定标准以及标签分类结果.xlsx'
df = pd.read_excel(file_path, sheet_name='Sheet1')

results = {
    '401214668': ('穿搭种草', '1. 人物占比符合：图片 401214668_pic_0.jpg 中人物全身出镜，篇幅占比超过 50%，符合“穿搭种草”中“达人全身展示”的标准。\n2. 内容形式符合：展示了达人的整体穿搭 LOOK，包含上身外套、长裤及鞋子的完整搭配。\n3. 排除法：非“性能测试”，无运动场实测；非“上脚展示”，有人物大面积全身出镜。'),
    '406607248': ('穿搭种草', '1. 人物占比符合：图片 406607248_pic_0.jpg 展示了达人的全身出镜，篇幅占比显著超过 50%。\n2. 内容形式符合：包含了达人的全身 LOOK 展示，涉及服饰、配件及鞋子的整体风格搭配。'),
    '418843023': ('穿搭种草', '1. 人物占比符合：图片 418843023_pic_0.jpg 中达人坐姿出镜，占据画面核心，篇幅超 50%。\n2. 内容形式符合：全方位展示了包括连帽衫、阔腿牛仔裤及运动鞋在内的日常潮流穿搭。'),
    '420909530': ('穿搭种草', '1. 人物占比符合：图片 420909530_pic_0.jpg 中达人全身出镜且占比超过 50%。\n2. 内容形式符合：展示了达人的整体穿搭风格，包含卫衣、阔腿裤及运动鞋。'),
    '442710990': ('上脚展示（鞋类）', '1. 局部出镜符合：图片 442710990_pic_1.jpg 仅展示了脚部上脚画面，没有人物全身或半身出镜，符合“图片仅局部上脚，或人物占比小于 50%”的标准。\n2. 内容形式符合：展示了鞋子的多角度实穿效果，且无讲解迹象。')
}

updated_count = 0
for idx, row in df.iterrows():
    mid = extract_id(str(row.iloc[1])) or extract_id(str(row.iloc[2]))
    if mid in results:
        label, reason = results[mid]
        df.iloc[idx, 8] = label
        df.iloc[idx, 9] = reason
        updated_count += 1
        print(f"Updated ID: {mid}")

df.to_excel(file_path, sheet_name='Sheet1', index=False)
print(f"Total updated: {updated_count}")
