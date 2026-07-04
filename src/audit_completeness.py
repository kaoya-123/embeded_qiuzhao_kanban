import os, json, requests
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
APP_ID=os.getenv("FEISHU_APP_ID"); APP_SECRET=os.getenv("FEISHU_APP_SECRET")
APP_TOKEN=os.getenv("FEISHU_APP_TOKEN"); MAIN=os.getenv("MAIN_TABLE_ID"); DISC=os.getenv("DISCOVERY_TABLE_ID")
API="https://open.feishu.cn/open-apis"
r=requests.post(f"{API}/auth/v3/tenant_access_token/internal", json={"app_id":APP_ID,"app_secret":APP_SECRET}, timeout=20)
token=r.json()["tenant_access_token"]

ALIAS = {"乐鑫科技": "乐鑫"}

r2=requests.get(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{DISC}/records", headers={"Authorization":f"Bearer {token}"}, params={"page_size":500}, timeout=30)
pool_a={}
for rec in r2.json()["data"]["items"]:
    f=rec["fields"]
    if f.get("发现类型")=="嵌入式岗位开放" and f.get("岗位开放状态")=="已开放":
        pool_a[f.get("疑似公司","").strip()]=None
pool_mapped={k:ALIAS.get(k,k) for k in pool_a}

r3=requests.get(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN}/records", headers={"Authorization":f"Bearer {token}"}, params={"page_size":500}, timeout=30)
main_map={}
for rec in r3.json()["data"]["items"]:
    cn=rec["fields"].get("公司名称","").strip()
    if cn: main_map[cn]=rec["fields"]

complete=[]; missing_detail=[]
for pool_cn, main_cn in pool_mapped.items():
    if main_cn not in main_map:
        missing_detail.append({"pool":pool_cn,"main":main_cn,"reason":"NOT_IN_MAIN"})
        continue
    f=main_map[main_cn]
    url=f.get("投递链接",""); u=url.get("link","") if isinstance(url,dict) else str(url)
    issues=[]
    if not u: issues.append("投递链接")
    if not f.get("投递截止时间",""): issues.append("投递截止时间")
    if not f.get("秋招岗位",""): issues.append("秋招岗位")
    if not f.get("岗位类型",""): issues.append("岗位类型")
    if not f.get("公司规模",""): issues.append("公司规模")
    if issues:
        missing_detail.append({"pool":pool_cn,"main":main_cn,"missing":issues})
    else:
        complete.append({"main":main_cn,"type":f.get("岗位类型",""),"size":f.get("公司规模","")})

deduped={c["main"]:c for c in complete}
unique=list(deduped.values())
unique.sort(key=lambda x:x["main"])

out={
    "pool_A":len(pool_a),"synced":len(unique),"missing":len(missing_detail),
    "companies":[f'{c["main"]} [{c["type"]}] size={c["size"]}' for c in unique],
    "missing_detail":missing_detail
}
with open("audit_final.json","w",encoding="utf-8") as fh: json.dump(out,fh,ensure_ascii=False,indent=2)
print(f'Pool A: {len(pool_a)} | Synced: {len(unique)} | Missing: {len(missing_detail)}')
for c in unique: print(f'  OK: {c["main"]} [{c["type"]}]')
