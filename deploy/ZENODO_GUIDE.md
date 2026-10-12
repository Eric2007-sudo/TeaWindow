# Zenodo DOI 归档指南（需你的账号，2 分钟）

> 目的：把 `v1.3` 发布归档，获得**可引用的 DOI**（提升"开放性/学术规范"）。
> 需要你的 Zenodo 账号（免费，可用 GitHub 登录）。**我无法代做（需 OAuth 授权）。**

## 方式 A：GitHub ↔ Zenodo 自动归档（推荐）
1. 打开 https://zenodo.org/ → **Sign up / Log in** → 选择 **Log in with GitHub**。
2. 右上头像 → **Settings** → **GitHub** → 找到 `Eric2007-sudo/TeaWindow`，把开关**打开**。
3. 回 GitHub：**Releases** → 找到 `v1.3` → 点 **Edit** → **Publish**（或删掉重建，触发 Zenodo 抓取）。
4. 回 Zenodo → **Upload**（上方菜单）会看到新条目 → 点进去即得 **DOI**（形如 `10.5281/zenodo.xxxxxxx`）。
5. 把 DOI 填进 `CITATION.cff` 的 `doi:` 字段（见下方）与 README。

## 方式 B：Zenodo API（若你愿意提供 Token）
1. Zenodo → **Settings → Applications → Personal access tokens → New token**（勾 `deposit:write`、`deposit:actions`）。
2. 把 Token 放进 `TeaWindow\.env`：`ZENODO_TOKEN=xxxx`（已被 gitignore）。
3. 我用 REST API 创建 deposition、上传 `dist/TeaWindow_v1.3.zip`、发布并取回 DOI。

## 归档后要更新的位置
- `CITATION.cff`：`doi: "10.5281/zenodo.xxxxxxx"`（本文件末尾已留位）
- `README.md`：在"自播放演示 / 打包 / 许可"处加一行 DOI 徽章/链接
- `submit/`：项目说明与英文版可加 DOI

## 备注
- 归档的是**Release 附件**（zip），含代码/数据/文档/报告；代码许可 MIT，数据/文档 CC BY 4.0。
- 若只想先占位，可先用 `CITATION.cff` 的 `version`+`date-released`（已填），DOI 后补。
