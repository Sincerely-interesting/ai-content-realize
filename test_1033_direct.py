# -*- coding: utf-8 -*-
"""直接测试 API Error 1033"""
import asyncio
import base64
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_single_call():
    """测试单次API调用"""
    frame_path = "d:/gitrepo/material-process/downloaded_materials/444093902/minimax_mcp_multimodal_frames/frame_29.jpg"
    
    # 读取图片
    with open(frame_path, 'rb') as f:
        img_data = base64.b64encode(f.read()).decode()
    
    print(f"图片大小: {len(img_data)} 字符 (base64)")
    print(f"图片路径: {frame_path}")
    
    prompt = """请分析这张图片，判断其内容类型。

可选标签：
1. 性能测评：展示运动动作(如跑步、跳跃等) + 运动场地/科技点讲解
2. 穿搭精选 (核心)-穿搭种草：全身/半身 + 人物头部 + 完整穿搭
3. 穿搭精选 (次要)-穿搭种草：半身图(头部+躯干)，未识别到脚部
4. 单品展示 (剔除出穿搭)-上脚：膝盖以下 + 静止展示 + 上脚状态
5. 静物展示：纯商品，无人物，简单背景
6. 创意静物：专业影棚/AI渲染/艺术布景
7. 其他：不属于以上类别

请以JSON格式输出：
{"标签": "xxx", "理由": "xxx"}
"""
    
    try:
        from mcp.client import MCPClient
        
        print("连接 MCP Server...")
        client = MCPClient()
        await client.connect("minimax-coding-plan-mcp")
        
        print("调用 understand_image...")
        result = await client.call_tool("understand_image", {
            "prompt": prompt,
            "image_base64": img_data
        })
        
        print(f"结果: {result}")
        
        await client.disconnect()
        return result
        
    except Exception as e:
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = asyncio.run(test_single_call())
