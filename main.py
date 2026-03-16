import os
import datetime
import requests
import google.generativeai as genai
from notion_client import Client
import cloudinary
import cloudinary.uploader

# 环境配置
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ELEVEN_API_KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]

# 初始化
notion = Client(auth=NOTION_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
cloudinary.config(cloudinary_url=os.environ["CLOUDINARY_URL"])

def text_to_speech(text, output_path):
    """调用 ElevenLabs V3 模型生成音频"""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVEN_API_KEY
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v3",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        return True
    return False

def process_magazine():
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    
    # 筛选：Category="杂志" + 今日日期 + 音频为空
    query = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "and": [
                {"property": "Category", "select": {"equals": "杂志"}},
                {"property": "阅读日期", "date": {"equals": today}},
                {"property": "深度解析音频", "files": {"is_empty": True}}
            ]
        }
    )
    
    for page in query.get("results", []):
        page_id = page["id"]
        # 1. 获取指令并使用 Gemini 生成脚本 (同上一步)
        # ... (此处省略上一步已实现的 Gemini 解析代码，获取 generated_script) ...
        
        # 2. 生成音频
        audio_path = f"/tmp/{page_id}.mp3"
        print("正在合成 ChaoJ 语音...")
        if text_to_speech(generated_script, audio_path):
            
            # 3. 上传至 Cloudinary 获取永久外链
            print("正在上传音频至云端...")
            upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
            audio_url = upload_result.get("secure_url")
            
            # 4. 更新 Notion (回写脚本 + 回写音频外链)
            notion.pages.update(
                page_id=page_id,
                properties={
                    "深度解析脚本": {"rich_text": [{"text": {"content": generated_script}}]},
                    "深度解析音频": {"files": [{"name": "深度解析音频.mp3", "external": {"url": audio_url}}]}
                }
            )
            print(f"成功！音频已就绪: {audio_url}")
