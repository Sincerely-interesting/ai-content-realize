import json

cache = json.load(open('minimax_label_cache.json', encoding='utf-8'))
success = {k:v for k,v in cache.items() if v['label'] != '其他'}

print(f'成功数量: {len(success)}')
print('\n成功案例:')
for k, v in list(success.items())[:5]:
    print(f'{k}: {v["label"]} - {v["reason"][:80]}')
