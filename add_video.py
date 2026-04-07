#!/usr/bin/env python3
"""
柔術アーカイブ 動画追加スクリプト
使い方:
  python add_video.py "https://youtu.be/AAA:青帯" "https://youtu.be/BBB:白帯"

必要な環境変数:
  GEMINI_API_KEY  ... Google Gemini APIキー
"""

import argparse
import json
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

VALID_RULESETS = {"JBJJF", "ASJJF"}

IBJJF_RULES = """【IBJJFルール参考情報】

■ ポイントが入る技と点数
- テイクダウン（Takedown）: 2点
- スイープ（Sweep）: 2点
- ニーオンベリー（Knee on belly）: 2点
- パスガード（Guard pass）: 3点
- マウント（Mount）: 4点
- バックポジション（Back position、両フック有り）: 4点
- 試合エリア逃亡（2021新ルール）: 相手に2点＋ペナルティ

※ポイントは安定した状態を3秒以上保持した場合に認められる。

■ アドバンテージが入る状況
- スイープの試みがほぼ成功し相手がバランスを崩した場合
- テイクダウンの試みがほぼ成功した場合
- パスの試みで一時的に相手のガードを通過した場合（3秒未満）
- ニーオンベリーの試みで相手がほぼ制された場合
- サブミッションの試みで相手が脱出した場合（チョーク・関節技）
- バックテイクの試みがほぼ完成した場合

■ 反則・禁止技
【シリアスファウル（即失格）】
- スラム（slam）の使用
- 頭部・首への直接的な圧力（スパインロック単体は含む）
- ヒールフック（黒・茶帯のみ可、それ以下は禁止）
- ニーリーピング（knee reaping）: 一方の太ももを相手の脚の後ろに置き、ふくらはぎを相手の膝より上に乗せ、足を相手身体の垂直中心線を越えた位置に置き、外側から膝に圧力をかける技（2021規定）
  - パープル帯以下: 即停止・反則
  - ブラウン・ブラック帯: 試合継続・反則なし（ただし状況による）
- 50/50ガードから内側へのターン時、相手が地面に足をついている場合（捕まれた足とみなす）
- 脊椎への圧力を伴うチョーク（2021: 脊椎ロック付きチョークの図追加）
- 足首のツイスト系技（白・青・紫帯は禁止）
- フィンガーロック（指4本以下への関節技）
- 暴言・挑発行為

【マイナーファウル（ペナルティ）】
- スタンディングポジションでのスタンディング回避（引き込みによる試合停滞）
- 試合エリアからの逃亡（劣勢回避目的）: ペナルティ＋相手に2点（2021新ルール）
- ユニフォーム規定違反
- 時間稼ぎ行為

■ 判定基準（優先順位）
1. サブミッション勝ち
2. 失格（相手のシリアスファウル）
3. ポイント差（多い方が勝ち）
4. アドバンテージ差（多い方が勝ち）
5. ペナルティ差（少ない方が勝ち）
6. 審判の判定（referee decision）"""

ASJJF_DIFF = """
【ASJJFルール（IBJJFとの主な差分）】
※ASJJF（Sport Jiu-Jitsu International Federation / SJJIF）のルールはIBJJFと多くが共通するが、以下の点が異なる。

■ アドバンテージなし
- SJJIFはアドバンテージポイント制度を採用しない（第42条）。
- 判定基準はポイント差 → ペナルティ差の順。同点の場合はオーバータイム（サドンデス）へ。

■ オーバータイム（サドンデス方式）
- 同点の場合、時間無制限のサドンデスへ移行。
- 最初にポイントまたはサブミッションを取った選手が勝者。
- IBJJFのゴールデンスコア（同一ルールで延長）とは異なる。
- サドンデス中はストーリングルールがより厳格に適用される。

■ ヒールフック・ニーリーピングの扱い
- ヒールフック: 全カテゴリーで禁止（IBJJFは黒・茶帯で許可）。
- ニーリーピング: 全カテゴリーで禁止（IBJJFは茶・黒帯では試合継続）。

■ 場外の定義
- 身体の3分の2以上が境界線の外に出た場合に場外となり試合停止（IBJJFは境界線を越えた時点）。
- 「ストップ」後の動きにはポイントを付与しない。

■ ブラケット方式
- シングルエリミネーション（敗者復活なし）。IBJJFはダブルエリミネーション（敗者復活あり）。
- 3位は敗者復活決勝の勝者（bronze matchあり）。

■ 試合時間（主な差分）
- マスター36歳以上は全帯一律5分（IBJJFは帯ごとに時間が異なる）。"""


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
def normalize_youtube_url(url: str) -> str:
    vid = extract_video_id(url)
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return url


