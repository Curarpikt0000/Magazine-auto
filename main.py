import os
import datetime
import requests
import google.generativeai as genai
from notion_client import Client

# 环境配置
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# 初始化客户端
notion = Client(auth=NOTION_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

def download_file(url, local_path):
    """从 Notion URL 下载文件到本地"""
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    return False

def process_magazine():
    # 获取东京时间 (JST) 的今天日期
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    
    # 筛选逻辑：Category="杂志" 且 阅读日期为今天
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
        print(f"[{today}] 未发现待处理的杂志任务。")
        return

    model = genai.GenerativeModel('gemini-1.5-pro')

    for page in tasks:
        page_id = page["id"]
        # 读取“脚本要求”列的内容
        req_prop = page["properties"].get("脚本要求", {}).get("rich_text", [])
        instruction = "".join([t["plain_text"] for t in req_prop]) if req_prop else "请写一份深度讲解脚本。"
        
        # 获取 Files & Media 链接
        files = page["properties"].get("Files & Media", {}).get("files", [])
        if not files: continue
        
        file_info = files[0]
        file_url = file_info.get("file", {}).get("url") or file_info.get("external", {}).get("url")
        file_name = file_info.get("name", "magazine.pdf")
        local_file_path = os.path.join("/tmp", file_name)

        # 1. 下载文件到本地
        print(f"正在下载文件: {file_name}...")
        if download_file(file_url, local_file_path):
            # 2. 上传文件至 Gemini
            print(f"正在上传至 Gemini 进行分析...")
            gemini_file = genai.upload_file(path=local_file_path, mime_type="application/pdf")
            
            # 3. 生成内容
            response = model.generate_content([instruction, gemini_file])
            generated_script = response.text
            
            # 4. 回写 Notion 脚本列
            notion.pages.update(
                page_id=page_id,
                properties={
                    "深度解析脚本": {
                        "rich_text": [{"text": {"content": generated_script}}]
                    }
                }
            )
            print(f"成功！已为 {file_name} 生成深度解析脚本。")
            
            # 清理临时文件
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
        else:
            print(f"下载失败: {file_url}")

if __name__ == "__main__":
    process_magazine()
