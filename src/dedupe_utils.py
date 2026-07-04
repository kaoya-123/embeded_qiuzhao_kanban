import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ALIAS_MAP = {
    "乐鑫科技": "乐鑫",
}

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "source", "channel", "share", "invite", "scene",
}

OFFICIAL_HOST_HINTS = (
    "zhiye.com", "jobs.feishu.cn", "career", "campus", "zhaopin", "jobs.",
    "hr.", "apply.careers", "liepin.com", "moka", "italent",
)

THIRD_PARTY_HOST_HINTS = (
    "qq.com", "163.com", "weixin", "nowcoder", "newjobs", "yingjiesheng",
    "job.cingta", "job1001", "zhaopin.com", "51job", "liepin.com",
)

DESCRIPTION_PREFIX_RE = re.compile(r"^\s*(?:\d+[\.、)]|[（(]\d+[）)]|[-•·])\s*")
DESCRIPTION_WORD_RE = re.compile(
    r"负责|参与|协助|熟悉|具备|掌握|任职要求|岗位职责|工作职责|优先|能力要求|完成|开发维护|设计实现"
)
JOB_TITLE_WORD_RE = re.compile(r"工程师|开发|岗位|职位|研究员|管培生|校招生|算法|软件|硬件|设计")


def normalize_company(name):
    text = re.sub(r"\s+", "", str(name or "")).strip()
    return ALIAS_MAP.get(text, text)


def extract_url_value(value):
    if isinstance(value, dict):
        return value.get("link", "") or value.get("url", "") or value.get("text", "")
    if isinstance(value, list):
        for item in value:
            url = extract_url_value(item)
            if url:
                return url
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def normalize_url(url, keep_fragment_for_job=True):
    raw = extract_url_value(url).strip()
    if not raw:
        return ""
    if raw.startswith("mailto:"):
        return raw.lower()
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw.rstrip("/")
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path or "").rstrip("/")
    query_pairs = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in TRACKING_PARAMS or key.lower().startswith("utm_"):
            continue
        query_pairs.append((key, val))
    query = urlencode(query_pairs, doseq=True)
    fragment = parts.fragment if keep_fragment_for_job else ""
    return urlunsplit((scheme, netloc, path, query, fragment)).rstrip("/")


