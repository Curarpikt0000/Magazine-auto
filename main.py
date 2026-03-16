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
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")

notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数库
# ==========================================

def get_script_from_notion(page_id):
    """
    智能读取剧本：寻找名为“深度解析脚本”的子页面并提取全文
    """
    child_page_id = None
    blocks = []
    has_more = True
    next_cursor = None
    while has_more:
        url = f"blocks/{page_id}/children?page_size=100"
        if next_cursor: url += f"&start_cursor={next_cursor}"
        res = notion.request(path=url, method="GET")
        blocks.extend(res.get("results", []))
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")
        
    for block in blocks:
        if block["type"] == "child_page" and "深度解析脚本" in block["child_page"]["title"]:
            child_page_id = block["id"]
            break
                
    page_script = ""
    if child_page_id:
        child_blocks = []
        has_more = True
        next_cursor = None
        while has_more:
            url = f"blocks/{child_page_id}/children?page_size=100"
            if next_cursor: url += f"&start_cursor={next_cursor}"
            res = notion.request(path=url, method="GET")
            child_blocks.extend(res.get("results", []))
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
            
        for block in child_blocks:
            b_type = block["type"]
            if b_type in ["paragraph", "callout", "quote", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
                rich_text = block[b_type].get("rich_text", [])
                text = "".join([t["plain_text"] for t in rich_text])
                if text.strip(): page_script += text.strip() + "\n"
                    
        page_script = page_script.strip()
        if len(page_script) > 10:
            print(" -> 已成功从子页面提取剧本。")
            return page_script

    # 备用：从属性列读取
    try:
        page_info = notion.request(path=f"pages/{page_id}", method="GET")
        prop_script = "".join([t["plain_text"] for t in page_info["properties"].get("深度解析脚本", {}).get("rich_text", [])])
        if len(prop_script) > 10:
            print(" -> 未发现子页面，已从属性列提取短剧本。")
            return prop_script
    except: pass
    return None

def text_to_speech(text, output_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVEN_API_KEY
    }
    data = {
        "text": text[:4900],
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    try:
        # 增加超时到 600 秒
        response = requests.post(url, json=data, headers=headers, timeout=600)
        if response.status_code == 200:
            with open(output_path, "wb") as f: f.write(response.content)
            return True
        else:
            print(f"ElevenLabs 报错: {response.text}")
    except Exception as e:
        print(f"语音合成失败: {e}")
    return False

def generate_visual_assets(page_id, script_text, style_seed):
    print(f"正在拆解视觉分镜 (风格: {style_seed})...")
    
    # 强制冷却 90 秒，应对长文 Token 压力
    print(" -> 等待 Gemini 令牌桶恢复 (90s)...")
    time.sleep(90)
    
    prompt = f"根据以下剧本和风格种子 '{style_seed}'，输出 10 个章节的 JSON 数组（chapter, timestamp, prompt）。剧本：{script_text[:3000]}"
    
    success = False
    for attempt in range(2): # 增加一次自动重试机制
        try:
            response = gemini_client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            chapters = json.loads(json_str)
            
            # 创建子数据库
            new_db = notion.request(
                path="databases",
                method="POST",
                body={
                    "parent": {"type": "page_id", "page_id": page_id},
                    "title": [{"type": "text", "text": {"content": "🎬 YouTube 翻页素材库" }}],
                    "properties": {
                        "章节标题": {"title": {}},
                        "建议时间戳": {"rich_text": {}},
                        "视觉提示词 (Prompt)": {"rich_text": {}}
                    }
                }
            )
            
            for item in chapters:
                notion.request(
                    path="pages",
                    method="POST",
                    body={
                        "parent": {"database_id": new_db["id"]},
                        "properties": {
                            "章节标题": {"title": [{"text": {"content": item.get('chapter', 'N/A')}}]},
                            "建议时间戳": {"rich_text": [{"text": {"content": item.get('timestamp', '00:00')}}]},
                            "视觉提示词 (Prompt)": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]}
                        }
                    }
                )
            print(" -> 视觉素材库建立成功！")
            success = True
            break
        except Exception as e:
            print(f" -> 分镜生成尝试 {attempt+1} 失败: {e}")
            if "429" in str(e):
                print(" -> 触发高频限制，额外休眠 30 秒后重试...")
                time.sleep(30)
            else: break
    return success

# ==========================================
# 3. 执行主逻辑
# ==========================================
def process_magazine():
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    print(f"=== 自动制片流启动 | {today} ===")
    
    tasks_response = notion.request(
        path=f"databases/{DATABASE_ID}/query",
        method="POST",
        body={
            "filter": {
                "and": [
                    {"property": "Category", "select": {"equals": "杂志"}},
                    {"property": "阅读日期", "date": {"equals": today}},
                    {"property": "深度解析音频", "files": {"is_empty": True}}
                ]
            }
        }
    )
    tasks = tasks_response.get("results", [])

    if not tasks:
        print("今日无待处理配音任务。")
        return

    for page in tasks:
        page_id = page["id"]
        print(f"\n--- 处理任务: {page_id} ---")

        script_text = get_script_from_notion(page_id)
        if not script_text: continue
            
        print(f"1. 成功获取剧本 ({len(script_text)} 字)")

        print("2. 合成语音并上传...")
        audio_path = f"/tmp/{page_id}.mp3"
        if text_to_speech(script_text, audio_path):
            upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
            audio_url = upload_result.get("secure_url")
            
            # ⚠️ 关键修正：打印写入结果以供调试
            write_res = notion.request(
                path=f"pages/{page_id}",
                method="PATCH",
                body={"properties": {"深度解析音频": {"files": [{"name": "Voice.mp3", "external": {"url": audio_url}}]}}}
            )
            if "id" in write_res:
                print(f" -> ✅ 音频已成功挂载！URL: {audio_url}")
            else:
                print(f" -> ❌ 挂载失败，Notion 返回: {write_res}")
        
        # 3. 分镜
        style_seed = "".join([t["plain_text"] for t in page["properties"].get("视觉风格种子", {}).get("rich_text", [])]) or "极简科技感"
        generate_visual_assets(page_id, script_text, style_seed)

        if os.path.exists(audio_path): os.remove(audio_path)
        print("--- 任务完成 ---")

if __name__ == "__main__":
    process_magazine()
