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
# 2. 增强型自愈工具函数
# ==========================================

def safe_gemini_call(model_name, contents, is_image=False):
    """
    带有自动重试机制的 Gemini 调用函数，专门对付 429 错误
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 物理冷却：每次请求前先睡 10 秒，降低并发压力
            time.sleep(10)
            if is_image:
                return client.models.generate_images(
                    model='imagen-3.0-generate-001',
                    prompt=contents,
                    config={'number_of_images': 1}
                )
            else:
                return client.models.generate_content(model=model_name, contents=contents)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                print(f" -> 触发频率限制，正在进行第 {attempt+1} 次重试，等待 30s...")
                time.sleep(30)
            else:
                raise e

def get_script_content(page_id):
    """从子页面读取剧本"""
    try:
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        child_id = next((b["id"] for b in blocks if b["type"] == "child_page" and "深度解析脚本" in b["child_page"]["title"]), None)
        if not child_id: return None
        
        text = ""
        c_blocks = notion.request(path=f"blocks/{child_id}/children", method="GET").get("results", [])
        for b in c_blocks:
            b_type = b["type"]
            if b_type in ["paragraph", "heading_1", "heading_2", "heading_3", "callout", "quote"]:
                text += "".join([t["plain_text"] for t in b[b_type].get("rich_text", [])]) + "\n"
        return text
    except: return None

# ==========================================
# 3. 视觉工厂逻辑
# ==========================================

def produce_visuals(page_id, script, style):
    print(" -> 🧠 正在规划分镜方案...")
    prompt = f"根据剧本和风格种子 '{style}'，输出 10 个视频分镜 JSON 数组: [{{'time': '00:00', 'title': '描述', 'prompt': 'English prompt'}}]。剧本：{script[:2500]}"
    
    res = safe_gemini_call('gemini-2.0-flash', prompt)
    json_str = res.text.strip().replace("```json", "").replace("```", "").replace("'", "\"").strip()
    chapters = json.loads(json_str)

    # 创建数据库
    new_db = notion.request(
        path="databases",
        method="POST",
        body={
            "parent": {"type": "page_id", "page_id": page_id},
            "title": [{"type": "text", "text": {"content": "🎬 YouTube 剪辑素材库"}}],
            "properties": {
                "描述": {"title": {}}, "时间戳": {"rich_text": {}}, "图片": {"files": {}}, "Prompt": {"rich_text": {}}
            }
        }
    )
    db_id = new_db["id"]

    for idx, item in enumerate(chapters):
        print(f"    🎨 处理 [{idx+1}/10]: {item.get('title')}")
        img_url = "https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg"
        
        try:
            img_res = safe_gemini_call(None, item.get('prompt'), is_image=True)
            img_bytes = img_res.generated_images[0].image_bytes
            up = cloudinary.uploader.upload(img_bytes, resource_type="image")
            img_url = up.get("secure_url")
        except Exception as e:
            print(f"    ⚠️ 图片生成跳过: {e}")

        notion.request(path="pages", method="POST", body={
            "parent": {"database_id": db_id},
            "properties": {
                "描述": {"title": [{"text": {"content": item.get('title', 'N/A')}}]},
                "时间戳": {"rich_text": [{"text": {"content": item.get('time', '00:00')}}]},
                "Prompt": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]},
                "图片": {"files": [{"name": "img.jpg", "external": {"url": img_url}}]}
            }
        })

# ==========================================
# 4. 主程序
# ==========================================
def main():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 生产线启动 | {today} ===")
    
    tasks = notion.request(path=f"databases/{DATABASE_ID}/query", method="POST", body={
        "filter": {"and": [
            {"property": "Category", "select": {"equals": "杂志"}},
            {"property": "阅读日期", "date": {"equals": today}},
            {"property": "深度解析音频", "files": {"is_not_empty": True}}
        ]}
    }).get("results", [])

    for page in tasks:
        pid = page["id"]
        blocks = notion.request(path=f"blocks/{pid}/children", method="GET").get("results", [])
        if any(b["type"] == "child_database" for b in blocks): continue

        script = get_script_content(pid)
        if not script: continue
        
        style = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"
        produce_visuals(pid, script, style)

if __name__ == "__main__":
    main()
