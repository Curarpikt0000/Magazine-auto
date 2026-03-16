import os
import requests
import base64
import time
from google import genai

# 配置
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_TOKEN = os.environ.get("GH_PAT")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def fix_and_push(error_log):
    # ⚠️ 关键：先睡一分钟，避开导致报错的频率高峰
    print("🤖 发现主程序崩溃，先冷静 60 秒等待 API 额度恢复...")
    time.sleep(60)
    
    print("🤖 正在读取现状并请求 AI 诊断修复方案...")
    
    with open("main.py", "r") as f:
        current_code = f.read()

    prompt = f"""
    我的 GitHub Action 运行失败了。报错是 429 频率超限。
    错误日志: {error_log}
    
    当前代码: {current_code}
    
    请帮我把所有调用 generate_content 的地方都包裹在一个 while True 的重试循环里。
    遇到 429 错误时，sleep 30 秒再重试。
    只需输出完整代码，不要 markdown 格式。
    """
    
    try:
        # 尝试修复
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        fixed_code = response.text.strip().replace("```python", "").replace("```", "")

        # 推送回 GitHub
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/main.py"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        sha = requests.get(url, headers=headers).json().get("sha")

        payload = {
            "message": "🤖 AI Self-Healing: Added robust retry logic for 429 errors",
            "content": base64.b64encode(fixed_code.encode()).decode(),
            "sha": sha
        }
        
        requests.put(url, json=payload, headers=headers)
        print("✅ 自愈完成：更健壮的代码已推送到仓库。")
    except Exception as e:
        print(f"❌ 自愈程序也撞上限制了，请稍后再试: {e}")

if __name__ == "__main__":
    if os.path.exists("error.log") and os.path.getsize("error.log") > 0:
        with open("error.log", "r") as f:
            fix_and_push(f.read())
