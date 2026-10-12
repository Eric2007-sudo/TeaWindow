"""
生成指向线上地址的二维码 PNG。
用法：python src\\make_qr.py <url> <out.png> [caption]
"""
import sys

import segno


def main():
    url = sys.argv[1]
    out = sys.argv[2]
    segno.make(url, error="m").save(out, scale=8, border=2, dark="#0f1720", light="#ffffff")
    print(f"QR -> {out}\n  {url}")


if __name__ == "__main__":
    main()
