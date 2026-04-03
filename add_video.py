#!/usr/bin/env python3
"""
柔術アーカイブ 動画追加スクリプト
使い方:
  python add_video.py "https://youtu.be/AAA:青帯" "https://youtu.be/BBB:白帯"

必要な環境変数:
  GEMINI_API_KEY  ... Google Gemini APIキー
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date

from google import genai
from google.genai import types

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
# yt-dlp でYouTubeメタデータ取得
# ----------------------------------------------------------------
def get_youtube_metadata(youtube_url: str) -> dict:
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", youtube_url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    import json
    data = json.loads(result.stdout)
    return {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "uploader": data.get("uploader", ""),
        "tags": data.get("tags", []),
    }


# ----------------------------------------------------------------
# Gemini で解析
# ----------------------------------------------------------------
def analyze_with_gemini(youtube_url: str) -> dict:
    import json

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("エラー: 環境変数 GEMINI_API_KEY が設定されていません。")

    print("  YouTube メタデータを取得中...")
    meta = get_youtube_metadata(youtube_url)
    context_parts = []
    if meta.get("title"):
        context_parts.append(f"タイトル: {meta['title']}")
    if meta.get("uploader"):
        context_parts.append(f"投稿者: {meta['uploader']}")
    if meta.get("description"):
        context_parts.append(f"概要欄:\n{meta['description'][:800]}")
    if meta.get("tags"):
        context_parts.append(f"タグ: {', '.join(meta['tags'][:10])}")
    context = "\n".join(context_parts) if context_parts else "（メタデータなし）"

    client = genai.Client(api_key=api_key)

    prompt = f"""以下は柔術の試合動画のYouTubeメタデータです。

{context}

この情報をもとに、以下のJSON形式のみで返答してください。余分なテキストは不要です。

{{
  "description": "試合の流れを3〜4文の日本語で説明。序盤・中盤・終盤の展開と勝敗を含める。メタデータが少ない場合は内容から推測して補完する。",
  "tags": "最重要タグ3個をカンマ区切りで（例: 青帯,スイープ,チョーク）。「柔術」「ブラジリアン柔術」「BJJ」はタグに含めないこと。"
}}"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

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
    parser = argparse.ArgumentParser(
        description='柔術アーカイブに動画を追加します。"URL:帯色" の形式で複数指定可。'
    )
    parser.add_argument(
        "entries",
        nargs="+",
        metavar="URL:帯色",
        help='例: "https://youtu.be/AAA:青帯"',
    )
    args = parser.parse_args()

    pairs = []
    for entry in args.entries:
        if ":" not in entry:
            sys.exit(f"エラー: 「URL:帯色」の形式で指定してください → {entry}")
        url, belt = entry.rsplit(":", 1)
        if not extract_video_id(url):
            sys.exit(f"エラー: 有効な YouTube URL を指定してください → {url}")
        if belt not in BELT_MAP:
            sys.exit(f"エラー: 帯色が不正です（{'/'.join(BELT_MAP.keys())}）→ {belt}")
        pairs.append((url, belt))

    today = date.today().strftime("%Y/%m/%d")
    for url, belt in pairs:
        print(f"動画を解析中: {url}")
        gemini_result = analyze_with_gemini(url)
        print(f"  description: {gemini_result['description'][:60]}...")
        print(f"  tags: {gemini_result['tags']}")

        video_entry = {
            "youtube": url,
            "belt": BELT_MAP[belt],
            "date": today,
            "description": gemini_result["description"],
            "tags": gemini_result["tags"],
        }
        add_to_html(video_entry)

    git_commit_and_push()
    print("\n完了！")


if __name__ == "__main__":
    main()
