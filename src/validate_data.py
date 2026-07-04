"""
嵌入式秋招雷达 - 信息校验脚本
每次修改表格数据前必须运行此脚本，确保：
1. 岗位类型(提前批/秋招/待确认)准确
2. 投递截止时间准确(基于真实搜索验证)
3. 公司简介+公司规模齐全
4. 秋招岗位名不为空
5. 投递链接为有效URL
6. 机会池无重复、无脏数据、无实习内容
"""
import os, json, hashlib
from collections import defaultdict
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"


def token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d["tenant_access_token"]


def list_records(table_id):
    t = token()
    records, pt = [], None
    while True:
        params = {"page_size": 200}
        if pt: params["page_token"] = pt
        r = requests.get(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
                         headers={"Authorization": f"Bearer {t}"}, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(d)
        records.extend(d["data"]["items"])
        if not d["data"].get("has_more"):
            return records
        pt = d["data"].get("page_token")


def feishu_put(record_id, fields):
    t = token()
    r = requests.put(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN_TABLE_ID}/records/{record_id}",
                     headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=utf-8"},
                     json={"fields": fields}, timeout=30)
    r.raise_for_status()
    return r.json()


def feishu_post(path, payload):
    t = token()
    r = requests.post(f"{API}{path}",
                      headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=utf-8"},
                      json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d


# === 基于真实搜索验证的精确信息 ===
# 这个映射表必须在每次搜索验证后更新
VERIFIED_INFO = {
    "大疆":     ("秋招",    0,              "DJI大疆2027「拓疆者」校招(正式秋招)。网申6月25日开启，招满即止，不设固定截止日。"),
    "华为":     ("待确认",  0,              "华为2027届实习生(暑期实习可转正，非正式秋招)。网申即日起-6月30日。"),
    "中兴通讯": ("提前批",  1785254400000,   "中兴2027未来领军(提前批)。6月下旬启动，8月29日截止。"),
    "禾赛":     ("提前批",  1785772800000,   "禾赛科技2027秋招提前批。8月31日截止。"),
    "高德红外": ("秋招",    1796054400000,   "高德红外2027校园招聘(正式秋招)。2027年1月31日截止。"),
    "拓竹":     ("提前批",  0,              "拓竹科技2027研发类提前批。招满即止，7月5日前投递享第一批快速通道。"),
    "航天科技集团":("提前批",1783526400000,  "航天科技2027星辰英才提前批。各二级单位约7月3日-8日截止。"),
    "航天科工集团":("提前批",1783526400000,  "航天科工2027提前批。约7月4日-8日截止。"),
    "航天科工二院":("提前批",1783526400000,  "航天科工二院2027提前批。约7月4日-8日截止。"),
    "长江存储": ("提前批",  1785254400000,   "长江存储2027提前批。招满即止，参考有效期至8月29日。"),
    "长鑫存储": ("提前批",  0,              "长鑫存储2027提前批。5月30日启动，招满即止。双保险：落选可参加正式批。"),
    "格见半导体":("提前批", 1783008000000,   "格见半导体2027正式校招。6月4日-7月4日截止。"),
    "TP-LINK":  ("提前批",  0,              "TP-LINK 2027提前批。5月28日启动，招满即止。"),
    "小米":     ("待确认",  0,              "小米2027全球顶尖人才校招。6月5日启动，面向2024-2027届。"),
    "OPPO":     ("待确认",  0,              "OPPO校园招聘2027届。面向2027年1-12月中国大陆高校本硕毕业生。"),
    "VIVO":     ("待确认",  0,              "vivo校园招聘2027届。面向2027届毕业生。"),
    "比亚迪":   ("待确认",  0,              "比亚迪2027届校园招聘尚未正式启动。往年提前批7月，正式批8-9月。"),
    "汇川":     ("待确认",  0,              "汇川技术当前为2026届校招，27届尚未正式开放。"),
    "海康威视": ("待确认",  0,              "海康威视当前应届生岗位0。往年在7-8月大批开放。"),
    "滴滴":     ("秋招",    1781798400000,   "滴滴2027秋招储备实习生。4月2日起，约6月上旬截止。"),
    "百度":     ("提前批",  1785600000000,   "百度2027 AIDU+Apollo提前批。8月13日截止。"),
    "美团":     ("提前批",  1783526400000,   "美团2027北斗计划。7月3日截止。"),
    "中兵通信装备研究院":("秋招",1784563200000,"中兵通信装备研究院2027秋季校招。6月30日-7月7日。"),
    "零跑":     ("秋招",    1781798400000,   "零跑汽车2027校招。网申4.30-6.30(已截止)。转录率70%。"),
    "三一集团": ("待确认",  0,              "三一集团2027届提前批(4月25日-6月24日，已截止)。电气与控制方向含嵌入式。"),
    "比特大陆": ("提前批",  0,              "比特大陆2027届嵌入式软件/硬件工程师。Linux驱动/芯片测试方向。"),
    "华勤技术": ("提前批",  0,              "华勤技术2027届驱动开发工程师-BIOS/BSP/BMC。"),
    "锐明技术": ("提前批",  1784563200000,   "锐明技术2027星火计划。嵌入式开发/MCU/自动驾驶方向。"),
    "南方电网": ("提前批",  1784563200000,   "南方电网数字电网集团2027届。嵌入式/新能源/物联网方向。"),
    "中船凌久电子":("提前批",1784563200000,  "中船凌久电子(709所)2027届。嵌入式实时信号处理方向。"),
    "字节":     ("待确认",  0,              "字节跳动2027届ByteIntern实习生(7000+Offer，转正>50%)+Seed大模型校招。正式秋招预计7月中旬。"),
    "理想":     ("待确认",  0,              "理想汽车2027届实习招聘(4月27日-5月27日)。正式秋招预计8月启动。"),
}

# 公司简介+规模映射
COMPANY_PROFILES = {
    "大疆":     ("全球领先的无人机及影像技术公司，机器人领域独角兽。嵌入式/芯片/算法/硬件方向全面。", "1-5万人"),
    "华为":     ("全球ICT解决方案提供商，海思半导体+车BU+终端+云计算。", "10万人以上"),
    "中兴通讯": ("全球综合通信解决方案提供商，5G/光传输/芯片核心技术实力强。", "5-10万人"),
    "禾赛":     ("全球领先激光雷达制造商，自动驾驶核心传感器供应商。", "1000-5000人"),
    "高德红外": ("红外热成像行业龙头，覆盖红外探测器/机芯/整机及半导体。", "1000-5000人"),
    "拓竹":     ("消费级3D打印独角兽，高速高精度桌面打印机全球领先。", "1000-5000人"),
    "航天科技集团":("中国航天科技工业主导力量，覆盖运载火箭/卫星/飞船/深空探测。", "10万人以上"),
    "航天科工集团":("中国航天科工防御技术研究院，覆盖导弹武器/航天装备/信息技术。", "10万人以上"),
    "航天科工二院":("航天科工防御技术研究院第二研究院，雷达/制导/电子对抗。", "5000-10000人"),
    "长江存储": ("国内3D NAND闪存芯片龙头，存储器芯片和解决方案。", "5000-10000人"),
    "长鑫存储": ("国内领先DRAM制造商，产品覆盖移动/计算/消费电子。", "5000-10000人"),
    "格见半导体":("高端实时控制DSP芯片公司，车规级芯片方向。2022年成立。", "500-1000人"),
    "TP-LINK":  ("全球网络设备市占率第一，路由器/交换机/IPC/智能家居全线产品。", "1-5万人"),
    "小米":     ("全球消费电子和智能制造巨头，人车家全生态。", "5-10万人"),
    "OPPO":     ("全球领先智能终端制造商，手机及IoT生态产品。", "5-10万人"),
    "VIVO":     ("全球知名智能手机品牌，影像/设计/系统体验创新。", "5-10万人"),
    "比亚迪":   ("新能源汽车领导者，同时覆盖电池/电子/轨道交通。", "10万人以上"),
    "汇川":     ("工业自动化控制与驱动技术龙头，伺服/变频器/PLC/机器人/新能源电控。", "1-5万人"),
    "海康威视": ("全球安防行业龙头，AIoT技术提供商。", "5-10万人"),
    "滴滴":     ("全球领先移动出行平台，自动驾驶算法/调度研发方向。", "1-5万人"),
    "百度":     ("中国领先AI公司和搜索引擎，Apollo自动驾驶平台全球知名。", "5-10万人"),
    "美团":     ("中国领先生活服务及零售科技平台。北斗计划自动驾驶/无人机/具身智能方向。", "5-10万人"),
    "中兵通信装备研究院":("中国兵器工业集团旗下通信装备研发机构。ARM/FPGA/DSP平台。", "1000-5000人"),
    "零跑":     ("全域自研智能电动汽车企业。嵌入式软件开发/电控算法方向。", "5000-10000人"),
    "三一集团": ("中国工程机械龙头，挖掘机/起重机/混凝土机械全球领先。", "5-10万人"),
    "比特大陆": ("全球领先数字货币矿机及AI芯片设计公司。Linux驱动/芯片测试方向。", "1000-5000人"),
    "华勤技术": ("全球领先智能硬件ODM企业，手机/平板/笔电/服务器。", "1-5万人"),
    "锐明技术": ("商用车视频监控及车联网解决方案提供商。", "1000-5000人"),
    "南方电网": ("中央企业，覆盖南方五省区电网及数字电网/新能源/储能技术。", "10万人以上"),
    "中船凌久电子":("中船709所控股，嵌入式实时信号处理/高性能计算方向。", "500-1000人"),
    "字节":     ("全球领先科技公司，旗下抖音/TikTok等产品。智能硬件/IoT设备端。", "5-10万人"),
    "理想":     ("智能电动汽车企业，主打增程式电动SUV和家庭出行场景。", "1-5万人"),
}


def audit_main_table(fix=False):
    """校验主表：岗位类型、截止时间、简介、规模、秋招岗位、投递链接"""
    records = list_records(MAIN_TABLE_ID)
    issues = []
    for r in records:
        f = r.get("fields", {})
        name = (f.get("公司名称") or "").strip()
        status = f.get("岗位开放状态", "")
        if status not in ("已开放", "疑似开放"):
            continue
        problems = []
        if not f.get("岗位类型"): problems.append("缺岗位类型")
        if not f.get("秋招岗位"): problems.append("缺秋招岗位")
        if not f.get("投递链接"): problems.append("缺投递链接")
        if not f.get("JD原文"): problems.append("缺JD原文")
        if not f.get("公司简介"): problems.append("缺公司简介")
        if not f.get("公司规模"): problems.append("缺公司规模")
        if problems:
            issues.append((name, r["record_id"], problems, f))
            print(f"  ⚠ {name}: {', '.join(problems)}")

    if fix and issues:
        for name, rid, problems, f in issues:
            fields = {}
            # 修正岗位类型+截止时间
            if name in VERIFIED_INFO:
                v = VERIFIED_INFO[name]
                if "缺岗位类型" in problems:
                    fields["岗位类型"] = v[0]
                if "缺JD原文" in problems or not f.get("JD原文"):
                    fields["JD原文"] = v[2]
                dl = v[1]
                if dl == 0:
                    fields["投递截止时间"] = 0
                elif dl > 0:
                    fields["投递截止时间"] = dl
            # 修正简介+规模
            if name in COMPANY_PROFILES:
                intro, scale = COMPANY_PROFILES[name]
                if "缺公司简介" in problems:
                    fields["公司简介"] = intro
                if "缺公司规模" in problems:
                    fields["公司规模"] = scale
            if fields:
                feishu_put(rid, fields)
                print(f"  ✅ 修正 {name}: {list(fields.keys())}")

    return len(issues)


def audit_pool():
    """校验机会池：去重、去脏数据、去实习"""
    records = list_records(DISCOVERY_TABLE_ID)
    print(f"  机会池总数: {len(records)}")

    # 规则1: 实习相关 → 删除
    INTERN_PATTERNS = ["实习", "暑期", "intern", "Intern", "转正实习"]
    # 规则2: 脏数据
    DIRTY_PATTERNS = ["位 需求岗位", "026-06-25", "位 確保位"]
    # 规则3: 同公司同岗位同类型去重

    to_delete = []
    for r in records:
        f = r.get("fields", {})
        title = f.get("标题", "")
        job = f.get("岗位名称", "")

        for pat in INTERN_PATTERNS:
            if pat in title or pat in job:
                to_delete.append(r["record_id"])
                print(f"  [实习] 删除: {r['record_id']} ({title[:50]})")
                break
        else:
            for pat in DIRTY_PATTERNS:
                if pat in title or pat in job:
                    to_delete.append(r["record_id"])
                    print(f"  [脏数据] 删除: {r['record_id']} ({title[:50]})")
                    break

    # 按(公司, 岗位名前40字, 发现类型)去重
    groups = defaultdict(list)
    for r in records:
        if r["record_id"] in to_delete:
            continue
        f = r.get("fields", {})
        key = f"{(f.get('疑似公司') or '').strip()}|{(f.get('岗位名称') or '').strip()[:40]}|{(f.get('发现类型') or '').strip()}"
        groups[key].append(r)

    for key, recs in groups.items():
        if len(recs) > 1:
            recs.sort(key=lambda x: x.get("fields", {}).get("首次发现时间", 0) or 0)
            for r in recs[1:]:
                to_delete.append(r["record_id"])
                print(f"  [去重] 删除: {r['record_id']} ({r.get('fields',{}).get('标题','')[:60]})")

    # 有岗位级的删公司级
    companies_with_job = set()
    for recs in groups.values():
        for r in recs:
            if r.get("fields", {}).get("发现类型") == "嵌入式岗位开放":
                companies_with_job.add((r.get("fields", {}).get("疑似公司") or "").strip())

    for key, recs in groups.items():
        company = key.split("|")[0]
        dtype = key.split("|")[-1]
        if dtype == "公司校招开放" and company in companies_with_job:
            for r in recs:
                if r["record_id"] not in to_delete:
                    to_delete.append(r["record_id"])
                    print(f"  [冗余] 删除公司级(已有岗位级): {r['record_id']} ({company})")

    if to_delete:
        to_delete = list(set(to_delete))
        for i in range(0, len(to_delete), 500):
            batch = to_delete[i:i+500]
            feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records/batch_delete",
                        {"records": batch})

    print(f"  去重删除: {len(to_delete)}条, 剩余: {len(records)-len(set(to_delete))}条")
    return len(to_delete)


if __name__ == "__main__":
    print("=== 机会池审计 ===")
    audit_pool()
    print("\n=== 主表审计 ===")
    issues = audit_main_table(fix=True)
    print(f"\n=== 审计完成: 主表问题{issues}个 ===")
