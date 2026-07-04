import json, os

with open("src/dashboard.html", "r", encoding="utf-8") as fh:
    lines = fh.readlines()

new_line = "    document.getElementById('recent-tbody').innerHTML=d.main.recent.slice(0,25).map(r=>`<tr><td>${r.company||'—'}</td><td>${r.job||'—'}</td><td>${fmtDate(r.apply_date)}</td><td>${fmtDate(r.exam_date)}</td><td>${fmtDate(r.interview1)}</td><td>${fmtDate(r.interview2)}</td><td>${(r.progress||[]).join(' → ')||'未填写'}</td><td>${r.url?`<a href=\"${r.url}\" target=_blank>投递</a>`:'—'}</td><td>${mDL(r.deadline)}</td></tr>`).join('')||'<tr><td colspan=\"9\" class=\"center\">暂无投递记录</td></tr>';\n"

lines[311] = new_line

with open("src/dashboard.html", "w", encoding="utf-8") as fh:
    fh.writelines(lines)

print("Line 312 replaced")
