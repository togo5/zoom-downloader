#!/usr/bin/env python3
"""
Zoom録画ダウンローダー
Playwrightを使って共有URLから動画をダウンロード
"""

import asyncio
import csv
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def download_zoom_recording(
    base_filename: str,
    share_url: str,
    passcode: str,
    output_dir: str = "./downloads",
) -> list[str]:
    """
    Zoom録画をダウンロード

    Args:
        base_filename: 出力ファイル名のベース (例: "meeting_2025-10-22")
        share_url: Zoom共有URL
        passcode: パスコード
        output_dir: 出力ディレクトリ

    Returns:
        ダウンロードしたファイルパスのリスト
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 動画URLとCookieを格納するリスト
    video_requests: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 720},
            locale="ja-JP",
        )
        page = await context.new_page()

        # ネットワークリクエストを監視してssrweb.zoom.usへのリクエストをキャプチャ
        async def handle_request(request):
            if "ssrweb.zoom.us" in request.url and ".mp4" in request.url:
                headers = request.headers
                video_requests.append(
                    {
                        "url": request.url,
                        "headers": headers,
                    }
                )

        page.on("request", handle_request)

        # navigator.webdriverをfalseにしてBot検出を回避
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
        """)

        print(f"\n{'=' * 60}")
        print(f"Processing: {base_filename}")
        print(f"URL: {share_url[:50]}...")
        print(f"{'=' * 60}")

        # ページ読み込み
        print("[1/4] Loading page...")
        await page.goto(share_url, wait_until="networkidle")

        # パスコード入力
        print("[2/4] Entering passcode...")
        try:
            await page.wait_for_selector('input[type="password"]', timeout=10000)
            await page.fill('input[type="password"]', passcode)

            # ボタンをクリック（英語/日本語両対応）
            submit_btn = page.locator(
                'button[type="submit"], button:has-text("View Recording"), button:has-text("録画を視聴")'
            )
            await submit_btn.first.click()
        except Exception as e:
            print(f"  [!] Passcode might not be required: {e}")

        # ネットワークリクエストがキャプチャされるまで待機（最大30秒）
        print("[3/4] Waiting for video requests...")
        for _ in range(30):
            if video_requests:
                break
            await asyncio.sleep(1)

        print("[4/4] Extracting sharing timeline...")

        # 画面共有のタイミング情報を取得（SPAN要素のaria-labelから）
        sharing_timeline = await page.evaluate(r"""() => {
            const markers = document.querySelectorAll('span.vjs-share-marker-button');
            const timeline = [];
            markers.forEach(marker => {
                const label = marker.getAttribute('aria-label');
                if (label && (label.includes('Sharing Started') || label.includes('Sharing Stopped'))) {
                    // "Sharing Started,0 hours 4 minutes 13 seconds" のような形式をパース
                    const match = label.match(/(Sharing (?:Started|Stopped)),(\d+) hours (\d+) minutes (\d+) seconds/);
                    if (match) {
                        const action = match[1];
                        const hours = parseInt(match[2]);
                        const minutes = parseInt(match[3]);
                        const seconds = parseInt(match[4]);
                        const totalSeconds = hours * 3600 + minutes * 60 + seconds;
                        const h = String(hours).padStart(2,'0');
                        const m = String(minutes).padStart(2,'0');
                        const s = String(seconds).padStart(2,'0');
                        timeline.push({
                            action: action,
                            time: `${h}:${m}:${s}`,
                            seconds: totalSeconds
                        });
                    }
                }
            });
            return timeline;
        }""")

        # タイムライン情報を保存
        if sharing_timeline:
            timeline_file = f"{output_dir}/{base_filename}_timeline.json"
            with open(timeline_file, "w", encoding="utf-8") as f:
                json.dump(sharing_timeline, f, indent=2, ensure_ascii=False)
            print(f"  [i] Saved sharing timeline: {timeline_file} ({len(sharing_timeline)} events)")
        else:
            print("  [i] No sharing timeline found")

        # 重複を除去したリクエスト情報を取得
        unique_requests = {}
        for req in video_requests:
            url = req["url"]
            # URLのベース部分（クエリパラメータ前）で重複判定
            if "_avo_" in url or "_as_" in url:
                unique_requests[url] = req

        print(f"  Found {len(unique_requests)} video request(s)")

        if not unique_requests:
            print("  [!] No video requests found!")
            await browser.close()
            return []

        # Cookieを取得
        cookies = await context.cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        await browser.close()

    # curlを使ってダウンロード（キャプチャしたヘッダーとCookieを使用）
    import subprocess

    downloaded_files = []
    for url, req in unique_requests.items():
        # 解像度情報を抽出
        if "_avo_" in url:
            match = re.search(r"_avo_(\d+x\d+)\.mp4", url)
            resolution = match.group(1) if match else "unknown"
            suffix = f"_face_{resolution}"
        elif "_as_" in url:
            match = re.search(r"_as_(\d+x\d+)\.mp4", url)
            resolution = match.group(1) if match else "unknown"
            suffix = f"_screen_{resolution}"
        else:
            suffix = "_unknown"

        filename = f"{output_dir}/{base_filename}{suffix}.mp4"
        print(f"  Downloading: {filename}")

        try:
            headers = req["headers"]
            curl_cmd = [
                "curl",
                "-L",
                "-o",
                filename,
                "-H",
                f"Accept: {headers.get('accept', '*/*')}",
                "-H",
                f"Accept-Language: {headers.get('accept-language', 'ja-JP')}",
                "-H",
                f"Referer: {headers.get('referer', 'https://us06web.zoom.us/')}",
                "-H",
                f"User-Agent: {headers.get('user-agent', '')}",
                "-b",
                cookie_str,
                url,
            ]
            result = subprocess.run(curl_cmd, capture_output=True)

            if result.returncode == 0:
                # ファイルサイズを確認
                file_path = Path(filename)
                if file_path.exists():
                    file_size = file_path.stat().st_size / (1024 * 1024)
                    if file_size > 0.1:
                        downloaded_files.append(filename)
                        print(f"  [✓] Done: {filename} ({file_size:.1f} MB)")
                    else:
                        print(f"  [✗] File too small: {filename} ({file_size:.3f} MB)")
                else:
                    print(f"  [✗] File not created: {filename}")
            else:
                print(f"  [✗] curl failed: {result.stderr.decode()}")
        except Exception as e:
            print(f"  [✗] Failed: {filename} - {e}")

    return downloaded_files


