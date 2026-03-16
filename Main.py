import os
import datetime
import requests
from notion_client import Client
import google.generativeai as genai

# 初始化环境
notion = Client(auth=os.environ["NOTION_TOKEN"])
DATABASE_ID = os.environ["DATABASE_ID"]
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

def process_magazine():
    # 获取东京时间 (JST) 的今天日期
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()
    
    # 1. 严格筛选：Category="杂志" + 阅读日期=今天 + 脚本为空
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
        print(f"[{today}] 没有发现待处理的杂志内容。")
        return

    model = genai.GenerativeModel('gemini-1.5-pro')

    for page in tasks:
        page_id = page["id"]
        # 获取“脚本要求”列的指令内容
        req_prop = page["properties"].get("脚本要求", {}).get("rich_text", [])
        instruction = "".join([t["plain_text"] for t in req_prop]) if req_prop else "请写一份深度讲解脚本。"
        
        # 获取 Files & Media 中的杂志文件
        files = page["properties"].get("Files & Media", {}).get("files", [])
        if not files: continue
        
        file_url = files[0].get("file", {}).get("url") or files[0].get("external", {}).get("url")
        
        # 2. 提取并解析 (此处模拟 Gemini 解析文件流程)
        # 实际操作中，Gemini API 可以直接接收文件流或先下载后再上传
        response = model.generate_content([instruction, f"分析此文件内容并生成脚本: {file_url}"])
        generated_script = response.text
        
        # 3. 回写脚本到 Notion
        notion.pages.update(
            page_id=page_id,
            properties={
                "深度解析脚本": {
                    "rich_text": [{"text": {"content": generated_script}}]
                }
            }
        )
        print(f"成功为页面 {page_id} 生成脚本！")

if __name__ == "__main__":
    process_magazine()
