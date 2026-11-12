"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const views = {overview:"Overview", rankings:"Rankings", indexation:"Indexation", queue:"Bing check queue", history:"History", export:"Export and setup"};
let dataset, requestId = 0, snippet = "", queueURL = "";
const visited = new Set();
const editedTitles = new Map();
let state = {};
function readState() {
  const parts = location.hash.slice(1).split("?");
  const params = new URLSearchParams(parts[1] || "");
  state = {view: views[parts[0]] ? parts[0] : "overview", source: params.get("source") === "mine" ? "mine" : "demo", query:params.get("query") || "", market:params.get("market") || "us", engine:params.get("engine") === "bing" ? "bing" : "google", filter:params.get("filter") || "all", search:params.get("search") || "", sort:params.get("sort") || "page", desc:params.get("desc") === "1"};
  $("source").value = state.source;
}
function navigate(changes, replace=false) {
  const next = {...state, ...changes};
  const params = new URLSearchParams();
  ["source","query","market","engine","filter","search","sort"].forEach(k => {if (next[k]) params.set(k, next[k]);});
  if (next.desc) params.set("desc", "1");
  const hash = "#" + next.view + "?" + params;
  if (replace) {history.replaceState(null, "", hash); state=next;} else location.hash = hash;
}
function link(url, label) {
  try {
    const u = new URL(url);
    if (!["http:","https:"].includes(u.protocol) || u.username || u.password) return el("span", label);
    const a = el("a", label); a.href = url; a.target="_blank"; a.rel="noopener noreferrer"; a.title=url;
    return a;
  } catch {return el("span", label);}
}
function time(at) {
  const n = el("time", at ? at.replace("T", " ").replace(/\.\d+Z$/, "Z").replace(/Z$/, " UTC") : "Never checked");
  if (at) n.dateTime=at;
  n.title=at || "No saved reading";
  return n;
}
function chip(r) {
  const labels = {"dataforseo-google":"DataForSEO Google", "dataforseo-bing":"Bing API: unverified", "browser-import":"Browser import", gsc:"Search Console", synthetic:"Synthetic", "rank-run":"Seen ranking", none:"No source"};
  const c = el("span", r.note === "suspect" ? "Suspect Bing API" : labels[r.provider] || r.provider, "chip");
  if (r.provider === "dataforseo-bing" || r.note === "suspect" || r.evidence?.run_provider === "dataforseo-bing") c.classList.add("warn");
  c.title=[labels[r.provider], r.evidence?.run_provider, r.note, r.provider === "dataforseo-bing" ? dataset.derived.bing_warning : ""].filter(Boolean).join(". ");
  return c;
}
function status(r) {
  const label = r.indexed === true ? (r.status.startsWith("Indexed (seen") ? r.status : "Indexed") : r.indexed === false ? (r.status === "Not found" ? "Not found" : "Not indexed") : "Unknown";
  const n = el("span", label, "status " + (r.indexed === true ? "yes" : r.indexed === false ? "no" : "unknown"));
  n.title = [r.status, r.note].filter(Boolean).join(". "); return n;
}
function reading(r) {
  const n=el("span",undefined,"reading"); n.append(status(r),chip(r),time(r.at)); return n;
}
function table(headers, rows, label, sorting) {
  const wrap=el("div",undefined,"table-wrap"); wrap.tabIndex=0; wrap.setAttribute("role","region"); wrap.setAttribute("aria-label",label + ". Scroll horizontally for all columns.");
  const t=el("table"), head=el("thead"), tr=el("tr"), body=el("tbody");
  headers.forEach((h,i)=>{
    const th=el("th"); th.scope="col";
    if (sorting) {
      const b=el("button", h + (state.sort === sorting[i] ? (state.desc ? " ↓":" ↑") : "")); b.type="button";
      b.onclick=()=>navigate({sort:sorting[i],desc:state.sort === sorting[i] ? !state.desc:false});
      th.append(b); th.setAttribute("aria-sort",state.sort === sorting[i] ? (state.desc ? "descending":"ascending") : "none");
    } else th.textContent=h;
    tr.append(th);
  });
  head.append(tr);
  rows.forEach(row=>{
    const r=el("tr"); if(row.mine) r.className="owned";
    row.cells.forEach(c=>{const td=el("td"); td.append(c instanceof Node ? c : document.createTextNode(String(c ?? ""))); td.title=td.textContent; r.append(td);});
    body.append(r);
  });
  t.append(head,body); wrap.append(t); return wrap;
}
function empty(title, description) {const n=el("div",undefined,"empty"); n.append(el("h2",title),el("p",description));return n;}
function field(label, control) {const f=el("label",undefined,"field");f.append(el("span",label),control);return f;}
function select(options, value, change) {const s=el("select");options.forEach(([v,t])=>{const o=el("option",t);o.value=v;s.append(o);});s.value=value;s.onchange=()=>change(s.value);return s;}
function chart(runs, small=false) {
  if (!runs.length) return el("span","No history","hint");
  const ns="http://www.w3.org/2000/svg", svg=document.createElementNS(ns,"svg");
  const make=(tag,attrs)=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;};
  const w=small?110:600,h=small?32:140,p=small?3:24;
  svg.setAttribute("viewBox",`0 0 ${w} ${h}`); svg.setAttribute("role","img");svg.setAttribute("aria-label","Best owned rank history, rank 1 is highest. Gaps mean not found in the saved sample.");svg.classList.add("chart");if(small)svg.classList.add("spark");
  const title=document.createElementNS(ns,"title");title.textContent=runs.map(r=>`${r.at}: ${r.best_rank === null ? "not found" : "rank " + r.best_rank}`).join("; ");svg.append(title);
  const max=Math.max(10,...runs.map(r=>r.best_rank||0));
  const x=i=>p+(runs.length===1?.5:i/(runs.length-1))*(w-p*2), y=r=>p+((r-1)/(max-1))*(h-p*2);
  let segment=[];
  const flush=()=>{if(segment.length)svg.append(make("polyline",{points:segment.join(" "),class:"line"}));segment=[];};
  runs.forEach((r,i)=>{if(r.best_rank===null){flush();return;}segment.push(`${x(i)},${y(r.best_rank)}`);svg.append(make("circle",{cx:x(i),cy:y(r.best_rank),r:small?1.8:3}));});flush();
  if(!small) {
    svg.append(make("line",{x1:p,y1:h-p,x2:w-p,y2:h-p,class:"axis"}));
    [["#1",1],["#"+max,max]].forEach(([label,r])=>{const t=make("text",{x:0,y:y(r)+4});t.textContent=label;svg.append(t);});
  }
  return svg;
}
function historyFor(query, market, engine) {return dataset.derived.rank_history.find(h=>h.query===query&&h.market===market&&h.engine===engine)?.runs || [];}
function overview(root) {
  const d=dataset.derived, metrics=el("div",undefined,"metrics");
  const unknown=d.pages.filter(p=>Object.values(p.engines).some(r=>r.indexed===null)).length;
  [["Pages tracked",d.pages.length],["Indexed in Google",d.counts.google.indexed],["Indexed in Bing",d.counts.bing.indexed],["Unknown in either engine",unknown]].forEach(([name,value])=>{const n=el("div",undefined,"metric");n.append(el("span",name,"label"),el("strong",String(value)),el("span",name.startsWith("Unknown")?"Missing evidence, not a negative":"Current saved evidence","hint"));metrics.append(n);});root.append(metrics);
  const engines=el("div",undefined,"engine-grid");
  ["google","bing"].forEach(e=>{const c=d.counts[e],p=el("div",undefined,"panel");p.append(el("p",e.toUpperCase(),"label"),el("h2",`Indexed ${c.indexed} of ${c.total}`),el("p",`${c.not_indexed} ${e==="bing"?"not found":"not indexed"} · ${c.unknown} unknown`,"hint"));engines.append(p);});root.append(engines);
  root.append(el("h2","Your pages in the results"),el("p","Owned pages match exact tracked URL identities. Each line shows the latest reading in its market.","hint"));
  const cards=el("div",undefined,"cards");
  dataset.queries.forEach(q=>{const c=el("article",undefined,"query-card");c.append(el("h3",q.query));q.markets.forEach(m=>["google","bing"].forEach(e=>{
    const runs=historyFor(q.query,m,e),r=runs.at(-1),line=el("div",undefined,"query-line");
    line.append(el("strong",e[0].toUpperCase()+e.slice(1)+" · "+m.toUpperCase()));
    if(r) {
      line.append(el("span",r.best_rank===null?"Not in sample":"Best #"+r.best_rank),el("span",`${r.top10_yours} of the top 10 are yours`),chart(runs,true),chip(r),time(r.at));
      const a=el("a","Inspect →");a.href="#rankings?"+new URLSearchParams({source:state.source,query:q.query,market:m,engine:e});line.append(a);
    } else line.append(el("span","No saved run","hint"));c.append(line);
  }));cards.append(c);});
  root.append(cards);
  if(!dataset.queries.length)root.append(empty("No queries yet","Add a query in the CLI. See Export and setup for commands."));
}
function rankings(root) {
  const queries=[...new Set([...dataset.queries.map(q=>q.query),...dataset.rank_runs.map(r=>r.query)])];
  if(!queries.length)return root.append(empty("No rank runs yet","Add a query, preview a capture in your terminal, then use --spend. Bing also accepts browser imports below."));
  const q=queries.includes(state.query)?state.query:queries[0];
  const bar=el("div",undefined,"toolbar");bar.append(field("Query",select(queries.map(x=>[x,x]),q,v=>navigate({query:v}))),field("Market",select([['us','United States'],['uk','United Kingdom'],['au','Australia']],state.market,v=>navigate({market:v}))),field("Engine",select([['google','Google'],['bing','Bing']],state.engine,v=>navigate({engine:v}))));root.append(bar);
  const runs=historyFor(q,state.market,state.engine),r=runs.at(-1),prev=runs.at(-2);
  if(state.engine==="bing")root.append(el("p",dataset.derived.bing_warning,"warning"));
  if(!r)root.append(empty("No run in this market","Try another market or capture this query with the CLI."));
  else {
    const panel=el("div",undefined,"panel");panel.append(el("h2",`${r.top10_yours} of the top 10 are yours`),el("p",r.best_rank===null?"Your pages were not found in this saved sample.":`Best owned rank: #${r.best_rank}`),chip(r),document.createTextNode(" "),time(r.at));root.append(panel);
    const cp=el("div",undefined,"panel chart-panel");cp.append(el("h2","Best rank history"),chart(runs),el("p","Rank 1 is highest. A gap means no owned page in that sample. Dates and ranks are in the chart tooltip.","hint"));root.append(cp);
    const owned=new Set(dataset.derived.pages.filter(p=>p.mine).map(p=>identity(p.url)));
    root.append(table(["Rank","Page","URL","Change","Ownership","Source","Captured UTC"],r.results.map(row=>{
      const before=prev?.results.find(x=>identity(x.url)===identity(row.url));const change=before?before.rank-row.rank:null;
      return {mine:owned.has(identity(row.url)),cells:[row.rank,link(row.url,row.title),link(row.url,row.url),change===null?"No previous match":change===0?"Unchanged":change>0?"Up "+change:"Down "+Math.abs(change),owned.has(identity(row.url))?"Yours":"Other",chip(r),time(r.at)]};
    }),"Rank results"));
    if(!r.results.length)root.append(empty("No organic results returned","This is a saved empty sample. It does not establish that your pages are unindexed."));
  }
  if(state.engine==="bing")root.append(importPanel(false));
}
function identity(url) {return url.replace(/^https?:\/\//,"").replace(/\/*(?=[?#]|$)/,"");}
function indexation(root) {
  const bar=el("div",undefined,"toolbar"),search=el("input");search.type="search";search.placeholder="Name, URL or group";search.value=state.search;
  search.oninput=()=>{navigate({search:search.value},true);draw();};
  bar.append(field("Show pages",select([['all','All'],['google','Not in Google'],['bing','Not in Bing'],['unknown','Unknown']],state.filter,v=>navigate({filter:v}))),field("Search",search));root.append(bar);
  root.append(el("p","Not in engine filters include unknown pages. Google inspection is only for your verified properties; other pages stay Unknown unless seen in a saved rank run.","hint"));
  const dest=el("div");root.append(dest);
  function draw() {
    let rows=dataset.derived.pages.filter(p=>(p.name+" "+p.url+" "+p.group).toLowerCase().includes(state.search.toLowerCase()));
    rows=rows.filter(p=>state.filter==="google"?p.engines.google.indexed!==true:state.filter==="bing"?p.engines.bing.indexed!==true:state.filter==="unknown"?Object.values(p.engines).some(r=>r.indexed===null):true);
    const get=(p,k)=>k==="page"?(p.name||p.url):k==="group"?p.group:k==="google"||k==="bing"?(p.engines[k].indexed===true?"Indexed":p.engines[k].indexed===false?"Not indexed":"Unknown"):k==="first"?Object.values(p.engines).map(r=>r.first_indexed).filter(Boolean).sort()[0]||"":k==="last"?Object.values(p.engines).map(r=>r.at).filter(Boolean).sort().at(-1)||"":p.engines.google.provider;
    rows.sort((a,b)=>String(get(a,state.sort)).localeCompare(String(get(b,state.sort)))*(state.desc?-1:1));
    dest.replaceChildren();
    dest.append(el("p",`${rows.length} pages shown. Highlighted rows are yours. Source and time are attached to each engine reading.` ,"hint"));
    if(!rows.length)return dest.append(empty("No matching pages","Clear filters or add pages using the CLI."));
    dest.append(table(["Page","Group","Google status, source and time","Bing status, source and time","First indexed UTC","Last checked UTC","Source"],rows.map(p=>({mine:p.mine,cells:[link(p.url,p.name||p.url),p.group,reading(p.engines.google),reading(p.engines.bing),time(get(p,"first")),time(get(p,"last")),[p.engines.google.provider,p.engines.bing.provider].join(" / ")]})),"Indexation",["page","group","google","bing","first","last","source"]));
  }draw();
}
function importPanel(queue, item) {
  const panel=el("div",undefined,"panel chart-panel"),input=el("textarea"),result=el("p","","hint"),button=el("button","Import browser reading");
  input.setAttribute("aria-label","Bing snippet JSON");input.placeholder='Paste the JSON copied by the Bing snippet';
  result.setAttribute("role","status");result.setAttribute("aria-live","polite");
  button.type="button";button.disabled=state.source!=="mine";input.disabled=state.source!=="mine";
  panel.append(el("h2","Paste a Bing reading"),el("p",state.source==="demo"?"Demo is read-only. Choose My data to paste a browser reading.":(queue?"Run the snippet on the queue search you opened, then paste its JSON here.":"Paste results for a configured query and market to import a rank run. Use the queue for page index checks.")+" Ctrl+Enter imports.","hint"),input,button,result);
  const submit=async()=>{
    if(state.source!=="mine")return;
    button.disabled=true;result.textContent="Checking import...";
    try {
      const raw=JSON.parse(input.value);
      if(queue&&item){raw.target_url=item.url;raw.title_query=editedTitles.get(item.url)||item.title_query;}else raw.kind='rank';
      const response=await fetch("/api/import-reading?source=mine",{method:"POST",headers:{"Content-Type":"application/json","X-Import-Token":document.querySelector('meta[name="import-token"]').content},body:JSON.stringify(raw)});
      const data=await response.json();if(!response.ok)throw new Error(data.error);
      if(queue&&item){visited.add(item.url);const list=dataset.derived.bing_queue;const i=list.findIndex(p=>p.url===item.url);queueURL=list[(i+1)%list.length]?.url||"";}
      $("load-status").textContent=data.message + ". Saved locally.";
      await load(true); if(queue)$("queue-paste")?.focus();
    }catch(e){result.textContent=e.message||"Import failed";button.disabled=false;}
  };
  button.onclick=submit;input.onkeydown=e=>{if(e.ctrlKey&&e.key==="Enter"){e.preventDefault();if(!button.disabled)submit();}};
  if(queue)input.id="queue-paste";
  return panel;
}
function bookmarkPanel() {
  const p=el("div",undefined,"panel");p.append(el("h2","Install the read-only Bing snippet"),el("p","Drag the link to your bookmarks bar. On an English Bing results page, click the bookmark and allow copying. If your browser blocks bookmarklets, open the snippet file and paste its contents into your browser console after reviewing it. It reads the current page, makes no requests and automates no searches.","hint"));
  const a=el("a","Copy visible Bing results");if(snippet)a.href="javascript:"+encodeURIComponent(snippet);else a.textContent="Loading snippet...";a.title="Drag to bookmarks bar, then use on a Bing search page";
  // A bookmarklet is intentionally offered as text to install; this dashboard's CSP blocks running it here.
  p.append(a,document.createTextNode(" · "),link(location.origin+"/bing-snippet.js","Read snippet source"));return p;
}
function queue(root) {
  root.append(el("p","The authors found no Bing API that reliably answers whether this exact URL is indexed. In tests on 8 November 2026, url: and site: gave false negatives. What worked: a signed-in browser, the page title first, then url:.","warning"));
  const d=dataset.derived,items=d.bing_queue;
  const checked=d.pages.filter(p=>p.engines.bing.indexed===true||p.engines.bing.provider==="browser-import"||visited.has(p.url)).length;
  const progress=el("div",undefined,"progress"),meter=el("progress");meter.max=Math.max(1,d.pages.length);meter.value=checked;meter.setAttribute("aria-label","Pages with Bing evidence or a browser check");
  progress.append(el("h2",`${checked} of ${d.pages.length} checked`),meter,el("p","Checked includes inconclusive attempts. Only Indexed confirms a page. The queue advances after each paste; revisit pending pages to finish the other search on the same UTC day and market.","hint"));root.append(progress,bookmarkPanel());
  if(!items.length)return root.append(empty("No Bing checks waiting",d.pages.length?"Every tracked page has current positive Bing evidence.":"Add pages in the CLI, then choose My data and Reload data."));
  let item=items.find(p=>p.url===queueURL)||items[0];queueURL=item.url;
  const selector=select(items.map(p=>[p.url,(p.name||p.url)+" · "+p.status]),item.url,v=>{queueURL=v;render();});
  root.append(field("Page to check",selector));
  const panel=el("div",undefined,"panel chart-panel"),title=el("input");title.value=editedTitles.get(item.url)||item.title_query;title.className="queue-title";
  const links=el("div",undefined,"actions");
  const update=()=>{editedTitles.set(item.url,title.value);links.replaceChildren(link("https://www.bing.com/search?"+new URLSearchParams({q:title.value,cc:state.market}),"1. Search page title"),link("https://www.bing.com/search?"+new URLSearchParams({q:"url:"+item.url,cc:state.market}),"2. Search exact URL"));};title.oninput=update;update();
  panel.append(el("h2",item.name||"Page to check"),link(item.url,item.url),field("Page title to search (editable)",title),field("Browser search market",select([['us','United States'],['uk','United Kingdom'],['au','Australia']],state.market,v=>navigate({market:v}))),links,el("p",item.note||"Open the title search first. A matching URL confirms indexation. Otherwise check the URL search too.","hint"));
  panel.append(reading(item));
  root.append(panel,importPanel(true,item));
  const list=el("div",undefined,"queue-list");list.append(table(["Page","Title search","URL search","State, source and time"],items.map(p=>({cells:[link(p.url,p.name||p.url),link(p.title_link,"Search title"),link(p.url_link,"Search URL"),reading(p)]})),"Bing check queue"));root.append(list);
}
function historyView(root) {
  const bar=el("div",undefined,"toolbar");bar.append(field("Engine",select([['all','All engines'],['google','Google'],['bing','Bing']],state.filter,v=>navigate({filter:v}))),field("Record type",select([['all','All records'],['rank','Rank runs'],['index','Index readings']],['rank','index'].includes(state.query)?state.query:'all',v=>navigate({query:v}))));root.append(bar);
  let rows=[...dataset.rank_runs.map(r=>({...r,kind:'rank'})),...dataset.index_readings.map(r=>({...r,kind:'index'}))];
  rows=rows.filter(r=>(!["google","bing"].includes(state.filter)||r.engine===state.filter)&&(!['rank','index'].includes(state.query)||r.kind===state.query)).sort((a,b)=>Date.parse(b.at)-Date.parse(a.at));
  if(!rows.length)return root.append(empty("No history in this view","Try another filter or save your first reading."));
  root.append(table(["Captured UTC","Type","Engine","Query or page","Reading","Source","Charge USD","Note"],rows.map(r=>({cells:[time(r.at),r.kind,r.engine,r.kind==='rank'?r.query+' · '+r.market:link(r.url,r.url),r.kind==='rank'?r.results.length+' organic results':status(r),chip(r),r.provider_cost_usd==null?"Not reported":r.provider_cost_usd.toFixed(6),r.note||"None"]})),"Saved history"));
}
function exportView(root) {
  const actions=el("div",undefined,"actions");['json','csv'].forEach(fmt=>{const a=el("a","Download "+fmt.toUpperCase());a.href='/api/export?'+new URLSearchParams({source:state.source,format:fmt});a.download='rank-index-tracker.'+fmt;actions.append(a);});root.append(el("h2","Take your evidence with you"),el("p",`Exporting ${state.source==='demo'?'invented demo data':'your saved local data'}. Exports spend nothing. JSON preserves the full dataset; CSV includes rank results, index history and current derived statuses.`),actions);
  const panel=el("div",undefined,"panel chart-panel");panel.append(el("h2","What the evidence means"));
  ["Indexed: a saved inspection passed, a browser result matched the exact URL, or the page appeared in a saved rank run. Source and UTC time travel with every reading.","Not indexed: a Search Console verdict other than PASS. Not found in Bing: at least 3 title results without your URL, plus an explicit no-results URL search, without another page of results.","Unknown: no evidence, an error, challenge, mismatch or an incomplete pair. Missing rank results and unrelated search results never prove non-indexation.","First indexed is the first positive observation in this file, not the date the search engine originally indexed the page. Newer unknown readings can replace older conclusions.","Bing API ranks are unverified even when the cheap keyword and result-count sanity checks pass. Suspect runs stay in history but do not confirm indexation."].forEach(t=>panel.append(el("p",t)));root.append(panel);
  root.append(el("h2","Track your own pages"),el("p","Use a terminal in this folder. Credentials are environment variables only. No credentials are accepted by this page."));
  root.append(el("pre",'python3 tracker.py add-page https://example.com/trail-pack --name "Trail pack"\npython3 tracker.py add-query "light trail packs" --market us,uk\npython3 tracker.py rank --engine google\n# Preview above. Add --spend only when ready.\npython3 tracker.py index --engine google --site-url sc-domain:example.com\n# Free quota-limited preview. Add --run to inspect owned URLs.'));
  root.append(el("p","DataForSEO rank estimates start at USD 0.002 per query and market at depth 10. Depth 20 and 30 estimates are USD 0.004 and 0.006. No retries or schedules. Search Console is free and limited to verified properties. Read README.md for environment variables, current documentation, quota and troubleshooting.","hint"),el("p","Live provider paths were implemented against the linked documentation and tested with fixtures. They have not been run end to end in this edition. Tested on Linux only.","warning"),bookmarkPanel(),importPanel(false));
}
function render() {
  if(!dataset)return;
  $("content").replaceChildren();$("view-title").textContent=views[state.view];document.title=views[state.view]+" · Rank and Index Tracker";
  document.querySelectorAll('nav a').forEach(a=>{a.removeAttribute('aria-current');if(a.dataset.view===state.view)a.setAttribute('aria-current','page');a.href='#'+a.dataset.view+'?source='+state.source;});
  $("mode-banner").textContent=state.source==='demo'?'SYNTHETIC DEMO · '+dataset.notice:'MY DATA · Local file. Only browser imports write from this dashboard.';
  if(!dataset.pages.length&&state.view!=='export')$("content").append(empty("Start with your pages","Add pages and queries in the CLI, then Reload data. Google inspection only works for properties you have verified. Other pages stay Unknown unless seen in a saved rank run."));
  ({overview,rankings,indexation,queue,history:historyView,export:exportView})[state.view]($("content"));
}
async function load(preserveStatus=false) {
  const id=++requestId;dataset=null;$("content").replaceChildren();$("mode-banner").textContent=state.source==='demo'?'SYNTHETIC DEMO · Loading invented data':'MY DATA · Loading local data';$("error").hidden=true;if(!preserveStatus)$("load-status").textContent='Loading '+(state.source==='demo'?'synthetic demo':'your local data')+'...';
  try {
    const response=await fetch('/api/data?source='+state.source);const data=await response.json();if(!response.ok)throw new Error(data.error);if(id!==requestId)return;dataset=data;render();
    if(!preserveStatus)$("load-status").textContent=`${data.pages.length} pages · ${data.rank_runs.length} rank runs · ${data.index_readings.length} index readings. Viewing saved data spends nothing.`;
  }catch(e){if(id!==requestId)return;dataset=null;$("content").replaceChildren();$("error").hidden=false;$("error").textContent=e.message;$("load-status").textContent='Data could not be loaded. Correct the local JSON or restore a valid backup, then Reload data.';}
}
$("source").onchange=()=>{queueURL='';visited.clear();navigate({source:$("source").value});};
$("reload").onclick=()=>load();
window.addEventListener('hashchange',()=>{const source=state.source;readState();if(source!==state.source)load();else render();});
readState();load();
fetch('/bing-snippet.js').then(r=>r.text()).then(s=>{snippet=s;if(state.view==='queue'||state.view==='export')render();}).catch(()=>{$("error").hidden=false;$("error").textContent='Cannot load the Bing snippet. Reload to try again.';});
