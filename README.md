# 嵌入式校招看板

> 把你的飞书投递表实时变成本地进度驾驶舱，看数据不再靠翻表格。
>
> 飞书多维表格 × FastAPI × 原生前端，零外部前端框架。

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Status](https://img.shields.io/badge/status-active-brightgreen)

---

## 能做什么

打开 `http://localhost:8765` 就能直接看：

- 监控公司数量、已投递数量、面试中数量
- 投递漏斗：已投 → 机考 → 面试 → Offer
- 截止时间轴：哪些快到期的要注意
- 方向分布、公司类型分布
- 你的投递记录列表
- 暗色 / 亮色主题

所有投递数据都由你在飞书多维表格里手动录入和维护，看板只负责读出来展示。

---

## 六步跑起来

### 1. 复制飞书多维表格模板

> 飞书多维表格模板：[点此打开](https://j0pbq4vb3lh.feishu.cn/wiki/Niv3we4Ldiw56LkEWV2cLuCynvc)
>
> 申请阅读权限后在右上角「...」→ **复制此表格**到你的飞书空间。

### 2. 打开你的表格填公司

在飞书里打开复制好的表格，手动填入你想关注的公司。至少填：

- 公司名称
- 投递链接

推荐也把嵌入式方向、工作地点、意愿填上。

### 3. 创建飞书自建应用

打开 [飞书开放平台](https://open.feishu.cn/app) → 创建企业自建应用：

- 开通 `bitable:app` 权限
- 复制 App ID 和 App Secret
- 创建版本并发布
- 从表格链接里记下 App Token、主表 ID

### 4. 克隆并安装

```bash
git clone https://github.com/kaoya-123/embeded_job_rader.git
cd embeded_job_rader
pip install -r requirements.txt
```

### 5. 配置 .env

```bash
cp .env.example .env
```

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_APP_TOKEN=你的多维表格 token
MAIN_TABLE_ID=你的主表 table_id
```

也可以启动后在浏览器配置页直接填。

### 6. 启动看板

```bash
dev -m uvicorn app.main:app --port 8765
```

打开浏览器访问：

```text
http://localhost:8765
```

---

## 原理一句话

```text
你在飞书表格里维护投递数据
      ↓ Feishu OpenAPI
本地 FastAPI 读取并聚合
      ↓
浏览器看板展示：KPI / 漏斗 / 截止时间轴 / 方向分布 / 你的投递列表
```

不写飞书，不等同步，不自动改你手动录入的任何内容。

---

## 安全说明

- 真实密钥只保存在本地 `.env` 或浏览器配置页中
- `.env` 已被 `.gitignore` 忽略，不要提交真实凭证

---

## 技术栈

| 组件 | 技术 |
|---|---|
| 后端框架 | FastAPI |
| 服务运行 | Uvicorn |
| 数据存储 | 飞书多维表格 Bitable |
| 前端 | 原生 HTML / CSS / JS |
| HTTP 客户端 | requests |

---

## 贡献 & 许可

MIT License — 可自由使用、修改和分发。
