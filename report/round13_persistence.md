# 第十三轮：持久化闭环（第六轮 P0-3）验收

> 目标：把 `DATABASE_URL` 真正接到外部存储，并**证明**跨重部署数据不丢失。

## 一、外部存储（Render Postgres，免费层）
- Render 服务原为 **free** 计划，**不支持持久磁盘**；改用 **Render Postgres**（免费层，到期 2026-11-13）。
- 通过 Render API 创建实例（`POST /v1/postgres`，`version:"16"`），取 **内部连接串**，写入服务环境变量 `DATABASE_URL`（保留既有变量）。
- `requirements.txt` 增 `psycopg[binary]`；`src/store.py` 识别 `postgres://` → 走适配层（占位符/upsert 翻译 + `BIGSERIAL` DDL）。

## 二、线上证据
```
/api/persistence → {"db":{"dialect":"postgres","url_configured":true},
                    "external_configured":true,
                    "retention_hint":"已配置外部存储（DATABASE_URL）"}
```

## 三、跨重部署保留验收（`src/persistence_check.py`）
1. **记录**：写入标记数据（snapshot / device），保存计数基线：`versions=3, devices=1, audit=1`。
2. **重部署**：触发新部署，`uptime_s` 由 1619s → **465s（新实例）**。
3. **核对**：计数 **完全一致**（versions=3 / devices=1 / audit=1）→ **RESULT: PASS**。

> 结论：预测版本历史、设备凭证、审计、告警去重状态、验证归档等现 **跨重部署保留**，第六轮 P0-3 闭环。

## 四、运维
- 复现：`python src/persistence_check.py --url <URL> --admin-token <TOKEN> --phase record` → 重部署 → `--phase verify`。
- 到期提醒：免费 Postgres **2026-11-13 到期**，需升级或迁移托管库（接口不变，仅换 `DATABASE_URL`）。

## 五、仍未完成
- 现场传感器真值；设备签名+nonce；提前期更早年份与田间真值；物候超越基线。