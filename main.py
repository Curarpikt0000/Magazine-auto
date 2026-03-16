import os
from notion_client import Client

notion = Client(auth=os.environ["NOTION_TOKEN"])

def write_script_to_notion(page_id, script_text):
    """
    判断字数并写入 Notion。
    如果超过 2000 字符，写入正文；否则写入属性列。
    """
    if len(script_text) <= 2000:
        # 字数较少，直接写入属性列
        notion.pages.update(
            page_id=page_id,
            properties={
                "深度解析脚本": {"rich_text": [{"text": {"content": script_text}}]}
            }
        )
        print("脚本已写入属性列。")
    else:
        # 字数超限，写入属性列作为提醒，并将全文写入正文
        notion.pages.update(
            page_id=page_id,
            properties={
                "深度解析脚本": {"rich_text": [{"text": {"content": "⚠️ 脚本较长，全文已写入页面正文。"}}] }
            }
        )
        
        # 将长文本按段落拆分，写入页面正文 (Notion 每个 Block 限制也是 2000 字符)
        # 这里我们将脚本切片，每 1500 字符作为一个段落 Block 写入
        chunks = [script_text[i:i+1500] for i in range(0, len(script_text), 1500)]
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                }
            } for chunk in chunks
        ]
        
        # 写入正文
        notion.blocks.children.append(block_id=page_id, children=children)
        print("脚本较长，已成功写入页面正文。")

def get_full_script_for_next_step(page_id):
    """
    供后续步骤（章节拆解）调用的函数：
    它会自动判断是从‘列’里读，还是从‘正文’里读。
    """
    page = notion.pages.retrieve(page_id=page_id)
    prop_text = "".join([t["plain_text"] for t in page["properties"]["深度解析脚本"]["rich_text"]])
    
    if "全文已写入页面正文" in prop_text:
        # 从正文提取所有 paragraph 类型的 blocks
        blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
        full_text = ""
        for block in blocks:
            if block["type"] == "paragraph":
                block_text = "".join([t["plain_text"] for t in block["paragraph"]["rich_text"]])
                full_text += block_text + "\n"
        return full_text
    else:
        return prop_text