def normalize_job_name(job):
    text = str(job or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ｜|-—:：;,，。")
    return text


def is_description_like_job(job):
    text = normalize_job_name(job)
    if not text or text == "待确认具体岗位":
        return False
    has_prefix = bool(DESCRIPTION_PREFIX_RE.search(text))
    has_desc_word = bool(DESCRIPTION_WORD_RE.search(text))
    has_title_word = bool(JOB_TITLE_WORD_RE.search(text))
    if has_prefix and has_desc_word:
        return True
    if len(text) > 38 and has_desc_word and not has_title_word:
        return True
    if len(text) > 55 and has_desc_word:
        return True
    return False


def canonical_job_for_key(job):
    text = normalize_job_name(job)
    if not text or text == "待确认具体岗位" or is_description_like_job(text):
        return "__generic__"
    # 多岗位聚合或正常岗位名保留，但去掉容易抖动的空白。
    return text.lower()


def discovery_exact_key(company, url, discovery_type, job):
    raw = "|".join([
        normalize_company(company),
        normalize_url(url),
        str(discovery_type or "").strip(),
        canonical_job_for_key(job),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def discovery_cluster_key(fields):
    company = normalize_company((fields or {}).get("疑似公司"))
    dtype = str((fields or {}).get("发现类型") or "").strip()
    url = normalize_url((fields or {}).get("投递链接") or (fields or {}).get("来源链接"), keep_fragment_for_job=False)
    if not url:
        url = "__no_url__"
    # 公司级和岗位级分开；同公司同入口下职责句/岗位汇总落同一簇。
    return f"{company}|{dtype}|{url}"


def _deadline_value(fields):
    return (fields or {}).get("投递截至时间") or (fields or {}).get("投递截止时间") or ""


def _url_score(url):
    norm = normalize_url(url)
    if not norm:
        return 0
    if norm.startswith("mailto:"):
        return -10
    host = urlsplit(norm).netloc.lower() if "://" in norm else norm.lower()
    score = 4
    if any(h in host or h in norm for h in OFFICIAL_HOST_HINTS):
        score += 8
    if any(h in host or h in norm for h in THIRD_PARTY_HOST_HINTS):
        score -= 4
    return score


def score_pool_record(record):
    fields = record.get("fields", record) or {}
    score = 0
    if fields.get("岗位开放状态") == "已开放":
        score += 30
    elif fields.get("岗位开放状态") == "疑似开放":
        score += 8
    if fields.get("发现类型") == "嵌入式岗位开放":
        score += 25
    elif fields.get("发现类型") == "公司校招开放":
        score += 5
    if fields.get("可信度") == "高":
        score += 10
    job = normalize_job_name(fields.get("岗位名称"))
    if job and job != "待确认具体岗位":
        score += 20
    if is_description_like_job(job):
        score -= 45
    if _deadline_value(fields):
        score += 18
    score += _url_score(fields.get("投递链接") or fields.get("来源链接"))
    jd = str(fields.get("JD原文") or "")
    if len(jd) > 80:
        score += min(len(jd), 2000) // 200
    if fields.get("首次发现时间"):
        # earliest wins only as tie-breaker elsewhere, not as quality score.
        score += 1
    return score


def choose_best_pool_record(records):
    if not records:
        return None
    return sorted(
        records,
        key=lambda r: (
            score_pool_record(r),
            -(r.get("fields", {}).get("首次发现时间") or 0),
            r.get("record_id", ""),
        ),
        reverse=True,
    )[0]


def best_job_name(records):
    best = choose_best_pool_record([
        r for r in records
        if normalize_job_name(r.get("fields", r).get("岗位名称"))
        and not is_description_like_job(r.get("fields", r).get("岗位名称"))
        and normalize_job_name(r.get("fields", r).get("岗位名称")) != "待确认具体岗位"
    ])
    if not best:
        return ""
    return normalize_job_name(best.get("fields", best).get("岗位名称"))


def best_deadline(records):
    candidates = []
    for r in records:
        fields = r.get("fields", r) or {}
        deadline = _deadline_value(fields)
        if deadline:
            candidates.append((score_pool_record(r), str(deadline)))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def best_url(records):
    candidates = []
    for r in records:
        fields = r.get("fields", r) or {}
        url = extract_url_value(fields.get("投递链接")) or extract_url_value(fields.get("来源链接"))
        if url:
            candidates.append((_url_score(url), score_pool_record(r), url))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][2]


def merge_pool_fields(records):
    best = choose_best_pool_record(records)
    if not best:
        return {}
    merged = dict(best.get("fields", best) or {})
    job = best_job_name(records)
    if job:
        merged["岗位名称"] = job
    deadline = best_deadline(records)
    if deadline:
        merged["投递截至时间"] = deadline
    url = best_url(records)
    if url:
        merged["投递链接"] = {"link": url, "text": url}
    first_times = [r.get("fields", {}).get("首次发现时间") for r in records if r.get("fields", {}).get("首次发现时间")]
    recent_times = [r.get("fields", {}).get("最近检测时间") for r in records if r.get("fields", {}).get("最近检测时间")]
    if first_times:
        merged["首次发现时间"] = min(first_times)
    if recent_times:
        merged["最近检测时间"] = max(recent_times)
    return merged


def group_records_by_company(records):
    groups = {}
    for record in records:
        fields = record.get("fields", {})
        company = normalize_company(fields.get("疑似公司"))
        if not company:
            continue
        groups.setdefault(company, []).append(record)
    return groups