async def process_batch(csv_path: str, output_dir: str = "./downloads"):
    """
    CSVファイルから複数の録画をバッチ処理

    CSVフォーマット:
    base_filename,url,passcode
    """
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        recordings = list(reader)

    print(f"Loaded {len(recordings)} recordings from {csv_path}")

    all_files = []
    for i, rec in enumerate(recordings, 1):
        print(f"\n[{i}/{len(recordings)}]")
        files = await download_zoom_recording(
            base_filename=rec["base_filename"], share_url=rec["url"], passcode=rec["passcode"], output_dir=output_dir
        )
        all_files.extend(files)

        # レート制限対策
        if i < len(recordings):
            print("Waiting 3 seconds before next download...")
            await asyncio.sleep(3)

    print(f"\n{'=' * 60}")
    print(f"Complete! Downloaded {len(all_files)} files")
    print(f"{'=' * 60}")
    return all_files


async def main():
    if len(sys.argv) < 2:
        # 単体テスト用
        print("Usage:")
        print("  Single: python zoom_downloader.py <base_filename> <url> <passcode>")
        print("  Batch:  python zoom_downloader.py --csv <csv_file>")
        print("")
        print("Example:")
        print('  python zoom_downloader.py meeting_01 "https://zoom.us/rec/share/xxx" "password123"')
        return

    if sys.argv[1] == "--csv":
        csv_path = sys.argv[2]
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "./downloads"
        await process_batch(csv_path, output_dir)
    else:
        base_filename = sys.argv[1]
        url = sys.argv[2]
        passcode = sys.argv[3]
        output_dir = sys.argv[4] if len(sys.argv) > 4 else "./downloads"
        await download_zoom_recording(base_filename, url, passcode, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
