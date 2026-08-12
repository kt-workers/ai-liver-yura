const svg = document.getElementById('graph');
const viewport = document.getElementById('viewport');
const lanesLayer = document.getElementById('lanes');
const edgesLayer = document.getElementById('edges');
const nodesLayer = document.getElementById('nodes');
const loading = document.getElementById('loading');
const categoryFilter = document.getElementById('categoryFilter');
const searchInput = document.getElementById('search');

const COLORS = {bootstrap:'#6f76d9',runtime:'#3c78d8',core:'#2f9eaa',domain:'#4b9a6b',service:'#3d9b88',port:'#6f8da8',plugin:'#9a6ec5',subsystem:'#875bb4',adapter:'#cc8544',integration:'#c36b66',infrastructure:'#768493',config:'#a78a45',admin:'#c45f82',gui:'#5a8fd0',validation:'#8c7bb7',prompting:'#7b68a8',diagnostics:'#88939f',other:'#7f8a98'};
const CATEGORY_ORDER = ['bootstrap','runtime','core','service','domain','port','plugin','subsystem','adapter','integration','infrastructure','config','prompting','diagnostics','admin','gui','validation','other'];
let graphData = {nodes:[],edges:[]}; let positions = new Map(); let selectedId = null; let scale = 1; let translate = {x:30,y:30}; let dragging = false; let lastPointer = null;

const el = (name, attrs={}) => { const node=document.createElementNS('http://www.w3.org/2000/svg',name); Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v)); return node; };
const htmlEscape = value => String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const categoryColor = category => COLORS[category] || COLORS.other;
const visibleNodes = () => { const category=categoryFilter.value; return graphData.nodes.filter(n=>category==='all'||n.category===category); };

function layout(nodes){
  const byCategory=new Map(); nodes.forEach(node=>{if(!byCategory.has(node.category))byCategory.set(node.category,[]);byCategory.get(node.category).push(node);});
  const categories=[...byCategory.keys()].sort((a,b)=>{const ai=CATEGORY_ORDER.indexOf(a),bi=CATEGORY_ORDER.indexOf(b);return(ai<0?999:ai)-(bi<0?999:bi)||a.localeCompare(b);});
  positions=new Map(); const laneWidth=230,nodeWidth=190,nodeHeight=66,rowGap=28,laneGap=34,top=72; const lanes=[];
  categories.forEach((category,column)=>{const list=byCategory.get(category).sort((a,b)=>a.label.localeCompare(b.label));const x=36+column*(laneWidth+laneGap);list.forEach((node,row)=>positions.set(node.id,{x:x+20,y:top+36+row*(nodeHeight+rowGap),w:nodeWidth,h:nodeHeight}));lanes.push({category,x,y:top,w:laneWidth,h:Math.max(160,70+list.length*(nodeHeight+rowGap))});});
  return {lanes};
}

function edgePath(source,target,index){
  const sxCenter=source.x+source.w/2,syCenter=source.y+source.h/2,txCenter=target.x+target.w/2,tyCenter=target.y+target.h/2;
  if(Math.abs(txCenter-sxCenter)<30){const offset=45+(index%4)*16,sideX=source.x+source.w+offset;return `M ${source.x+source.w} ${syCenter} C ${sideX} ${syCenter}, ${sideX} ${tyCenter}, ${target.x+target.w} ${tyCenter}`;}
  const toRight=txCenter>sxCenter,sx=toRight?source.x+source.w:source.x,tx=toRight?target.x:target.x+target.w,dx=Math.max(45,Math.abs(tx-sx)*.46),c1=sx+(toRight?dx:-dx),c2=tx-(toRight?dx:-dx);
  return `M ${sx} ${syCenter} C ${c1} ${syCenter}, ${c2} ${tyCenter}, ${tx} ${tyCenter}`;
}

