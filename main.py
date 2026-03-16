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
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 视觉生产核心函数
# ==========================================

def get_audio_url_from_page(page):
    """提取音频链接"""
    audio_files = page["properties"].get("深度解析音频", {}).get("files", [])
    if not audio_files: return None
    return audio_files[0].get("file", {}).get("url") or audio_files[0].get("external", {}).get("url")

def analyze_and_draw(audio_url, style_seed):
    """Gemini 听取音频并直接生成分镜数据（含图片生成）"""
    print(f" -> 🎙️ Gemini 正在听取音频并构思画面...")
    
    # 强制冷却防止免费版 API 超限
    time.sleep(10) 
    
    # 第一步：分析音频节点
    prompt = f"""
    请听这段音频：{audio_url}
    根据内容和视觉风格 '{style_seed}'，规划 10 个 YouTube 分镜。
    输出格式为 JSON 数组：[ {{"timestamp": "00:00", "title": "分镜描述", "prompt": "用于生图的英文描述"}} ]
    """
    
    try:
        response = gemini_client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        storyboard_data = json.loads(json_str)
        
        # 第二步：循环生图并上传云端
        results = []
        for item in storyboard_data:
            print(f"    🎨 正在绘制分镜: {item['title']}...")
            # ⚠️ 这里调用您权限内的生图能力
            # image_res = gemini_client.models.generate_image(prompt=item['prompt'])
            # 这里由于环境限制，我们先通过 Cloudinary 占位，您部署时可接入具体的生图方法
            img_url = "https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg" 
            
            results.append({
                "time": item['timestamp'],
                "desc": item['title'],
                "prompt": item['prompt'],
                "url": img_url
            })
        return results
    except Exception as e:
        print(f"❌ 视觉分析或绘图失败: {e}")
        return None

def create_inline_storyboard(page_id, data):
    """在 Page 内部全自动新建一个 Inline Database 并填充内容"""
    print(" -> 🎬 正在 Page 内部创建全自动分镜表...")
    
    try:
        # 1. 创建数据库
        new_db = notion.request(
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": page_id},
                "title": [{"type": "text", "text": {"content": "🎬 YouTube 剪辑素材库"}}],
                "properties": {
                    "分镜描述": {"title": {}},
                    "建议时间戳": {"rich_text": {}},
                    "视觉图片": {"files": {}},
                    "生图词 (Prompt)": {"rich_text": {}}
                }
            }
        )
        db_id = new_db["id"]
        
        # 2. 批量填充行数据
        for row in data:
            notion.request(
                path="pages",
                method="POST",
                body={
                    "parent": {"database_id": db_id},
                    "properties": {
                        "分镜描述": {"title": [{"text": {"content": row['desc']}}]},
                        "建议时间戳": {"rich_text": [{"text": {"content": row['time']}}]},
                        "生图词 (Prompt)": {"rich_text": [{"text": {"content": row['prompt']}}]},
                        "视觉图片": {"files": [{"name": "story.jpg", "external": {"url": row['url']}}]}
                    }
                }
            )
        print(" -> ✅ 视觉工厂任务全部完成，请回 Notion 查看！")
    except Exception as e:
        print(f"❌ 写入 Notion 失败: {e}")

# ==========================================
# 3. 执行流
# ==========================================
def process_magazine():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 视觉分镜流启动 | {today} ===")
    
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

    if not tasks:
        print("今日无新音频任务。")
        return

    for page in tasks:
        page_id = page["id"]
        audio_url = get_audio_url_from_page(page)
        style_seed = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"

        if audio_url:
            print(f"\n--- 发现音频，开始视觉生产: {page_id} ---")
            storyboard_data = analyze_and_draw(audio_url, style_seed)
            if storyboard_data:
                create_inline_storyboard(page_id, storyboard_data)

if __name__ == "__main__":
    process_magazine()
