"""
自动生成演示视频（无需真人/配音）：用 Chrome 无头逐帧截取 web/demo.html，再合成 MP4。
输出 submit/演示视频_自动生成.mp4
依赖：Chrome + imageio/imageio-ffmpeg。
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import imageio.v2 as imageio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
OUT = os.path.join(ROOT, "submit", "演示视频_自动播放.mp4")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
N_SLIDES = 21
SECS_PER_SLIDE = 8
FPS = 1


def main():
    tmp = tempfile.mkdtemp(prefix="tw_vid_")
    try:
        for name in ("demo.html", "demo.js", "data.js", "chart.umd.min.js"):
            p = os.path.join(WEB, name)
            if os.path.exists(p):
                shutil.copy(p, tmp)
        shutil.copytree(os.path.join(WEB, "demo_assets"), os.path.join(tmp, "demo_assets"))
        frames = []
        for n in range(N_SLIDES):
            png = os.path.join(tmp, f"frame_{n}.png")
            url = f"file:///{tmp.replace(os.sep, '/')}/demo.html?slide={n}&clean=1"
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--window-size=1280,720", "--virtual-time-budget=1800",
                            f"--screenshot={png}", url], capture_output=True)
            if not os.path.exists(png):
                print("截图失败 slide", n)
                continue
            img = imageio.imread(png)[:, :, :3]
            for _ in range(SECS_PER_SLIDE):
                frames.append(img)
            print(f"slide {n} ok")
        if not frames:
            print("无帧，退出"); return
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        writer = imageio.get_writer(OUT, fps=FPS, codec="libx264", quality=8,
                                    macro_block_size=None, ffmpeg_log_level="error")
        for f in frames:
            writer.append_data(f)
        writer.close()
        print("视频 ->", OUT, round(os.path.getsize(OUT) / 1e6, 2), "MB", f"({len(frames)//FPS}s)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
