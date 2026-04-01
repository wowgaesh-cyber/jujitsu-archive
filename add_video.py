#!/usr/bin/env python3
"""
柔術アーカイブ 動画追加スクリプト
使い方:
  python add_video.py <YouTube URL> --belt 青帯

必要な環境変数:
  GEMINI_API_KEY  ... Google Gemini APIキー
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date

import google.generativeai as genai

# ----------------------------------------------------------------
# 定数
# ----------------------------------------------------------------
HTML_FILE = os.path.join(os.path.dirname(__file__), "jujitsu_archive.html")

BELT_MAP = {
    "白帯": "white",
    "青帯": "blue",
    "紫帯": "purple",
    "茶帯": "brown",
    "黒帯": "black",
}


# ----------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------
def extract_video_id(url: str) -> str | None:
    m = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{11})",
        url,
    )
    return m.group(1) if m else None


def get_next_id(html: str) -> int:
    ids = re.findall(r"\bid:\s*(\d+)", html)
    return max((int(i) for i in ids), default=0) + 1


# ----------------------------------------------------------------
# Gemini で解析
# ----------------------------------------------------------------
def analyze_with_gemini(youtube_url: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("エラー: 環境変数 GEMINI_API_KEY が設定されていません。")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")

    prompt = """この柔術の試合動画を日本語で解析してください。
以下のJSON形式のみで返答してください。余分なテキストは不要です。

{
  "description": "試合の流れを3〜4文の日本語で説明。序盤・中盤・終盤の展開と勝敗を含める。",
  "tags": "最重要タグ3個をカンマ区切りで（例: 青帯,スイープ,チョーク）"
}"""

    response = model.generate_content(
        [
            prompt,
            genai.types.Part(
                file_data=genai.types.FileData(file_uri=youtube_url)
            ),
        ]
    )

    text = response.text.strip()
    # コードブロックを除去
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    import json
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"エラー: Geminiの応答をJSONとして解析できませんでした。\n{text}\n{e}")

    tags = [t.strip() for t in data["tags"].split(",") if t.strip()]
    return {
        "description": data["description"].strip(),
        "tags": tags,
    }


# ----------------------------------------------------------------
# HTML の VIDEOS 配列に追記
# ----------------------------------------------------------------
def add_to_html(video_entry: dict) -> None:
    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()

    new_id = get_next_id(html)
    vid_id = extract_video_id(video_entry["youtube"])
    thumbnail = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg" if vid_id else ""

    tags_js = ", ".join(f'"{t}"' for t in video_entry["tags"])

    new_entry = f"""  {{
    id: {new_id},
    description: "{video_entry['description']}",
    belt: "{video_entry['belt']}",
    tags: [{tags_js}],
    youtube: "{video_entry['youtube']}",
    thumbnail: "{thumbnail}",
    date: "{video_entry['date']}"
  }}"""

    # 最後のエントリの `}` の直前に挿入（`];\n` の直前に追加）
    # 既存エントリの末尾 `}` にカンマを付けて新エントリを追加
    pattern = r"(const VIDEOS = \[)(.*?)(\];)"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        sys.exit("エラー: VIDEOS 配列が見つかりませんでした。")

    array_body = match.group(2).rstrip()
    if array_body.strip():
        # 既存エントリがある場合、末尾にカンマを付ける
        array_body = re.sub(r"\}\s*$", "},\n", array_body)
        new_body = array_body + new_entry + "\n"
    else:
        new_body = "\n" + new_entry + "\n"

    new_html = html[:match.start(2)] + new_body + html[match.end(2):]

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"✓ VIDEOS配列に追加しました (id: {new_id})")


# ----------------------------------------------------------------
# Git 操作
# ----------------------------------------------------------------
def git_commit_and_push() -> None:
    cmds = [
        ["git", "add", "."],
        ["git", "commit", "-m", "動画追加"],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=os.path.dirname(__file__))
        if result.returncode != 0:
            sys.exit(f"エラー: {' '.join(cmd)} が失敗しました。")
    print("✓ git commit & push 完了")


# ----------------------------------------------------------------
# メイン
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="柔術アーカイブに動画を追加します")
    parser.add_argument("url", help="YouTube の URL")
    parser.add_argument(
        "--belt",
        required=True,
        choices=list(BELT_MAP.keys()),
        help="帯色（白帯/青帯/紫帯/茶帯/黒帯）",
    )
    args = parser.parse_args()

    if not extract_video_id(args.url):
        sys.exit("エラー: 有効な YouTube URL を指定してください。")

    print(f"🎬 動画を解析中: {args.url}")
    gemini_result = analyze_with_gemini(args.url)
    print(f"✓ Gemini 解析完了")
    print(f"  description: {gemini_result['description'][:60]}...")
    print(f"  tags: {gemini_result['tags']}")

    video_entry = {
        "youtube": args.url,
        "belt": BELT_MAP[args.belt],
        "date": date.today().strftime("%Y/%m/%d"),
        "description": gemini_result["description"],
        "tags": gemini_result["tags"],
    }

    add_to_html(video_entry)
    git_commit_and_push()

    print("\n✅ 完了！")


if __name__ == "__main__":
    main()
