# 嵌入式校招看板

> 面向嵌入式校招投递的本地飞书进度驾驶舱：飞书多维表格 × FastAPI × 原生前端 × 安全字段补齐。

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Status](https://img.shields.io/badge/status-active-brightgreen)

---

## 这是什么？

**一句话：把你的飞书主投递表变成本地看板，集中展示投递进度、截止风险、公司画像，并支持“先预览、再确认、只补空字段”的主表补齐。**

它适合嵌入式校招准备场景：你在飞书多维表格里维护公司、岗位、投递状态；本地服务读取飞书数据后，提供更适合行动决策的看板视图。

```text
飞书主投递表 / 机会发现池
        ↓ Feishu OpenAPI
本地 FastAPI 服务 :8765
        ↓
浏览器看板：KPI / 漏斗 / 截止时间轴 / 机会池 / 公司画像补齐
```

---

## 当前核心功能

### 1. 本地看板

打开 `http://localhost:8765` 后可以看到：

- 顶部 KPI：主表公司数、A 档机会、明确截止、已投递、面试中等
- 投递漏斗：机会 → 已投递 → 机考/测评 → 面试 → Offer
- 截止时间轴：按截止日期聚合近期风险
- 机会发现池：展示去重后的岗位机会
- 方向 / 公司类型分布：观察投递组合是否均衡
- 主投递表记录：按状态、意愿、时间查看
- 配置页：在浏览器内填写或更新飞书连接配置

### 2. 公司画像补齐

补齐入口在看板内，流程是：

1. 从飞书主表读取公司列表和现有字段
2. 更新本地画像库 `data/company_profiles.json`
3. 根据画像库生成补齐预览
4. 用户在页面确认
5. 后端再次检查字段仍为空
6. 只把空字段写回飞书主表

默认补齐字段包括：

- `嵌入式方向`
- `工作地点`
- `公司/行业类型`
- `细分类型`
- `公司规模`
- `公司简介`

安全原则：

- 默认只预览，不写入
- 必须 `confirm=true` 才写入
- 只补白名单字段
- 只补主表空字段
- apply 前会再次读取飞书，避免覆盖用户刚刚手动填写的内容
- 多选字段只使用飞书已有选项，不随意新增选项

### 3. 产品介绍页

`intro.html` 是单文件产品介绍页：

- 纯 HTML / CSS / 原生 JS
- Apple × Vercel × Linear 风格
- deep-space 暗色底、玻璃拟态、Mesh 背景
- 暗 / 亮主题切换，状态保存在 `localStorage`
- 全屏 Deck 幻灯片
- 支持 `←` / `→` / `Home` / `End` / `Space` 键盘翻页

可以直接用浏览器打开 `intro.html`。

---

## 画像数据到底怎么来的？是否用了 AI 或网络搜索？

**当前代码没有接入 AI，也没有用网络搜索自动生成公司画像。**

目前画像来源是确定性的本地数据合并：

1. `data/company_profile_seeds.json`
   - 手工整理 / 历史沉淀的公司画像种子数据
2. `data/seed_companies.json`
   - 项目内置的种子公司信息
3. 飞书主投递表已有字段
   - 如果主表里已经有公司类型、方向、城市、简介等，会被抽取进本地画像库
4. `data/company_profiles.json`
   - 最终合并后的本地画像库

对应代码：

- `src/main_table_completion.py`
  - `update_company_profiles_from_main()`：从主表和种子文件合并画像
  - `build_completion_preview()`：根据画像库生成补齐预览
  - `build_apply_updates()`：确认写入前再次检查空字段
- `app/routers/completion.py`
  - `/api/completion/profiles/update`
  - `/api/completion/preview`
  - `/api/completion/apply`

代码里有占位说明：未来可以接入 AI / 联网画像能力识别待补公司，但当前版本还没有实现。

如果后续接入 AI，建议仍保持当前安全链路：**AI 只生成候选画像 → 页面预览 → 用户确认 → 只写入空字段**。

---

## 系统架构

```text
embedded-job-radar/
├── app/
│   ├── main.py                 # FastAPI 应用入口
│   ├── feishu.py               # 飞书 OpenAPI 封装、看板数据聚合、扫描/同步入口
│   ├── state.py                # 本地运行态与缓存
│   ├── bus.py                  # 事件流 / 状态推送
│   └── routers/
│       ├── config.py           # 飞书配置读写与连接测试
│       ├── dashboard.py        # 看板数据、刷新、扫描、同步接口
│       ├── completion.py       # 主表字段补齐：更新画像、预览、确认写入
│       └── status.py           # 运行状态接口
├── static/index.html           # 本地看板前端，原生 HTML/CSS/JS
├── intro.html                  # 单文件产品介绍页
├── data/
│   ├── company_profile_seeds.json
│   ├── company_profiles.json
│   └── seed_companies.json
├── src/
│   ├── main_table_completion.py
│   ├── dedupe_utils.py
│   ├── sync_pool_to_main.py
│   ├── sync_apply_url_deadline.py
│   ├── audit_pool.py
│   ├── audit_completeness.py
│   ├── full_sync.py
│   └── validate_data.py
├── tests/
│   ├── test_main_table_completion.py
│   ├── test_dedupe_utils.py
│   └── test_sync_selection.py
├── start-dashboard.py
├── start-dashboard.bat
├── install-deps.bat
├── requirements.txt
└── .env.example
```

---

## 快速开始

### 前置条件

- Python 3.11+
- 飞书账号
- 飞书自建应用
- 多维表格 `bitable:app` 权限

### 1. 克隆项目

```bash
git clone https://github.com/kaoya-123/embeded_job_rader.git
cd embeded_job_rader
```

### 2. 安装依赖

Windows 可直接双击：

```text
install-deps.bat
```

或者手动执行：

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置飞书凭证

复制环境变量模板：

```bash
cp .env.example .env
```

填写：

```bash
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_APP_TOKEN=你的多维表格 app_token
MAIN_TABLE_ID=主投递表 table_id
DISCOVERY_TABLE_ID=机会发现池 table_id
```

> `.env` 已写入 `.gitignore`，不要提交真实密钥。

也可以启动看板后，在浏览器配置页填写这些值。

### 4. 启动看板

Windows 可直接双击：

```text
start-dashboard.bat
```

或者运行：

```bash
python start-dashboard.py
```

也可以直接用 uvicorn：

```bash
py -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

打开浏览器访问：

```text
http://localhost:8765
```

---

## 常用命令

```bash
# 启动看板
python start-dashboard.py

# 直接启动 FastAPI
py -m uvicorn app.main:app --host 0.0.0.0 --port 8765

# 运行测试
python -m unittest discover -s tests

# 机会池审计
python src/audit_pool.py --dry-run

# 机会池 → 主表同步
python src/sync_pool_to_main.py

# 链接 / 截止时间同步
python src/sync_apply_url_deadline.py --dry-run
```

---

## 飞书表格字段参考

### 主投递表

常用字段：

| 字段名 | 类型 | 说明 |
|---|---|---|
| 公司名称 | 文本 | 必填 |
| 公司简介 | 文本 | 一句话概括 |
| 公司规模 | 文本 | 如 `500-1000人` |
| 工作地点 | 多选 | 公司所在地 / 投递城市 |
| 细分类型 | 多选 | 新势力车企、芯片原厂、IoT 等 |
| 公司/行业类型 | 多选 | 车厂、手机厂、互联网等 |
| 嵌入式方向 | 多选 | MCU、RTOS、Linux应用、驱动、BSP 等 |
| 岗位类型 | 单选 | 提前批 / 秋招 / 春招 |
| 意愿 | 单选 | P0 / P1 / P2 |
| 投递链接 | URL | 官方招聘入口 |
| 投递截止时间 | 文本 | 如 `2026-08-31` 或 `招满即止` |
| 秋招岗位 | 文本 | 目标岗位名 |
| JD原文 | 文本 | 岗位描述 |
| 进展 | 多选 | 测评、机考、一面、二面、OC 等 |
| 投递时间 | 日期 | 实际投递日期 |

### 机会发现池

常用字段：

| 字段名 | 类型 | 说明 |
|---|---|---|
| 标题 | 文本 | 自动生成 |
| 疑似公司 | 文本 | 匹配主表公司名 |
| 岗位名称 | 文本 | 发现的具体岗位 |
| 疑似嵌入式方向 | 多选 | 同主表方向选项 |
| 工作地点 | 多选 | 岗位地点 |
| 来源平台 | 单选 | 官网、公众号、牛客、高校就业网等 |
| 来源链接 | URL | 发现来源 |
| 投递链接 | URL | 实际投递入口 |
| 命中关键词 | 文本 | 匹配原因 |
| 可信度 | 单选 | 高 / 中 / 低 |
| 处理状态 | 单选 | 待确认 / 已入库 / 重复 / 忽略 |
| 岗位开放状态 | 单选 | 已开放 / 疑似开放 / 待确认 / 已截止 |
| JD原文 | 文本 | 岗位描述 |
| 发现类型 | 单选 | 公司校招开放 / 嵌入式岗位开放 / JD更新 / 截止提醒 |
| 去重Key | 文本 | 避免重复写入 |

---

## 安全说明

- 真实飞书凭证只应保存在本地 `.env` 或浏览器配置页写入的本地配置中
- `.env` 已被 `.gitignore` 忽略
- 不要把 `FEISHU_APP_SECRET`、访问令牌、个人账号密码提交到仓库
- 补齐功能默认不写入，必须预览并确认
- 写入前会再次检查飞书主表，避免覆盖手动维护字段

---

## 技术栈

| 组件 | 技术 |
|---|---|
| 后端框架 | FastAPI |
| 服务运行 | Uvicorn |
| 定时调度 | APScheduler |
| 数据存储 | 飞书多维表格 Bitable + 本地 JSON 画像库 |
| 动态渲染 / 抓取辅助 | Playwright |
| 前端 | 原生 HTML / CSS / JS |
| HTTP 客户端 | requests |
| 测试 | unittest |

---

## 贡献 & 许可

MIT License — 可自由使用、修改和分发。

如果你不是嵌入式方向，也可以复用这套架构：替换字段、种子公司和补齐规则，就能改成其他行业的校招投递看板。
