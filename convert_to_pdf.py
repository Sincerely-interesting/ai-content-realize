import markdown
from pathlib import Path

# Read markdown file
md_file = 'MiniMax_MCP计费分析报告.md'
with open(md_file, 'r', encoding='utf-8') as f:
    md_content = f.read()

# Convert to HTML
html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])

# Create a complete HTML document with styling
html_document = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: 'Microsoft YaHei', 'SimHei', Arial, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            border-bottom: 2px solid #bdc3c7;
            padding-bottom: 8px;
            margin-top: 30px;
        }}
        h3 {{
            color: #7f8c8d;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: #3498db;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 15px;
            border-left: 4px solid #3498db;
            overflow-x: auto;
        }}
        blockquote {{
            border-left: 4px solid #bdc3c7;
            padding-left: 15px;
            color: #7f8c8d;
            margin: 10px 0;
        }}
        hr {{
            border: none;
            border-top: 2px solid #bdc3c7;
            margin: 30px 0;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>
"""

# Save HTML
html_file = 'MiniMax_MCP计费分析报告.html'
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_document)

print(f"✅ HTML file created: {html_file}")
print(f"📄 You can now:")
print(f"   1. Open {html_file} in browser")
print(f"   2. Use browser's Print → Save as PDF")
print(f"   3. Or install 'wkhtmltopdf' for direct conversion")
