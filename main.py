import os
import datetime
import requests
import json
import google.generativeai as genai
from notion_client import Client
import cloudinary
import cloudinary.uploader

# ==========================================
# 1. 环境与密钥配置 (从 GitHub Secrets 获取)
# ==========================================
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")

# 初始化客户端
notion = Client(auth=NOTION_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# ==========================================
# 2. 核心功能函数库
# ==========================================

def download_file(url, local_path):
    """从 Notion 下载 PDF 杂志到本地临时目录"""
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

def write_script_to_notion(page_id, script_text):
    """智能写入脚本：判断字数，超长则自动拆分写入页面正文"""
    if len(script_text) <= 2000:
        notion.pages.update(
            page_id=page_id,
            properties={
                "深度解析脚本": {"rich_text": [{"text": {"content": script_text}}]}
            }
        )
        print(" -> 脚本较短，已直接写入属性列。")
    else:
        # 写入提示到属性列
        notion.pages.update(
            page_id=page_id,
            properties={
                "深度解析脚本": {"rich_text": [{"text": {"content": "⚠️ 剧本字数超限，完整内容已写入下方页面正文。"}}]}
            }
        )
        
        # 插入一个分隔线和标题
        notion.blocks.children.append(
            block_id=page_id,
            children=[
                {"type": "divider", "divider": {}},
                {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🎙️ AI 深度解析剧本"}}]}}
            ]
        )
        
        # 将长文本切片（每 1500 字一块）写入正文
        chunks = [script_text[i:i+1500] for i in range(0, len(script_text), 1500)]
        children_blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
            } for chunk in chunks
        ]
        notion.blocks.children.append(block_id=page_id, children=children_blocks)
        print(" -> 脚本较长，已安全切割并写入页面正文。")

def text_to_speech(text, output_path):
    """调用 ElevenLabs 生成音频"""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVEN_API_KEY
    }
    # 截断过长文本以防 API 报错 (ElevenLabs 基础额度单次可能限制 5000 字符)
    safe_text = text[:4900] 
    data = {
        "text": safe_text,
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
    """利用 Gemini 拆解章节，并在 Notion 内创建 Inline Database 素材库"""
    print(f"正在根据风格 [{style_seed}] 拆解视觉分镜...")
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    prompt = f"""
    请根据以下视频剧本和给定的视觉风格种子 '{style_seed}'，将剧本拆分为 10 个视频章节。
    请输出纯 JSON 格式的数组，不要有 markdown 标记。
    格式示例：
    [
      {{"chapter": "章节标题(5字内)", "timestamp": "00:00", "prompt": "用于生成动态背景的极简英文视觉提示词，必须包含风格种子元素"}}
    ]
    
    剧本内容：
    {script_text[:3000]}
    """
    
    try:
        response = model.generate_content(prompt)
        # 清理可能存在的 markdown code block 标记
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        chapters = json.loads(json_str)
        
        # 在 Notion 页面内创建一个新的 Database
        new_db = notion.databases.create(
            parent={"page_id": page_id},
            title=[{"type": "text", "text": {"content": f"🎬 YouTube 翻页素材库 (风格: {style_seed})" }}],
            properties={
                "章节标题": {"title": {}},
                "建议时间戳": {"rich_text": {}},
                "视觉提示词 (Prompt)": {"rich_text": {}}
            }
        )
        db_id = new_db["id"]
        
        # 将生成的章节写入新建立的内嵌数据库
        for item in chapters:
            notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "章节标题": {"title": [{"text": {"content": item.get('chapter', '未命名')}}]},
                    "建议时间戳": {"rich_text": [{"text": {"content": item.get('timestamp', '00:00')}}]},
                    "视觉提示词 (Prompt)": {"rich_text": [{"text": {"content": item.get('prompt', '')}}]}
                }
            )
        print(" -> 视觉分镜素材库已成功建立在 Notion 页面中！")
    except Exception as e:
        print(f"视觉分镜生成失败: {e}")


# ==========================================
# 3. 主干执行流程
# ==========================================

def process_magazine():
    # 统一使用 JST 时间 (UTC+9)，确保和您阅读的“今天”对齐
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    print(f"=== 开始执行自动制片流 | 日期: {today} ===")
    
    # 筛选待处理任务
    query = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "and": [
                {"property": "Category", "select": {"equals": "杂志"}},
                {"property": "阅读日期", "date": {"equals": today}},
                {"property": "深度解析脚本", "rich_text": {"is_empty": True}}
            ]
        }
    )
    
    tasks = query.get("results")
    if not tasks:
        print(f"未发现今天 ({today}) 需要处理的杂志任务。")
        return

    model = genai.GenerativeModel('gemini-1.5-pro')

    for page in tasks:
        page_id = page["id"]
        
        # [提取属性] 脚本要求
        req_prop = page["properties"].get("脚本要求", {}).get("rich_text", [])
        instruction = "".join([t["plain_text"] for t in req_prop]) if req_prop else "请写一份深度讲解脚本。"
        
        # [提取属性] 视觉风格种子
        seed_prop = page["properties"].get("视觉风格种子", {}).get("rich_text", [])
        style_seed = "".join([t["plain_text"] for t in seed_prop]) if seed_prop else "白色、淡蓝色、极简科技感"
        
        # [提取属性] 获取文件 URL
        files = page["properties"].get("Files & Media", {}).get("files", [])
        if not files:
            print(f"跳过页面 {page_id}：没有找到杂志文件。")
            continue
            
        file_info = files[0]
        file_url = file_info.get("file", {}).get("url") or file_info.get("external", {}).get("url")
        file_name = file_info.get("name", "magazine.pdf")
        local_file_path = os.path.join("/tmp", file_name)

        print(f"\n--- 开始处理: {file_name} ---")

        # 步骤 1: 下载文件
        print("1. 正在下载杂志 PDF...")
        if not download_file(file_url, local_file_path):
            continue

        # 步骤 2: Gemini 分析并生成脚本
        print("2. Gemini 正在深度阅读并创作剧本...")
        gemini_file = genai.upload_file(path=local_file_path)
        response = model.generate_content([instruction, gemini_file])
        generated_script = response.text
        write_script_to_notion(page_id, generated_script)

        # 步骤 3: ElevenLabs 生成语音并上传
        print("3. ElevenLabs 正在生成 ChaoJ 的配音...")
        audio_path = f"/tmp/{page_id}.mp3"
        if text_to_speech(generated_script, audio_path):
            print(" -> 正在上传音频至 Cloudinary...")
            upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
            audio_url = upload_result.get("secure_url")
            
            # 更新 Notion 音频列
            notion.pages.update(
                page_id=page_id,
                properties={
                    "深度解析音频": {"files": [{"name": "ChaoJ_Audio.mp3", "external": {"url": audio_url}}]}
                }
            )
            print(" -> 音频链接已挂载回 Notion。")
        
        # 步骤 4: Gemini 生成视觉素材分镜库
        print("4. 正在规划视频翻页镜头...")
        generate_visual_assets(page_id, generated_script, style_seed)

        # 步骤 5: 清理临时文件
        print("5. 清理临时环境...")
        if os.path.exists(local_file_path): os.remove(local_file_path)
        if os.path.exists(audio_path): os.remove(audio_path)
        genai.delete_file(gemini_file.name) # 释放 Gemini 云端存储
        
        print(f"=== {file_name} 自动化流程全部完成！===")

if __name__ == "__main__":
    process_magazine()
