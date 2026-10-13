const $=id=>document.getElementById(id);let lastId=null;
async function api(url,options={}){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.detail||"Request failed");return data}
async function start(){try{const data=await api("/demo/start",{method:"POST"});$("controls").hidden=false;$("message").textContent=data.message}catch(e){$("message").textContent=e.message}}
async function create(){try{const data=await api("/demo/sessions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({duration_seconds:30})});lastId=data.id;$("output").textContent=JSON.stringify(data,null,2)}catch(e){$("message").textContent=e.message}}
async function expire(){if(!lastId)return;$("output").textContent=JSON.stringify(await api(`/demo/sessions/${lastId}/expire`,{method:"POST"}),null,2)}
async function revoke(){if(!lastId)return;$("output").textContent=JSON.stringify(await api(`/sessions/${lastId}/revoke`,{method:"POST"}),null,2)}
$("start").onclick=start;$("create").onclick=create;$("expire").onclick=expire;$("revoke").onclick=revoke;
