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
# 初始化 Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数
# ==========================================

def get_script_content(page_id):
    """从子页面提取剧本文字，避开音频读取的兼容性问题"""
    child_page_id = None
    blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
    for block in blocks:
        if block["type"] == "child_page" and "深度解析脚本" in block["child_page"]["title"]:
            child_page_id = block["id"]
            break
            
    if not child_page_id: return None
    
    script_text = ""
    child_blocks = notion.request(path=f"blocks/{child_page_id}/children", method="GET").get("results", [])
    for b in child_blocks:
        b_type = b["type"]
        if b_type in ["paragraph", "heading_1", "heading_2", "heading_3", "callout", "quote"]:
            text = "".join([t["plain_text"] for t in b[b_type].get("rich_text", [])])
            script_text += text + "\n"
    return script_text

def generate_storyboard_data(script_text, style_seed):
    """基于文字剧本生成 10 个视觉分镜方案"""
    print(" -> 🧠 Gemini 正在构思视觉方案...")
    time.sleep(5) # 基础冷却
    
    prompt = f"""
    根据以下剧本和风格种子 '{style_seed}'，规划 10 个视频分镜。
    请输出纯 JSON 数组，格式：[ {{"time": "00:00", "title": "描述", "prompt": "英文生图提示词"}} ]
    剧本内容：{script_text[:3000]}
    """
    try:
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return json.loads(response.text.strip().removeprefix("```json").removesuffix("```").strip())
    except Exception as e:
        print(f"❌ 分镜构思失败: {e}")
        return None

def create_notion_gallery(page_id, chapters):
    """在 Notion 页面内创建 Inline Database 并自动填充生成的 AI 图片"""
    print(f" -> 🎬 启动视觉工厂，正在生成 10 张高清分镜图...")
    
    try:
        # 1. 创建内嵌数据库
        new_db = notion.request(
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": page_id},
                "title": [{"type": "text", "text": {"content": "🎬 YouTube 剪辑素材库 (AI Generated)"}}],
                "properties": {
                    "分镜描述": {"title": {}},
                    "建议时间戳": {"rich_text": {}},
                    "视觉素材": {"files": {}},
                    "AI Prompt": {"rich_text": {}}
                }
            }
        )
        db_id = new_db["id"]

        # 2. 循环生图并挂载
        for item in chapters:
            print(f"    🎨 绘图中: {item['title']}...")
            
            # 使用 Gemini 3 Flash Image 生图 (Paid Tier 接口)
            # 💡 注意：此处假设您使用的是官方最新 genai SDK 的生图方法
            img_response = client.models.generate_images(
                model='gemini-3-flash-image',
                prompt=item['prompt'],
                config={'number_of_images': 1}
            )
            
            # 获取图片字节流并上传到 Cloudinary
            image_bytes = img_response.generated_images[0].image_bytes
            upload_res = cloudinary.uploader.upload(image_bytes, resource_type="image")
            img_url = upload_res.get("secure_url")

            # 写入 Notion
            notion.request(
                path="pages",
                method="POST",
                body={
                    "parent": {"database_id": db_id},
                    "properties": {
                        "分镜描述": {"title": [{"text": {"content": item['title']}}]},
                        "建议时间戳": {"rich_text": [{"text": {"content": item['time']}}]},
                        "AI Prompt": {"rich_text": [{"text": {"content": item['prompt']}}]},
                        "视觉素材": {"files": [{"name": "story.jpg", "external": {"url": img_url}}]}
                    }
                }
            )
            time.sleep(2) # 避免 Notion API 频率过快
            
        print(" -> ✅ 全部分镜图已生成并挂载完成！")
    except Exception as e:
        print(f"❌ 视觉工厂执行出错: {e}")

# ==========================================
# 3. 执行流
# ==========================================
def main():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 视觉工厂启动 | {today} ===")
    
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
        
        # 检查是否已有分镜库，防止重复生成
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        if any(b["type"] == "child_database" for b in blocks): continue

        # 1. 获取剧本文字
        script_text = get_script_content(page_id)
        if not script_text:
            print(f" -> 跳过 {page_id}：未找到‘深度解析脚本’页面。")
            continue
            
        # 2. 获取风格种子
        style_seed = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"

        # 3. 构思分镜
        chapters = generate_storyboard_data(script_text, style_seed)
        
        # 4. 生图并建库
        if chapters:
            create_notion_gallery(page_id, chapters)

if __name__ == "__main__":
    main()
