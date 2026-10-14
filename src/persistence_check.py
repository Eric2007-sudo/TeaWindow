"""
持久化保留验收：跨重部署验证数据不丢失。
用法：
  # 阶段一：记录基线并写入标记数据（需管理令牌）
  python src\\persistence_check.py --url <URL> --admin-token <TOKEN> --phase record
  # 重新部署后
  python src\\persistence_check.py --phase verify
退出码：0=通过；1=失败。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".persistence_baseline.json")


def _req(method, url, body=None, headers=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for _ in range(tries):
        r = urllib.request.Request(url, data=data, method=method,
                                   headers=headers or {"Content-Type": "application/json"})
        try:
            x = urllib.request.urlopen(r, timeout=60)
            return x.status, json.loads(x.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")[:200]
        except Exception as e:  # noqa: BLE001
            last = e
            import time
            time.sleep(5)
    return 0, str(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://teawindow.onrender.com")
    ap.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN", ""))
    ap.add_argument("--phase", choices=["record", "verify"], required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    if a.phase == "record":
        if not a.admin_token:
            print("需要 --admin-token 或 ADMIN_TOKEN"); sys.exit(2)
        h = {"X-Admin-Token": a.admin_token}
        _req("POST", base + "/api/data/snapshot", headers=h)
        _req("POST", base + "/api/device/register?device_id=ACCEPT-TEST", headers=h)
        st, d = _req("POST", base + "/api/outcome", {"date": "2026-10-18", "kind": "巡查无灾", "plot": "验收"},
                     headers={"X-Admin-Token": a.admin_token})
        p = _req("GET", base + "/api/persistence", headers=h)[1]
        json.dump(p.get("counts", {}), open(BASE_FILE, "w", encoding="utf-8"))
        print("baseline counts:", p.get("counts"), "db:", p.get("db"))
        print("-> 保存到", BASE_FILE, "；请重新部署后执行 --phase verify")
        return
    # verify
    if not os.path.exists(BASE_FILE):
        print("缺少基线文件，请先 --phase record"); sys.exit(2)
    want = json.load(open(BASE_FILE, encoding="utf-8"))
    p = _req("GET", base + "/api/persistence")[1]
    got = p.get("counts", {})
    print("baseline:", want)
    print("current :", got)
    ok = True
    for k in ("versions", "outcomes", "devices"):
        if k in want and got.get(k, 0) < want.get(k, 0):
            ok = False
            print(f"  ✗ 保留失败：{k} {want.get(k)} -> {got.get(k)}")
    print("external_configured:", p.get("external_configured"))
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()