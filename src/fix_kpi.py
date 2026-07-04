import os

with open("src/dashboard.html", "r", encoding="utf-8") as fh:
    content = fh.read()

# 1. Replace KPI cards (6 per row, 2 rows)
old_kpi_start = '<div class="kpi-row">'
old_kpi_end = '<div class="alert-row" id="alerts"></div>'

kpi_idx = content.index(old_kpi_start)
alert_idx = content.index(old_kpi_end)

new_kpi_html = '''<div class="kpi-row">
  <div class="kpi b"><div class="kpi-label">已监控</div><div class="kpi-value" id="kpi-total">-</div><div class="kpi-sub">主表公司数</div></div>
  <div class="kpi b"><div class="kpi-label">已投递</div><div class="kpi-value" id="kpi-applied">-</div><div class="kpi-sub">已提交申请</div></div>
  <div class="kpi a"><div class="kpi-label">笔试/机考</div><div class="kpi-value" id="kpi-exam">-</div><div class="kpi-sub">已安排考试</div></div>
  <div class="kpi g"><div class="kpi-label">一面</div><div class="kpi-value" id="kpi-int1">-</div><div class="kpi-sub">技术面 / 综合面</div></div>
  <div class="kpi g"><div class="kpi-label">二面/终面</div><div class="kpi-value" id="kpi-int2">-</div><div class="kpi-sub">HR面 / 主管面</div></div>
  <div class="kpi g"><div class="kpi-label">Offer</div><div class="kpi-value" id="kpi-offer">-</div><div class="kpi-sub">已OC / 录用</div></div>
</div>

<div class="kpi-row">
  <div class="kpi r"><div class="kpi-label">即将截止</div><div class="kpi-value" id="kpi-urgent">-</div><div class="kpi-sub">7 天内关闭</div></div>
  <div class="kpi b"><div class="kpi-label">机会发现池</div><div class="kpi-value" id="kpi-pool">-</div><div class="kpi-sub">已开放校招</div></div>
  <div class="kpi b"><div class="kpi-label">嵌入式岗位</div><div class="kpi-value" id="kpi-jobs">-</div><div class="kpi-sub">有具体岗位名</div></div>
</div>

'''

content = content[:kpi_idx] + new_kpi_html + content[alert_idx:]

# 2. Add SVG pattern background before </style>
old_media = '@media(max-width:1200px)'
svg_bg = '''/* Subtle tech pattern overlay */
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.04;background-image:url("data:image/svg+xml,%3Csvg width='80' height='80' viewBox='0 0 80 80' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' stroke='%2338bdf8' stroke-width='0.6' stroke-opacity='0.3'%3E%3Ccircle cx='40' cy='40' r='38'/%3E%3Ccircle cx='40' cy='40' r='28' stroke-dasharray='3 5'/%3E%3Ccircle cx='40' cy='40' r='16'/%3E%3Cpath d='M40 2 L40 12 M40 68 L40 78 M2 40 L12 40 M68 40 L78 40'/%3E%3C/g%3E%3C/svg%3E")}
@media(max-width:1200px)'''

content = content.replace(old_media, svg_bg)

with open("src/dashboard.html", "w", encoding="utf-8") as fh:
    fh.write(content)

print("KPI layout fixed + SVG pattern added")
