import os
import time
from openai import OpenAI


def main():
    client = OpenAI(
        base_url="http://127.0.0.1:8045/v1",
        api_key=os.getenv("PONYCHAT_APIYI_API_KEY", ""),
        timeout=300,
        max_retries=0,
    )

    print("🔍 检查模型列表...")
    try:
        models = client.models.list()
        print(f"✅ 模型数量: {len(models.data) if hasattr(models, 'data') else 'unknown'}")
    except Exception as e:
        print(f"❌ 获取模型列表失败: {e}")
        return

    print("🎨 开始绘图请求...")
    start = time.time()
    response = client.chat.completions.create(
        model="gemini-3-pro-image",
        extra_body={"size": "1024x1024"},
        messages=[{"role": "user", "content": "Draw a futuristic city"}],
    )
    print(f"⏱️ 完成耗时: {time.time() - start:.1f}s")

    content = response.choices[0].message.content
    print(content)


if __name__ == "__main__":
    main()
