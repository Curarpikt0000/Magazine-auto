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
# 使用 Paid Tier 权限下的 Gemini 3 Flash 模型
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 视觉工厂核心函数
# ==========================================

def analyze_audio_and_generate_data(audio_url, style_seed):
    """
    让 Gemini 听取 NotebookLM 音频，并构思 10 个分镜
    """
    print(f" -> 🎙️ Gemini 正在分析音频内容与节奏...")
    
    # 强制等待 30 秒，确保长音频处理不触发频率限制
    time.sleep(30)
    
    prompt = f"""
    这是一段 YouTube 讲解视频的音频链接：{audio_url}
    
    请执行以下任务：
    1. 听取音频，总结出 10 个最适合转场的视觉节点。
    2. 为每个时刻提供【建议时间戳】（如 01:20）。
    3. 根据风格种子 '{style_seed}'，为每个节点写一段【生图提示词 (English Prompt)】。
    描述需包含构图、光影和具体的视觉元素，确保风格统一。
    
    请仅输出纯 JSON 数组，格式如下：
    [ {{"timestamp": "00:00", "title": "分镜标题", "prompt": "Prompt description"}} ]
    """
    
    try:
        response = gemini_client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(json_str)
    except Exception as e:
        print(f"❌ 音频视觉分析失败: {e}")
        return None

def create_inline_storyboard(page_id, chapters):
    """
    在 Page 内部全自动新建一个 Inline Database 并填充内容
    """
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
                    "视觉素材": {"files": {}},
                    "生图词 (Prompt)": {"rich_text": {}}
                }
            }
        )
        db_id = new_db["id"]
        
        # 2. 填充数据
        for item in chapters:
            # 💡 提示：这里您可以根据需要接入具体的图像生成 API
            # 目前为您预留一个占位图片，或您可以直接利用 Cloudinary 的 URL
            placeholder_img = "https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg"
            
            notion.request(
                path="pages",
                method="POST",
                body={
                    "parent": {"database_id": db_id},
                    "properties": {
                        "分镜描述": {"title": [{"text": {"content": item.get('title', '未命名')}}]},
                        "建议时间戳": {"rich_text": [{"text": {"content": item.get('timestamp', '00:00')}}]},
                        "生图词 (Prompt)": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]},
                        "视觉素材": {"files": [{"name": "story.jpg", "external": {"url": placeholder_img}}]}
                    }
                }
            )
        print(" -> ✅ 视觉分镜表已成功挂载回 Notion！")
    except Exception as e:
        print(f"❌ Notion 写入失败: {e}")

# ==========================================
# 3. 主程序
# ==========================================
def process_magazine():
    # 东京时间 UTC+9
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 视觉分镜自动化流启动 | 日期: {today} ===")
    
    # 筛选：有音频，但还没生成分镜的任务
    tasks_response = notion.request(
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
    )
    tasks = tasks_response.get("results", [])

    if not tasks:
        print("今日无新音频任务。")
        return

    for page in tasks:
        page_id = page["id"]
        
        # 检查是否已经存在分镜库（通过查找页面 Block）
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        if any(b["type"] == "child_database" for b in blocks):
            print(f" -> 跳过 Page {page_id}: 分镜库已存在。")
            continue

        audio_files = page["properties"].get("深度解析音频", {}).get("files", [])
        audio_url = audio_files[0].get("file", {}).get("url") or audio_files[0].get("external", {}).get("url")
        style_seed = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "白色、淡蓝色、极简科技感"

        print(f"\n--- 开始为音频生成视觉方案: {page_id} ---")
        
        chapters = analyze_audio_and_generate_data(audio_url, style_seed)
        if chapters:
            create_inline_storyboard(page_id, chapters)

if __name__ == "__main__":
    process_magazine()
