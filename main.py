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
    child_page_id = None
    blocks = []
    has_more = True
    next_cursor = None
    while has_more:
        url = f"blocks/{page_id}/children?page_size=100"
        if next_cursor:
            url += f"&start_cursor={next_cursor}"
        res = notion.request(path=url, method="GET")
        blocks.extend(res.get("results", []))
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")
        
    for block in blocks:
        if block["type"] == "child_page":
            if "深度解析脚本" in block["child_page"]["title"]:
                child_page_id = block["id"]
                break
                
    page_script = ""
    if child_page_id:
        child_blocks = []
        has_more = True
        next_cursor = None
        while has_more:
            url = f"blocks/{child_page_id}/children?page_size=100"
            if next_cursor:
                url += f"&start_cursor={next_cursor}"
            res = notion.request(path=url, method="GET")
            child_blocks.extend(res.get("results", []))
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
            
        for block in child_blocks:
            b_type = block["type"]
            if b_type in ["paragraph", "callout", "quote", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
                text = "".join([t["plain_text"] for t in block[b_type].get("rich_text", [])])
                if text.strip():
                    page_script += text.strip() + "\n"
                    
        page_script = page_script.strip()
        if len(page_script) > 10:
            print(" -> 已成功从子页面提取剧本。")
            return page_script

    try:
        page_info = notion.request(path=f"pages/{page_id}", method="GET")
        prop_script = "".join([t["plain_text"] for t in page_info["properties"].get("深度解析脚本", {}).get("rich_text", [])])
        if len(prop_script) > 10:
            print(" -> 未发现子页面，已从属性列提取短剧本。")
            return prop_script
    except Exception:
        pass
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
        # ⚠️ 增加了 timeout 到 300 秒，防止长文合成超时
        response = requests.post(url, json=data, headers=headers, timeout=300)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
        else:
            print(f"ElevenLabs 报错: {response.text}")
    except Exception as e:
        print(f"语音合成失败: {e}")
    return False

def generate_visual_assets(page_id, script_text, style_seed):
    print(f"正在根据风格 [{style_seed}] 拆解视觉分镜...")
    
    # ⚠️ 增加冷却时间至 60 秒，彻底解决免费版频率限制
    print(" -> 为确保长剧本处理不触发限制，强制冷却中 (60s)...")
    time.sleep(60)
    
    prompt = f"""
    请根据以下视频剧本和给定的视觉风格种子 '{style_seed}'，将剧本拆分为 10 个视频章节。
    请输出纯 JSON 格式的数组。
    格式示例：
    [ {{"chapter": "标题", "timestamp": "00:00", "prompt": "视觉提示词"}} ]
    剧本内容：{script_text[:3000]}
    """
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=prompt
        )
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        chapters = json.loads(json_str)
        
        new_db = notion.request(
            path="databases",
            method="POST",
            body={
                "parent": {"type": "page_id", "page_id": page_id},
                "title": [{"type": "text", "text": {"content": f"🎬 YouTube 翻页素材库 (风格: {style_seed})" }}],
                "properties": {
                    "章节标题": {"title": {}},
                    "建议时间戳": {"rich_text": {}},
                    "视觉提示词 (Prompt)": {"rich_text": {}}
                }
            }
        )
        db_id = new_db["id"]
        
        for item in chapters:
            notion.request(
                path="pages",
                method="POST",
                body={
                    "parent": {"database_id": db_id},
                    "properties": {
                        "章节标题": {"title": [{"text": {"content": item.get('chapter', '未命名')}}]},
                        "建议时间戳": {"rich_text": [{"text": {"content": item.get('timestamp', '00:00')}}]},
                        "视觉提示词 (Prompt)": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]}
                    }
                }
            )
        print(" -> 视觉分镜素材库已成功建立！")
    except Exception as e:
        print(f"视觉分镜生成失败: {e}")

def process_magazine():
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    print(f"=== 开始执行人机协同制片流 | 日期: {today} ===")
    
    try:
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
    except Exception as e:
        print(f"⚠️ 无法查询 Notion 表格: {e}")
        return

    if not tasks:
        print(f"未发现今天 ({today}) 需要处理的配音任务。")
        return

    for page in tasks:
        page_id = page["id"]
        seed_prop = page["properties"].get("视觉风格种子", {}).get("rich_text", [])
        style_seed = "".join([t["plain_text"] for t in seed_prop]) if seed_prop else "白色、淡蓝色、极简科技感"
        
        print(f"\n--- 开始处理 Page ID: {page_id} ---")

        print("1. 正在从 Notion 读取剧本...")
        script_text = get_script_from_notion(page_id)
        
        if not script_text:
            print("⚠️ 未能找到剧本，跳过。")
            continue
            
        print(f" -> 成功获取 {len(script_text)} 字剧本。")

        print("2. ElevenLabs 正在生成配音...")
        audio_path = f"/tmp/{page_id}.mp3"
        if text_to_speech(script_text, audio_path):
            print(" -> 正在上传音频至 Cloudinary...")
            upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
            audio_url = upload_result.get("secure_url")
            
            notion.request(
                path=f"pages/{page_id}",
                method="PATCH",
                body={"properties": {"深度解析音频": {"files": [{"name": "ChaoJ_Audio.mp3", "external": {"url": audio_url}}]}}}
            )
            print(" -> 音频链接已挂载回 Notion。")
        
        print("3. 正在规划视频翻页镜头...")
        generate_visual_assets(page_id, script_text, style_seed)

        print("4. 清理临时文件...")
        if os.path.exists(audio_path): os.remove(audio_path)
        
        print(f"=== 此任务流执行完毕！===")

if __name__ == "__main__":
    process_magazine()
