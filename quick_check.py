import json
from datetime import datetime

with open('labeling_200_cache.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Cache records: {len(data)}")
print(f"\nLast 5 entries:")
for k, v in list(data.items())[-5:]:
    time_str = v.get('time', '')[:19]
    label = v.get('label', 'N/A')
    print(f"  {k}: {label} at {time_str}")