def analyze_with_gemini(youtube_url: str, ruleset: str = "JBJJF") -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("エラー: 環境変数 GEMINI_API_KEY が設定されていません。")

    client = genai.Client(api_key=api_key)

    rules = IBJJF_RULES
    if ruleset == "ASJJF":
        rules += "\n" + ASJJF_DIFF

    normalized_url = normalize_youtube_url(youtube_url)

    prompt = f"""{rules}

---

重要：
・選手の帯色は別途指定されるため、descriptionに帯色（白帯・青帯・紫帯・茶帯・黒帯）を記載しないこと
・道着の色（白い道着・青い道着）と帯色は別物です。混同しないこと
・選手を表現する際は「白道着の選手」「青道着の選手」と道着の色で表現すること

上記のルールを参考に、この柔術の試合動画を解析して以下のJSON形式のみで返答してください。余分なテキストは不要です。

{{
  "description": "試合の流れを3〜4文の日本語で説明。序盤・中盤・終盤の展開と勝敗を含める。",
  "tags": "最重要タグ3個をカンマ区切りで（例: スイープ,チョーク,ハーフガード）。「柔術」「ブラジリアン柔術」「BJJ」「白帯」「青帯」「紫帯」「茶帯」「黒帯」はタグに含めないこと。"
}}"""

    contents = [
        types.Part(
            file_data=types.FileData(
                file_uri=normalized_url,
                mime_type="video/*"
            )
        ),
        types.Part(text=prompt)
    ]

    print("  Gemini で解析中...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
        )

        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        data = json.loads(text)
        tags = [t.strip() for t in data["tags"].split(",") if t.strip()]
        return {
            "description": data["description"].strip(),
            "tags": tags,
        }
    except Exception as e:
        print(f"  警告: Gemini解析に失敗しました。手動入力が必要です。({e})")
        return {
            "description": "解析失敗のため手動で入力してください",
            "tags": [],
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
        description='柔術アーカイブに動画を追加します。"URL:帯色[:ルールセット]" の形式で複数指定可。'
    )
    parser.add_argument(
        "entries",
        nargs="+",
        metavar="URL:帯色[:ルールセット]",
        help='例: "https://youtu.be/AAA:青帯" または "https://youtu.be/AAA:青帯:ASJJF"',
    )
    parser.add_argument(
        "--ruleset",
        choices=list(VALID_RULESETS),
        default="JBJJF",
        help="使用するルールセット（デフォルト: JBJJF）。URL内に指定がある場合はそちらが優先される。",
    )
    args = parser.parse_args()

    triples = []
    for entry in args.entries:
        parts = entry.rsplit(":", 2)
        if len(parts) == 3 and parts[2] in VALID_RULESETS:
            url, belt, entry_ruleset = parts
        else:
            url, _, belt = entry.rpartition(":")
            if not url:
                sys.exit(f"エラー: 「URL:帯色」の形式で指定してください → {entry}")
            entry_ruleset = args.ruleset
        if not extract_video_id(url):
            sys.exit(f"エラー: 有効な YouTube URL を指定してください → {url}")
        if belt not in BELT_MAP:
            sys.exit(f"エラー: 帯色が不正です（{'/'.join(BELT_MAP.keys())}）→ {belt}")
        triples.append((url, belt, entry_ruleset))

    total = len(triples)
    today = date.today().strftime("%Y/%m/%d")
    for i, (url, belt, ruleset) in enumerate(triples):
        print(f"[{i + 1}/{total}] 処理中: {url}")
        print(f"動画を解析中: {url} [{ruleset}]")
        gemini_result = analyze_with_gemini(url, ruleset)
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
