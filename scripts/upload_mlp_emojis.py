"""一次性脚本：从 Derpibooru CDN 下载 4 张 MLP G4 表情包并上传到素材管理 API。"""
import json
import requests

API_BASE = "https://www.ponychat.org/api/admin/assets"

IMAGES = [
    {
        "url": "https://derpicdn.net/img/2016/10/19/1276533/full.gif",
        "filename": "twilight-not-cute.gif",
        "mime": "image/gif",
        "name": "暮光 - 我才不可爱",
        "category": "emoji",
        "emotions": ["shy", "cute", "smug"],
        "intensity": "mild",
        "scenes": ["tease", "casual"],
        "age_rating": "all",
        "description": "暮光闪闪眨眼否认自己可爱，反差萌动图",
        "custom_tags": ["暮光闪闪", "G4", "动图"],
    },
    {
        "url": "https://derpicdn.net/img/2019/4/6/2004900/medium.png",
        "filename": "mane6-shocked.png",
        "mime": "image/png",
        "name": "六人组 - 集体震惊",
        "category": "emoji",
        "emotions": ["surprised", "scared"],
        "intensity": "strong",
        "scenes": ["tease", "casual"],
        "age_rating": "all",
        "description": "六人组捂脸集体大惊失色，极度震惊反应表情包",
        "custom_tags": ["六人组", "G4", "主角团"],
    },
    {
        "url": "https://derpicdn.net/img/2016/12/29/1327325/medium.png",
        "filename": "twilight-laugh-cry.png",
        "mime": "image/png",
        "name": "暮光 - 笑到泪崩",
        "category": "emoji",
        "emotions": ["laugh", "excited", "happy"],
        "intensity": "strong",
        "scenes": ["tease", "casual", "celebrate"],
        "age_rating": "all",
        "description": "暮光闪闪笑到泪目捂嘴，适合搞笑调侃场景",
        "custom_tags": ["暮光闪闪", "G4", "笑cry"],
    },
    {
        "url": "https://derpicdn.net/img/2013/8/25/409940/full.gif",
        "filename": "aj-rarity-gasp.gif",
        "mime": "image/gif",
        "name": "苹果杰克&瑞瑞 - 倒吸冷气",
        "category": "emoji",
        "emotions": ["surprised", "scared"],
        "intensity": "moderate",
        "scenes": ["tease", "casual", "question"],
        "age_rating": "all",
        "description": "苹果杰克与瑞瑞同时惊讶倒吸冷气的动图",
        "custom_tags": ["苹果杰克", "瑞瑞", "G4", "动图"],
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (PonyChat/1.0)"}


def main():
    for img in IMAGES:
        print(f"\n[下载] {img['name']} ...")
        r = requests.get(img["url"], headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}，跳过")
            continue
        data = r.content
        print(f"  大小: {len(data) // 1024} KB")

        files = {
            "name": (None, img["name"]),
            "category": (None, img["category"]),
            "emotions": (None, json.dumps(img["emotions"], ensure_ascii=False)),
            "intensity": (None, img["intensity"]),
            "scenes": (None, json.dumps(img["scenes"], ensure_ascii=False)),
            "age_rating": (None, img["age_rating"]),
            "custom_tags": (None, json.dumps(img["custom_tags"], ensure_ascii=False)),
            "description": (None, img["description"]),
            "file": (img["filename"], data, img["mime"]),
        }

        print("  [上传] 中...")
        resp = requests.post(f"{API_BASE}/upload", files=files, timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            print(f"  OK id={result['id']}  animated={result['is_animated']}")
        else:
            print(f"  FAIL HTTP {resp.status_code}: {resp.text[:300]}")

    print("\n完成")


if __name__ == "__main__":
    main()
