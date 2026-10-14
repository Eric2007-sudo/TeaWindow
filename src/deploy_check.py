"""
部署一致性自检：校验 Git SHA / OpenAPI 路由数 / 核心接口连续可用。
用法：
  python src\\deploy_check.py --url https://teawindow.onrender.com [--expect-sha ab12cd34] [--min-routes 20] [--tries 8]
退出码：0=全部通过；1=存在失败。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

CRITICAL = ["/api/health", "/api/summary", "/api/days?scope=forecast", "/api/ask?q=%E4%BB%8A%E5%A4%A9%E6%9C%89%E9%A3%8E%E9%99%A9%E5%90%97",
            "/api/realtime", "/api/updates", "/api/data/versions", "/api/forecast/verify", "/api/ready", "/api/alerts",
            "/api/persistence", "/api/forecast/compare"]


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "TeaWindow-deploy-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://teawindow.onrender.com")
    ap.add_argument("--expect-sha", default="")
    ap.add_argument("--min-routes", type=int, default=20)
    ap.add_argument("--tries", type=int, default=8)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    checks = []

    def chk(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, repr(e)
        checks.append((name, ok, detail))

    # 等待唤醒
    awake = False
    for _ in range(a.tries):
        try:
            if _get(base + "/api/health", 20)[0] == 200:
                awake = True
                break
        except Exception:  # noqa: BLE001
            time.sleep(8)
    checks.append(("awake", awake, "health reachable" if awake else "unreachable"))

    chk("health", lambda: (json.loads(_get(base + "/api/health")[1]).get("status") == "ok", ""))

    def ready():
        j = json.loads(_get(base + "/api/ready")[1])
        sha_ok = (not a.expect_sha) or str(j.get("build", "")).startswith(a.expect_sha[:12])
        good = bool(j.get("ready")) and not j.get("missing_critical") and sha_ok
        return good, f"ready={j.get('ready')} build={j.get('build')} missing={j.get('missing_critical')} age={j.get('age_minutes')}"
    chk("ready", ready)

    def routes():
        spec = json.loads(_get(base + "/openapi.json")[1])
        n = len(spec.get("paths", {}))
        return n >= a.min_routes, f"paths={n} (>= {a.min_routes})"
    chk("openapi", routes)

    for p in CRITICAL:
        chk(p, lambda p=p: (0 < _get(base + p)[0] < 400, ""))

    def alerts():
        j = json.loads(_get(base + "/api/alerts")[1])
        return True, f"{j.get('count')} alerts"
    chk("alerts", alerts)

    def persistence():
        j = json.loads(_get(base + "/api/persistence")[1])
        ext = j.get("external_configured")
        return True, (f"db={j.get('db', {}).get('dialect')} external={ext} counts={j.get('counts')}")
    chk("persistence", persistence)

    width = max(len(c[0]) for c in checks)
    passed = 0
    for name, ok, detail in checks:
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    print(f"\n{passed}/{len(checks)} 通过")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()