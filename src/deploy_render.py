"""
Render 部署脚本（REST API）。
从 .env 读取 RENDER_API_KEY（不落盘、不打印）。
用法：
  python src\\deploy_render.py owners     # 查看 ownerId（验证 Key）
  python src\\deploy_render.py list       # 列出服务
  python src\\deploy_render.py up         # 创建/复用服务并触发部署
  python src\\deploy_render.py status     # 查看最近部署状态
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
import llm_advice  # noqa: E402  (触发 .env 加载)

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY", "")
REPO = "https://github.com/Eric2007-sudo/TeaWindow"
NAME = "teawindow"
BRANCH = "main"
REGION = "singapore"


def _req(method, path, body=None):
    if not KEY:
        raise SystemExit("RENDER_API_KEY 未配置（请在 .env 填写）")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"null")
    except urllib.error.HTTPError as e:
        print(f"[HTTP {e.code}] {e.read().decode('utf-8', 'ignore')[:500]}")
        raise


def owners():
    o = _req("GET", "/owners?limit=20")
    for item in o:
        print(item["owner"]["id"], item["owner"].get("name"), item["owner"].get("email"))
    return o[0]["owner"]["id"] if o else None


def list_services():
    return _req("GET", "/services?limit=100")


def find_service():
    for s in list_services():
        svc = s.get("service", {})
        if svc.get("name") == NAME:
            return svc
    return None


def create_service(owner_id):
    body = {
        "type": "web_service",
        "name": NAME,
        "ownerId": owner_id,
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "python",
            "plan": "free",
            "region": REGION,
            "healthCheckPath": "/api/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "uvicorn src.serve:app --host 0.0.0.0 --port $PORT",
            },
        },
    }
    return _req("POST", "/services", body)


def deploys(service_id):
    return _req("GET", f"/services/{service_id}/deploys?limit=5")


def cmd_up():
    owner = owners()
    svc = find_service()
    if svc is None:
        print("创建服务 ...")
        r = create_service(owner)
        svc = r.get("service", r)
    sid = svc["id"]
    print("service id:", sid)
    print("url:", svc.get("serviceDetails", {}).get("url") or svc.get("serviceDetails", {}).get("url"))
    # 触发一次部署
    try:
        _req("POST", f"/services/{sid}/deploys", {"clearCache": "do_not_clear"})
    except Exception as e:  # noqa: BLE001
        print("触发部署(可能已在部署):", e)
    for _ in range(30):
        ds = deploys(sid)
        if ds:
            d = ds[0]["deploy"]
            print(f"  部署 {d['id'][:12]} 状态={d['status']}")
            if d["status"] in ("live", "build_failed", "update_failed", "canceled", "deactivated"):
                break
        time.sleep(20)
    return sid


def set_env(vars_map):
    svc = find_service()
    if not svc:
        raise SystemExit("服务不存在")
    body = [{"key": k, "value": v} for k, v in vars_map.items()]
    return _req("PUT", f"/services/{svc['id']}/env-vars", body)


def cmd_setenv():
    ds = os.environ.get("DEEPSEEK_API_KEY", "")
    if not ds:
        print("DEEPSEEK_API_KEY 未在 .env 中配置，跳过")
        return
    r = set_env({"DEEPSEEK_API_KEY": ds})
    print(f"已设置环境变量（{len(r)} 项），将自动触发重新部署")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "owners"
    if cmd == "owners":
        owners()
    elif cmd == "list":
        for s in list_services():
            svc = s["service"]
            print(svc["id"], svc["name"], svc.get("type"))
    elif cmd == "up":
        cmd_up()
    elif cmd == "setenv":
        cmd_setenv()
    elif cmd == "status":
        svc = find_service()
        if not svc:
            print("未找到服务")
        else:
            for d in deploys(svc["id"]):
                dd = d["deploy"]
                print(dd["id"][:12], dd["status"], dd.get("finishedAt"))
    else:
        print("unknown command:", cmd)
