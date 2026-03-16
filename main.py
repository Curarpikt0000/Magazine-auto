import os
import datetime
import requests
import json
import time
from google import genai
from notion_client import Client
import cloudinary
import cloudinary.uploader
import fitz  # ⚠️ 引入工业级 PyMuPDF 解析库

# ==========================================
# 1. 环境与密钥配置
# ==========================================
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")

# 强制锁定 Notion 服务器处理版本为最经典的 2022-06-28，防止 API 更新导致的报错
notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数库
# ==========================================
def download_file(url, local_path):
    try:
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"下载文件失败: {e}")
    return False

def extract_text_from_pdf(pdf_path, max_chars=40000):
    """使用工业级 PyMuPDF 解析复杂杂志文本，过滤图片，限制字数防超载"""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            extracted = page.get_text()
            if extracted:
                text += extracted + "\n"
            # 达到字数限制提前结束，避免浪费算力
            if len(text) > max_chars:
                break
        doc.close()
    except Exception as e:
        print(f"⚠️ PDF 本地解析出错: {e}")
        
    if len(text.strip()) < 100:
        print("⚠️ 警告：提取到的有效文字极少！这可能是一本全图片/扫描版杂志。")
        
    return text[:max_chars]

def write_script_to_notion(page_id, script_text):
    # 放弃使用页面的 update 方法，直接调用底层 API 写入，绕过 SDK 限制
    if len(script_text) <= 2000:
        notion.request(
            path=f"pages/{page_id}",
            method="PATCH",
            body={"properties": {"深度解析脚本": {"rich_text": [{"text": {"content": script_text}}]}}}
        )
        print(" -> 脚本较短，已直接写入属性列。")
    else:
        notion.request(
            path=f"pages/{page_id}",
            method="PATCH",
            body={"properties": {"深度解析脚本": {"rich_text": [{"text": {"content": "⚠️ 剧本字数超限，完整内容已写入下方页面正文。"}}]}}}
        )
        
        children_blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🎙️ AI 深度解析剧本"}}]}}
        ]
        chunks = [script_text[i:i+1500] for i in range(0, len(script_text), 1500)]
        for chunk in chunks:
            children_blocks.append(
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}}
            )
            
        notion.request(
            path=f"blocks/{page_id}/children",
            method="PATCH",
            body={"children": children_blocks}
        )
        print(" -> 脚本较长，已安全切割并写入页面正文。")

def text_to_speech(text, output_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVEN_API_KEY
    }
    data = {
        "text": text[:4900],
        "model_id": "eleven_multilingual_v3",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=60)
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
        
        # 直接发送 HTTP POST 请求新建内嵌表格，绕过 SDK
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

# ==========================================
# 3. 主干执行流程
# ==========================================
def process_magazine():
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    print(f"=== 开始执行自动制片流 | 日期: {today} ===")
    
    try:
        # 彻底抛弃 .query() 语法，直接请求数据库内容
        tasks_response = notion.request(
            path=f"databases/{DATABASE_ID}/query",
            method="POST",
            body={
                "filter": {
                    "and": [
                        {"property": "Category", "select": {"equals": "杂志"}},
                        {"property": "阅读日期", "date": {"equals": today}},
                        {"property": "深度解析脚本", "rich_text": {"is_empty": True}}
                    ]
                }
            }
        )
        tasks = tasks_response.get("results", [])
    except Exception as e:
        print(f"⚠️ 无法查询 Notion 表格: {e}")
        return

    if not tasks:
        print(f"未发现今天 ({today}) 需要处理的杂志任务。")
        return

    for page in tasks:
        page_id = page["id"]
        
        req_prop = page["properties"].get("脚本要求", {}).get("rich_text", [])
        instruction = "".join([t["plain_text"] for t in req_prop]) if req_prop else "请写一份深度讲解脚本。"
        
        seed_prop = page["properties"].get("视觉风格种子", {}).get("rich_text", [])
        style_seed = "".join([t["plain_text"] for t in seed_prop]) if seed_prop else "白色、淡蓝色、极简科技感"
        
        # 兼容 Files & Media 与 Files & media
        files = page["properties"].get("Files & Media", {}).get("files", [])
        if not files:
            files = page["properties"].get("Files & media", {}).get("files", [])
            
        if not files:
            print(f"跳过页面 {page_id}：没有找到杂志文件。")
            continue
            
        file_info = files[0]
        file_url = file_info.get("file", {}).get("url") or file_info.get("external", {}).get("url")
        file_name = file_info.get("name", "magazine.pdf")
        local_file_path = os.path.join("/tmp", file_name)

        print(f"\n--- 开始处理: {file_name} ---")

        print("1. 正在下载杂志 PDF...")
        if not download_file(file_url, local_file_path):
            continue

        print("2. 正在本地提取 PDF 纯文本 (智能瘦身)...")
        pdf_text = extract_text_from_pdf(local_file_path, max_chars=40000)
        print(f" -> 成功提取 {len(pdf_text)} 字核心内容。")

        print("3. Gemini 正在基于纯文本创作剧本...")
        # 将指令和纯文本合并为单一 prompt 发送
        combined_prompt = f"{instruction}\n\n以下是杂志提取的核心内容：\n{pdf_text}"
        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=combined_prompt
        )
        generated_script = response.text
        write_script_to_notion(page_id, generated_script)

        print("4. ElevenLabs 正在生成配音...")
        audio_path = f"/tmp/{page_id}.mp3"
        if text_to_speech(generated_script, audio_path):
            print(" -> 正在上传音频至 Cloudinary...")
            upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
            audio_url = upload_result.get("secure_url")
            
            # 使用原生 request 挂载音频
            notion.request(
                path=f"pages/{page_id}",
                method="PATCH",
                body={"properties": {"深度解析音频": {"files": [{"name": "ChaoJ_Audio.mp3", "external": {"url": audio_url}}]}}}
            )
            print(" -> 音频链接已挂载回 Notion。")
        
        print("5. 正在规划视频翻页镜头...")
        generate_visual_assets(page_id, generated_script, style_seed)

        print("6. 清理临时环境...")
        if os.path.exists(local_file_path): os.remove(local_file_path)
        if os.path.exists(audio_path): os.remove(audio_path)
        
        print(f"=== {file_name} 自动化流程全部完成！===")

if __name__ == "__main__":
    process_magazine()
