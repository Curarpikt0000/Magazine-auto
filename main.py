import os
import datetime
import requests
import json
import time
from google import genai
from notion_client import Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. 环境与密钥配置
# ==========================================
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")

notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28")
client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数
# ==========================================

def get_script_content(page_id):
    """提取子页面“深度解析脚本”的内容"""
    try:
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        child_page_id = next((b["id"] for b in blocks if b["type"] == "child_page" and "深度解析脚本" in b["child_page"]["title"]), None)
        
        if not child_page_id: return None
        
        script_text = ""
        child_blocks = notion.request(path=f"blocks/{child_page_id}/children", method="GET").get("results", [])
        for b in child_blocks:
            b_type = b["type"]
            if b_type in ["paragraph", "heading_1", "heading_2", "heading_3", "callout", "quote"]:
                text = "".join([t["plain_text"] for t in b[b_type].get("rich_text", [])])
                script_text += text + "\n"
        return script_text
    except Exception as e:
        print(f"❌ 读取脚本失败: {e}")
        return None

def generate_storyboard_data(script_text, style_seed):
    """构思分镜方案 (已修复 f-string 语法错误)"""
    print(" -> 🧠 Gemini 正在策划视觉分镜...")
    
    # 使用单引号包裹 JSON 示例以规避语法冲突
    prompt = (
        f"根据剧本和风格种子 '{style_seed}'，输出 10 个视频分镜 JSON 数组。 "
        f"格式示例: [ {{'time': '00:00', 'title': '描述', 'prompt': 'English prompt'}} ]。 "
        f"剧本：{script_text[:3000]}"
    )
    
    try:
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        # 清洗 JSON 字符串中的潜在字符
        text = response.text.strip().replace("```json", "").replace("```", "").replace("'", "\"").strip()
        return json.loads(text)
    except Exception as e:
        print(f"❌ 分镜策划报错: {e}")
        return None

def produce_visuals(page_id, chapters):
    """创建数据库并生成/挂载图片"""
    print(f" -> 🎬 视觉工厂启动，处理 {len(chapters)} 个节点...")
    
    try:
        # 1. 创建内嵌数据库
        new_db = notion.request(
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": page_id},
                "title": [{"type": "text", "text": {"content": "🎬 YouTube 剪辑素材库"}}],
                "properties": {
                    "分镜描述": {"title": {}},
                    "建议时间戳": {"rich_text": {}},
                    "视觉素材": {"files": {}},
                    "AI Prompt": {"rich_text": {}}
                }
            }
        )
        db_id = new_db["id"]

        for index, item in enumerate(chapters):
            print(f"    🎨 处理 [{index+1}/10]: {item.get('title', 'N/A')}...")
            img_url = "https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg" # 默认占位
            
            # 2. 尝试生图 (自愈逻辑)
            try:
                image_response = client.models.generate_images(
                    model='imagen-3.0-generate-001',
                    prompt=item.get('prompt', ''),
                    config={'number_of_images': 1}
                )
                image_bytes = image_response.generated_images[0].image_bytes
                upload_res = cloudinary.uploader.upload(image_bytes, resource_type="image")
                img_url = upload_res.get("secure_url")
            except Exception as img_err:
                print(f"    ⚠️ 生图接口跳过 (将保留 Prompt): {img_err}")

            # 3. 写入 Notion 页面
            notion.request(
                path="pages",
                method="POST",
                body={
                    "parent": {"database_id": db_id},
                    "properties": {
                        "分镜描述": {"title": [{"text": {"content": item.get('title', 'N/A')}}]},
                        "建议时间戳": {"rich_text": [{"text": {"content": item.get('time', '00:00')}}]},
                        "AI Prompt": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]},
                        "视觉素材": {"files": [{"name": "story.jpg", "external": {"url": img_url}}]}
                    }
                }
            )
            time.sleep(1) 
            
        print(" -> ✅ 任务全部完成。")
    except Exception as e:
        print(f"❌ 流程中断: {e}")

def main():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 视觉生产线启动 | {today} ===")
    
    # 筛选今日任务
    tasks = notion.request(
        path=f"databases/{DATABASE_ID}/query",
        method="POST",
        body={
            "filter": {
                "and": [
                    {"property": "Category", "select": {"equals": "杂志"}},
                    {"property": "阅读日期", "date": {"equals": today}},
                    {"property": "深度解析音频", "files": {"is_not_empty": True}}
                ]
            }
        }
    ).get("results", [])

    for page in tasks:
        page_id = page["id"]
        
        # 查重
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        if any(b["type"] == "child_database" for b in blocks): continue

        # 核心逻辑：读剧本 -> 构思 -> 生产
        script = get_script_content(page_id)
        if not script:
            print(f" -> 跳过 {page_id}: 未发现‘深度解析脚本’页面。")
            continue
            
        style = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"
        
        chapters = generate_storyboard_data(script, style)
        if chapters:
            produce_visuals(page_id, chapters)

if __name__ == "__main__":
    main()
