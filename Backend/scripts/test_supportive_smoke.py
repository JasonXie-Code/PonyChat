"""冒烟测试：验证远端测试链路通畅。只发一次请求，不操作数据库。"""
import asyncio, json, os, sys, time, uuid
import httpx

BASE = "http://127.0.0.1:5000"

def make_token(username):
    import base64, hmac
    exp = int(time.time()) + 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    pb64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(b"ponychat_default_secret_change_in_production", pb64.encode(), "sha256").digest()
    return f"{pb64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"

async def main():
    print("START", flush=True)
    t0 = time.time()
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/health", timeout=10)
        print(f"HEALTH: {r.status_code} {r.text[:200]}", flush=True)
    print(f"DONE in {time.time()-t0:.1f}s", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
