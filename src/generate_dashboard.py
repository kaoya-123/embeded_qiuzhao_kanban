import os
import json
from collections import Counter, defaultdict
from datetime import datetime
from html import escape

import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")

API = "https://open.feishu.cn/open-apis"


def token():
    r = requests.post(
        f"{API}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data)
    return data["tenant_access_token"]


def list_records(table_id):
    t = token()
    headers = {"Authorization": f"Bearer {t}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(data)
        block = data.get("data", {})
        records.extend(block.get("items", []))
        if not block.get("has_more"):
            break
        page_token = block.get("page_token")
    return records


def text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " / ".join(str(x) for x in v)
    if isinstance(v, dict):
        return v.get("text") or v.get("link") or json.dumps(v, ensure_ascii=False)
    return str(v)


def url(v):
    if isinstance(v, dict):
        return v.get("link", "")
    if isinstance(v, str):
        return v
    return ""


def first_select(fields, name):
    v = fields.get(name)
    if isinstance(v, list):
        return v[0] if v else "未填写"
    return v or "未填写"


def render_bar(label, count, max_count):
    pct = 0 if max_count == 0 else int(count / max_count * 100)
    return f"""
    <div class=\"bar-row\"><span>{escape(label)}</span><strong>{count}</strong></div>
    <div class=\"bar-bg\"><div class=\"bar-fill\" style=\"width:{pct}%\"></div></div>
    """


def main():
    main_records = list_records(MAIN_TABLE_ID)
    pool_records = list_records(DISCOVERY_TABLE_ID)

    rows = [r.get("fields", {}) for r in main_records if r.get("fields", {}).get("公司名称")]
    pool = [r.get("fields", {}) for r in pool_records]

    progress = Counter()
    directions = Counter()
    company_types = Counter()
    intention = Counter()

    for f in rows:
        for p in f.get("进展", []) or ["未填写"]:
            progress[p] += 1
        for d in f.get("嵌入式方向", []) or ["未填写"]:
            directions[d] += 1
        for c in f.get("公司/行业类型", []) or ["未填写"]:
            company_types[c] += 1
        intention[first_select(f, "意愿")] += 1

    max_progress = max(progress.values() or [0])
    max_dir = max(directions.values() or [0])
    max_type = max(company_types.values() or [0])

    recent_rows = sorted(
        rows,
        key=lambda f: f.get("投递时间", 0) or 0,
        reverse=True,
    )[:20]

    pool_rows = pool[:30]

    html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>嵌入式秋招雷达</title>
<style>
:root {{ --bg:#0b1020; --card:#141a2e; --muted:#95a3b8; --text:#edf2ff; --line:#26314f; --accent:#6ee7b7; --accent2:#60a5fa; --warn:#fbbf24; --danger:#fb7185; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:linear-gradient(135deg,#0b1020,#111827 45%,#172554); color:var(--text); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:32px; }}
.header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; margin-bottom:28px; }}
h1 {{ margin:0; font-size:34px; letter-spacing:.5px; }}
.sub {{ color:var(--muted); margin-top:8px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:18px; }}
.card {{ background:rgba(20,26,46,.88); border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:0 12px 40px rgba(0,0,0,.22); backdrop-filter: blur(10px); }}
.kpi .num {{ font-size:34px; font-weight:800; margin-top:8px; }}
.kpi .label {{ color:var(--muted); }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:18px; }}
.three {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-bottom:18px; }}
h2 {{ font-size:18px; margin:0 0 16px 0; }}
.bar-row {{ display:flex; justify-content:space-between; color:#dbeafe; font-size:14px; margin:10px 0 6px; }}
.bar-bg {{ height:8px; background:#0f172a; border-radius:999px; overflow:hidden; }}
.bar-fill {{ height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); border-radius:999px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ padding:10px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:#bfdbfe; text-align:left; font-weight:700; }}
td {{ color:#dbeafe; }}
a {{ color:#93c5fd; text-decoration:none; }}
.tag {{ display:inline-block; border:1px solid #334155; background:#111827; color:#dbeafe; padding:2px 8px; border-radius:999px; margin:2px; font-size:12px; }}
.badge {{ display:inline-block; padding:4px 8px; border-radius:8px; background:#172554; color:#bfdbfe; }}
.footer {{ color:var(--muted); margin-top:20px; font-size:12px; }}
@media (max-width:900px) {{ .grid,.two,.three {{ grid-template-columns:1fr; }} .wrap {{ padding:18px; }} }}
</style>
</head>
<body>
<div class=\"wrap\">
  <div class=\"header\">
    <div>
      <h1>嵌入式秋招雷达</h1>
      <div class=\"sub\">从飞书多维表格实时生成 · 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    </div>
    <div class=\"badge\">投递记录主表 + 机会发现池</div>
  </div>

  <div class=\"grid\">
    <div class=\"card kpi\"><div class=\"label\">已记录公司</div><div class=\"num\">{len(rows)}</div></div>
    <div class=\"card kpi\"><div class=\"label\">已投递/流程中</div><div class=\"num\">{sum(progress.values())}</div></div>
    <div class=\"card kpi\"><div class=\"label\">机会发现池</div><div class=\"num\">{len(pool)}</div></div>
    <div class=\"card kpi\"><div class=\"label\">P0 高意愿</div><div class=\"num\">{intention.get('P0-高意愿',0)}</div></div>
  </div>

  <div class=\"three\">
    <div class=\"card\"><h2>投递进展漏斗</h2>{''.join(render_bar(k,v,max_progress) for k,v in progress.most_common())}</div>
    <div class=\"card\"><h2>嵌入式方向分布</h2>{''.join(render_bar(k,v,max_dir) for k,v in directions.most_common(12))}</div>
    <div class=\"card\"><h2>公司/行业类型</h2>{''.join(render_bar(k,v,max_type) for k,v in company_types.most_common(12))}</div>
  </div>

  <div class=\"card\" style=\"margin-bottom:18px\">
    <h2>最近投递记录</h2>
    <table><thead><tr><th>公司</th><th>公司类型</th><th>嵌入式方向</th><th>进展</th><th>岗位</th><th>投递链接</th></tr></thead><tbody>
    {''.join(f"<tr><td>{escape(text(f.get('公司名称')))}</td><td>{escape(text(f.get('公司/行业类型')))}</td><td>{''.join('<span class=tag>'+escape(x)+'</span>' for x in (f.get('嵌入式方向') or []))}</td><td>{escape(text(f.get('进展')))}</td><td>{escape(text(f.get('秋招岗位')))}</td><td>{'<a href='+repr(url(f.get('投递链接')))+' target=_blank>打开</a>' if url(f.get('投递链接')) else ''}</td></tr>" for f in recent_rows)}
    </tbody></table>
  </div>

  <div class=\"card\">
    <h2>机会发现池（只展示已入库/待确认来源）</h2>
    <table><thead><tr><th>标题</th><th>公司</th><th>岗位</th><th>方向</th><th>状态</th><th>来源</th></tr></thead><tbody>
    {''.join(f"<tr><td>{escape(text(f.get('标题')))}</td><td>{escape(text(f.get('疑似公司')))}</td><td>{escape(text(f.get('岗位名称')))}</td><td>{''.join('<span class=tag>'+escape(x)+'</span>' for x in (f.get('疑似嵌入式方向') or []))}</td><td>{escape(text(f.get('岗位开放状态')))}</td><td>{'<a href='+repr(url(f.get('来源链接')))+' target=_blank>来源</a>' if url(f.get('来源链接')) else ''}</td></tr>" for f in pool_rows)}
    </tbody></table>
  </div>

  <div class=\"footer\">说明：机会发现池不会自动等同于“已投递”；确认要投后再进入主表。</div>
</div>
</body>
</html>"""

    out = os.path.join(os.path.dirname(__file__), "..", "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(out)


if __name__ == "__main__":
    main()