function render(){
  lanesLayer.replaceChildren();edgesLayer.replaceChildren();nodesLayer.replaceChildren(); const nodes=visibleNodes(),visible=new Set(nodes.map(n=>n.id)),dimensions=layout(nodes);
  dimensions.lanes.forEach(lane=>{const g=el('g',{class:'lane'}),rect=el('rect',{x:lane.x,y:lane.y,width:lane.w,height:lane.h}),title=el('text',{x:lane.x+16,y:lane.y+24});rect.setAttribute('stroke',categoryColor(lane.category)+'55');title.textContent=lane.category;title.setAttribute('fill',categoryColor(lane.category));g.append(rect,title);lanesLayer.appendChild(g);});
  graphData.edges.filter(e=>visible.has(e.source)&&visible.has(e.target)).forEach((edge,index)=>{const source=positions.get(edge.source),target=positions.get(edge.target),path=el('path',{d:edgePath(source,target,index),class:'edge','data-source':edge.source,'data-target':edge.target});edgesLayer.appendChild(path);if(edge.weight>1){const label=el('text',{class:'edge-weight',x:(source.x+target.x+source.w)/2,y:(source.y+target.y+source.h)/2});label.textContent=`×${edge.weight}`;edgesLayer.appendChild(label);}});
  nodes.forEach(node=>{const p=positions.get(node.id),color=categoryColor(node.category),g=el('g',{class:'node',transform:`translate(${p.x} ${p.y})`,'data-id':node.id,tabindex:'0'}),card=el('rect',{class:'card',width:p.w,height:p.h}),stripe=el('rect',{x:0,y:0,width:5,height:p.h,rx:3,fill:color}),title=el('text',{class:'node-title',x:16,y:27}),meta=el('text',{class:'node-meta',x:16,y:47}),badge=el('text',{class:'node-badge',x:p.w-12,y:18,'text-anchor':'end'});card.setAttribute('stroke',color+'aa');title.textContent=node.label;meta.textContent=`${node.file_count} files · ${node.incoming_count} in · ${node.outgoing_count} out`;badge.textContent=node.category;badge.setAttribute('fill',color);g.append(card,stripe,title,meta,badge);g.addEventListener('click',evt=>{evt.stopPropagation();selectNode(node.id);});g.addEventListener('keydown',evt=>{if(evt.key==='Enter'||evt.key===' ')selectNode(node.id);});nodesLayer.appendChild(g);});
  applySearchAndSelection();updateSummary(nodes.length,graphData.edges.filter(e=>visible.has(e.source)&&visible.has(e.target)).length);if(selectedId&&!visible.has(selectedId))clearSelection();
}

function applySearchAndSelection(){
  const query=searchInput.value.trim().toLowerCase();document.querySelectorAll('.node').forEach(nodeEl=>{const id=nodeEl.dataset.id,data=graphData.nodes.find(n=>n.id===id),match=!query||`${data.id} ${data.path} ${data.label}`.toLowerCase().includes(query);nodeEl.classList.toggle('dimmed',!!query&&!match);nodeEl.classList.toggle('search-match',!!query&&match);nodeEl.classList.toggle('selected',id===selectedId);});
  document.querySelectorAll('.edge').forEach(edgeEl=>{const related=selectedId&&(edgeEl.dataset.source===selectedId||edgeEl.dataset.target===selectedId);edgeEl.classList.toggle('related',!!related);edgeEl.classList.toggle('incoming',related&&edgeEl.dataset.target===selectedId);edgeEl.classList.toggle('dimmed',!!selectedId&&!related);});
}

