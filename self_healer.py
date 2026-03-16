import os
import requests
import base64
from google import genai

# 配置
GITHUB_REPO = "你的用户名/Magazine-auto" # ⚠️ 修改这里
GITHUB_TOKEN = os.environ.get("GH_PAT")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def fix_and_push(error_log):
    # 1. 读取当前的 main.py
    with open("main.py", "r") as f:
        current_code = f.read()

    # 2. 呼叫 Gemini 进行诊断和修复
    prompt = f"""
    我的 GitHub Action 运行失败了。
    报错信息如下:
    {error_log}

    当前 main.py 代码如下:
    {current_code}

    请分析错误并输出修正后的完整 main.py 代码。
    注意：只输出代码内容，不要任何解释。
    """
    
    response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
    fixed_code = response.text.strip().replace("```python", "").replace("```", "")

    # 3. 通过 API 推送回 GitHub
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/main.py"
    
    # 获取文件 sha (更新必须)
    res = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    sha = res.json().get("sha")

    payload = {
        "message": "🤖 AI Self-Healing: Fixed runtime error",
        "content": base64.b64encode(fixed_code.encode()).decode(),
        "sha": sha
    }
    
    requests.put(url, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    print("✅ 自愈完成：修正后的代码已推送。")

if __name__ == "__main__":
    # 这里模拟读取上一步运行的错误日志
    if os.path.exists("error.log"):
        with open("error.log", "r") as f:
            fix_and_push(f.read())
