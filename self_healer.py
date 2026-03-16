import os, requests, base64, time
from google import genai

REPO = os.environ.get("GITHUB_REPO")
TOKEN = os.environ.get("GH_PAT")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def heal():
    if not os.path.exists("error.log") or os.path.getsize("error.log") == 0: return
    print("🤖 启动 AI 自愈...")
    time.sleep(60) # 物理避让 429 峰值

    with open("error.log", "r") as f: err = f.read()
    with open("main.py", "r") as f: code = f.read()

    prompt = f"我的代码报错了: {err}\n当前代码: {code}\n请直接输出修复后的完整代码，不要 markdown。"
    try:
        res = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        fixed = res.text.strip().replace("```python", "").replace("```", "")
        
        url = f"https://api.github.com/repos/{REPO}/contents/main.py"
        headers = {"Authorization": f"token {TOKEN}"}
        sha = requests.get(url, headers=headers).json().get("sha")
        
        requests.put(url, json={
            "message": "🤖 AI Self-Healing",
            "content": base64.b64encode(fixed.encode()).decode(),
            "sha": sha
        }, headers=headers)
        print("✅ 自愈完成。")
    except Exception as e: print(f"❌ 自愈失败: {e}")

if __name__ == "__main__": heal()
