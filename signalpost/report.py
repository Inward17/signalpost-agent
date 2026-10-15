"""Self-contained HTML viewer: search, compare and verify every claim against its source (desktop + mobile)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signalpost profiles</title><style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14171f;--mut:#5b6472;--line:#e3e6eb;--acc:#1f4fd1;--ok:#137a3f;--warn:#a15c00;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaee;--mut:#9aa3b2;--line:#2a2f3a;--acc:#7ea2ff;--ok:#4cc38a;--warn:#f0b35a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2}
h1{font-size:18px;margin:0 0 8px}.row{display:flex;gap:8px;flex-wrap:wrap}input,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
input{flex:1;min-width:180px}main{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:16px;padding:16px;max-width:1400px;margin:auto}
@media (max-width:800px){main{grid-template-columns:1fr}#list{max-height:40vh}}
#list{overflow:auto;max-height:calc(100vh - 130px);display:flex;flex-direction:column;gap:6px}
.item{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer}.item.sel{outline:2px solid var(--acc)}
.item b{display:block}.mut{color:var(--mut);font-size:13px}.dots{display:flex;gap:3px;margin-top:6px}.dot{width:10px;height:10px;border-radius:3px;background:var(--line)}
.s-available{background:var(--ok)}.s-ambiguous,.s-blocked{background:var(--warn)}.s-failed{background:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px;overflow-wrap:anywhere}
h2{font-size:20px;margin:0}h3{font-size:15px;margin:0 0 8px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.pill{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);white-space:nowrap}.p-available{color:var(--ok)}.p-ambiguous,.p-blocked{color:var(--warn)}.p-failed{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:5px 4px;border-top:1px solid var(--line);vertical-align:top}td:first-child{color:var(--mut);width:34%}
a{color:var(--acc)}details{margin-top:4px}summary{cursor:pointer;color:var(--mut);font-size:13px}.ev{font-size:12px;color:var(--mut);margin:2px 0 6px}
ul{margin:4px 0;padding-left:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:12px}
.kpi{border:1px solid var(--line);border-radius:10px;padding:8px 10px}.kpi b{display:block;font-size:17px}
</style></head><body><header><h1>Signalpost · __COUNT__ company profiles <span class="mut">run __RUN__</span></h1>
<div class="row"><input id="q" placeholder="Search name, organisation number, municipality…" aria-label="search">
<select id="f" aria-label="filter"><option value="">All companies</option><option value="website">Verified website</option><option value="jobs">Hiring</option>
<option value="social_profiles">Social profiles</option><option value="changes">Changed since last run</option><option value="ambiguous">Has ambiguous match</option></select></div></header>
<main><div id="list" role="list"></div><div id="detail"><div class="card">Select a company.</div></div></main>
<script>
const D=__DATA__;const SECTIONS=["identity","financials","leadership","locations","website","social_profiles","contact","jobs","public_activity"];
const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safe=u=>/^https?:\/\//.test(u||"")?u:"#";
function fmt(v){if(v==null)return"";if(typeof v!=="object")return esc(v);if(v.amount!==undefined)return esc(Number(v.amount).toLocaleString("en")+" "+(v.currency||""))+(v.statement==="konsern"?" <span class=mut>(group)</span>":"");
 if(v.url&&v.title)return `<a href="${esc(safe(v.url))}" target=_blank rel=noopener>${esc(v.title)}</a> ${esc([v.date||v.published,v.locations&&v.locations.join(", ")].filter(Boolean).join(" · "))}`;
 if(v.url&&v.type)return `${esc(v.date)} · <a href="${esc(safe(v.url))}" target=_blank rel=noopener>${esc(v.type)}</a>`;
 if(v.url)return `<a href="${esc(safe(v.url))}" target=_blank rel=noopener>${esc(v.platform||v.url)}</a>`+(v.identity_method?` <span class=mut>${esc(v.identity_method)}</span>`:"");
 if(v.role)return `${esc(v.name)} — ${esc(v.role)}`;if(v.name&&v.address!==undefined)return `${esc(v.name)} <span class=mut>${esc(v.address||"")}</span>`;
 if(Array.isArray(v))return esc(v.map(x=>typeof x==="object"?(x.label||x.code||JSON.stringify(x)):x).join("; "));if(v.label)return esc(v.label);return esc(JSON.stringify(v))}
function list(){const q=$("#q").value.toLowerCase(),f=$("#f").value;const el=$("#list");el.innerHTML="";
 D.filter(e=>{const t=(e.n+" "+e.o+" "+(e.m||"")).toLowerCase();if(q&&!t.includes(q))return false;if(!f)return true;if(f==="changes")return e.ch.length>0;
  if(f==="ambiguous")return Object.values(e.s).some(s=>s.state==="ambiguous");return e.s[f]&&e.s[f].state==="available"}).slice(0,600).forEach(e=>{
  const d=document.createElement("div");d.className="item";d.role="listitem";d.tabIndex=0;d.onclick=d.onkeydown=ev=>{if(ev.type==="click"||ev.key==="Enter")show(e,d)};
  d.innerHTML=`<b>${esc(e.n||e.o)}</b><span class=mut>${esc(e.o)} · ${esc(e.m||"")}</span><div class=dots>${SECTIONS.map(s=>`<span title="${s}: ${esc(e.s[s]?.state)}" class="dot s-${esc(e.s[s]?.state)}"></span>`).join("")}</div>`;el.appendChild(d)})}
function show(e,node){document.querySelectorAll(".item.sel").forEach(x=>x.classList.remove("sel"));node&&node.classList.add("sel");const ev=Object.fromEntries(e.ev.map(x=>[x.id,x]));
 const by={};e.c.forEach(c=>(by[c.section]=by[c.section]||[]).push(c));
 const k=(f)=>e.c.find(c=>c.field===f&&(!c.value||c.value.statement!=="konsern"));const rev=e.c.filter(c=>c.field==="revenue"&&c.value.statement==="selskap").sort((a,b)=>b.reporting_period.localeCompare(a.reporting_period))[0];
 let h=`<div class=card><h2>${esc(e.n)}</h2><div class=mut>${esc(e.o)} · ${esc(e.f||"")} · ${esc(e.m||"")} · <a href="https://virksomhet.brreg.no/nb/oppslag/enheter/${esc(e.o)}" target=_blank rel=noopener>Brønnøysund</a></div>
 <p>${esc(e.sum.headline)}</p><div class=grid>
 <div class=kpi><span class=mut>Revenue ${rev?esc(rev.reporting_period.slice(-10,-6)):""}</span><b>${rev?fmt(rev.value):"—"}</b></div>
 <div class=kpi><span class=mut>Employees (register)</span><b>${k("registered_employees")?esc(k("registered_employees").value):"—"}</b></div>
 <div class=kpi><span class=mut>Open roles</span><b>${(by.jobs||[]).filter(c=>c.field==="job_posting").length}</b></div>
 <div class=kpi><span class=mut>Website</span><b>${e.s.website.state==="available"?"verified":esc(e.s.website.state)}</b></div></div></div>
 <div class=card><h3>Summary</h3><ul>${e.sum.points.map(p=>`<li>${esc(p.text)}</li>`).join("")}</ul>
 <details><summary>What changed</summary><ul>${e.sum.changes.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></details>
 <details><summary>Unknowns (${e.sum.unknowns.length})</summary><ul>${e.sum.unknowns.map(u=>`<li><b>${esc(u.section)}</b>: ${esc(u.state)} — ${esc(u.reason)}</li>`).join("")}</ul></details></div>`;
 SECTIONS.forEach(s=>{const st=e.s[s]||{};const cs=by[s]||[];h+=`<div class=card><h3>${s.replace("_"," ")}<span class="pill p-${esc(st.state)}">${esc(st.state)}</span></h3><div class=mut>${esc(st.reason)}</div>`;
  if(cs.length){h+=`<table>${cs.slice(0,60).map(c=>{const evs=c.evidence_ids.map(i=>ev[i]).filter(Boolean);return `<tr><td>${esc(c.field.replace(/_/g," "))}${c.reporting_period?`<div class=mut>${esc(c.reporting_period)}</div>`:""}${c.stale?"<div class=mut>stale</div>":""}</td><td>${fmt(c.value)}
   <details><summary>evidence</summary>${evs.map(x=>`<div class=ev><a href="${esc(safe(x.source_url))}" target=_blank rel=noopener>${esc(x.source_class)}</a> · retrieved ${esc(x.retrieved_at)} · “${esc(x.claim_span)}”</div>`).join("")}</details></td></tr>`}).join("")}</table>`}
  h+="</div>"});
 $("#detail").innerHTML=h;if(innerWidth<800)$("#detail").scrollIntoView()}
$("#q").oninput=list;$("#f").onchange=list;list();const first=document.querySelector(".item");if(first)first.click();
</script></body></html>"""


def write_html(path: Path, envelopes: list[dict[str, Any]], report: dict[str, Any]) -> None:
    rows = []
    for e in envelopes:
        li = e.get("legal_identity") or {}
        rows.append({"o": e["organisation_number"], "n": li.get("legal_name"), "f": li.get("legal_form"), "m": li.get("municipality"),
                     "s": e.get("sections", {}), "c": e.get("claims", []), "ev": e.get("evidence", []), "ch": e.get("changes", []),
                     "sum": e.get("summary") or {"headline": "", "points": [], "changes": [], "unknowns": []}})
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data).replace("__COUNT__", str(len(rows))).replace("__RUN__", str(report["run"]["run_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
