import os

# Add fmtDate helper function
with open("src/dashboard.html", "r", encoding="utf-8") as fh:
    content = fh.read()

# Insert fmtDate before mDL function
old = "function mDL(ts){"
new = "function fmtDate(v){if(!v||v===0)return'—';if(typeof v==='number'){const d=new Date(v);return isNaN(d.getTime())?'—':d.toISOString().slice(0,10)}return String(v).slice(0,10);}\n    function mDL(ts){"

content = content.replace(old, new)

with open("src/dashboard.html", "w", encoding="utf-8") as fh:
    fh.write(content)

print("fmtDate inserted")
