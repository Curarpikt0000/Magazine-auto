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
# 初始化客户端
client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数
# ==========================================

def get_script_content(page_id):
    """从子页面提取剧本文字"""
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
    time.sleep(2)
    
    prompt = f"""
    根据以下剧本和风格种子 '{style_seed}'，规划 10 个视频分镜。
    请输出纯 JSON 数组，格式：[ {{"time": "00:00", "title": "描述", "prompt": "英文生图提示词"}} ]
    剧本内容：{script_text[:3000]}
    """
    try:
        # 使用 2.0 Flash 生成文本 JSON
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(text)
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

        # 2. 循环生图并挂载
        for index, item in enumerate(chapters):
            print(f"    🎨 [{index+1}/10] 绘图中: {item['title']}...")
            
            try:
                # ⚠️ 修正后的生图调用方式
                img_response = client.models.generate_content(
                    model='gemini-3-flash-image', # 使用生图模型名称
                    contents=item['prompt']
                )
                
                # 处理生图返回（通常返回的是生成的图像对象）
                # 注意：如果 SDK 返回的是特殊格式，可能需要根据具体 response 结构提取
                image_data = img_response.generated_images[0].image_bytes
                
                # 上传到 Cloudinary
                upload_res = cloudinary.uploader.upload(image_data, resource_type="image")
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
            except Exception as e:
                print(f"    ⚠️ 第 {index+1} 张图生成或挂载失败，跳过: {e}")
                continue
            
            time.sleep(1) # 频率保护
            
        print(" -> ✅ 视觉工厂任务处理完毕！")
    except Exception as e:
        print(f"❌ 数据库创建失败: {e}")

# ==========================================
# 3. 主程序入口
# ==========================================
def main():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.date().isoformat()
    print(f"=== 视觉工厂启动 | {today} ===")
    
    # 筛选任务
    query_body = {
        "filter": {
            "and": [
                {"property": "Category", "select": {"equals": "杂志"}},
                {"property": "阅读日期", "date": {"equals": today}},
                {"property": "深度解析音频", "files": {"is_not_empty": True}}
            ]
        }
    }
    
    tasks = notion.request(path=f"databases/{DATABASE_ID}/query", method="POST", body=query_body).get("results", [])

    for page in tasks:
        page_id = page["id"]
        
        # 查重：若已有分镜库则不再生成
        blocks = notion.request(path=f"blocks/{page_id}/children", method="GET").get("results", [])
        if any(b["type"] == "child_database" for b in blocks):
            print(f" -> 任务 {page_id} 已有分镜，跳过。")
            continue

        # 1. 提取文本
        script_text = get_script_content(page_id)
        if not script_text:
            print(f" -> 跳过 {page_id}：未找到‘深度解析脚本’页面。")
            continue
            
        # 2. 风格种子
        style_seed = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"

        # 3. 规划分镜
        chapters = generate_storyboard_data(script_text, style_seed)
        
        # 4. 执行生产
        if chapters:
            create_notion_gallery(page_id, chapters)

if __name__ == "__main__":
    main()