function relationItems(ids){if(!ids.length)return '<div class="file-item">なし</div>';return ids.map(id=>{const n=graphData.nodes.find(node=>node.id===id);return `<button class="relation-item" data-node-id="${htmlEscape(id)}"><b>${htmlEscape(n?.label||id)}</b><span>${htmlEscape(n?.category||'')}</span></button>`;}).join('');}
function selectNode(id){
  selectedId=id;applySearchAndSelection();const node=graphData.nodes.find(n=>n.id===id);if(!node)return;const incoming=graphData.edges.filter(e=>e.target===id).map(e=>e.source).sort(),outgoing=graphData.edges.filter(e=>e.source===id).map(e=>e.target).sort();
  document.getElementById('emptyDetail').hidden=true;document.getElementById('detail').hidden=false;document.getElementById('detailCategory').textContent=node.category;document.getElementById('detailLabel').textContent=node.label;document.getElementById('detailId').textContent=node.id;document.getElementById('detailPath').textContent=node.path;document.getElementById('detailFilesCount').textContent=node.file_count;document.getElementById('detailIncomingCount').textContent=incoming.length;document.getElementById('detailOutgoingCount').textContent=outgoing.length;document.getElementById('outgoingList').innerHTML=relationItems(outgoing);document.getElementById('incomingList').innerHTML=relationItems(incoming);document.getElementById('fileList').innerHTML=node.files.map(file=>`<div class="file-item">${htmlEscape(file)}</div>`).join('');document.querySelectorAll('[data-node-id]').forEach(button=>button.addEventListener('click',()=>selectNode(button.dataset.nodeId)));
}
function clearSelection(){selectedId=null;applySearchAndSelection();document.getElementById('emptyDetail').hidden=false;document.getElementById('detail').hidden=true;}
function updateSummary(nodeCount,edgeCount){document.getElementById('summary').innerHTML=`<div class="metric"><strong>${nodeCount}</strong><span>modules</span></div><div class="metric"><strong>${edgeCount}</strong><span>dependencies</span></div>`;}
function populateFilters(){const categories=[...new Set(graphData.nodes.map(n=>n.category))].sort();categoryFilter.innerHTML='<option value="all">すべて</option>'+categories.map(c=>`<option value="${htmlEscape(c)}">${htmlEscape(c)}</option>`).join('');document.getElementById('legend').innerHTML=categories.map(c=>`<div class="legend-item"><span class="legend-dot" style="background:${categoryColor(c)}"></span>${htmlEscape(c)}</div>`).join('');}
function applyTransform(){viewport.setAttribute('transform',`translate(${translate.x} ${translate.y}) scale(${scale})`);}
function fitViewport(minScale=0){const bounds=viewport.getBBox();if(!bounds.width||!bounds.height)return;const rect=svg.getBoundingClientRect(),pad=55,fitScale=Math.min((rect.width-pad*2)/bounds.width,(rect.height-pad*2)/bounds.height,1.2);scale=Math.max(minScale,fitScale);translate.x=(rect.width-bounds.width*scale)/2-bounds.x*scale;translate.y=(rect.height-bounds.height*scale)/2-bounds.y*scale;applyTransform();}
function fitToView(){fitViewport(0);}
function fitReadableView(){fitViewport(.45);}
async function loadGraph(){loading.hidden=false;try{const response=await fetch('/api/graph',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);graphData=await response.json();populateFilters();render();document.getElementById('generatedAt').textContent=`解析: ${new Date(graphData.generated_at).toLocaleString()} · diagnostics ${graphData.diagnostics?.length||0}`;requestAnimationFrame(fitReadableView);}catch(error){document.getElementById('generatedAt').textContent=`読み込み失敗: ${error.message}`;}finally{loading.hidden=true;}}
searchInput.addEventListener('input',applySearchAndSelection);categoryFilter.addEventListener('change',()=>{render();requestAnimationFrame(fitReadableView);});document.getElementById('fitButton').addEventListener('click',fitToView);document.getElementById('reloadButton').addEventListener('click',loadGraph);document.getElementById('closeDetail').addEventListener('click',clearSelection);svg.addEventListener('click',clearSelection);
svg.addEventListener('wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect(),px=event.clientX-rect.left,py=event.clientY-rect.top,beforeX=(px-translate.x)/scale,beforeY=(py-translate.y)/scale,factor=event.deltaY<0?1.12:.89;scale=Math.max(.18,Math.min(2.6,scale*factor));translate.x=px-beforeX*scale;translate.y=py-beforeY*scale;applyTransform();},{passive:false});
svg.addEventListener('pointerdown',event=>{if(event.target.closest?.('.node'))return;dragging=true;lastPointer={x:event.clientX,y:event.clientY};svg.setPointerCapture(event.pointerId);});svg.addEventListener('pointermove',event=>{if(!dragging)return;translate.x+=event.clientX-lastPointer.x;translate.y+=event.clientY-lastPointer.y;lastPointer={x:event.clientX,y:event.clientY};applyTransform();});svg.addEventListener('pointerup',()=>{dragging=false;lastPointer=null;});window.addEventListener('resize',()=>requestAnimationFrame(fitReadableView));loadGraph();
