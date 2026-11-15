import {stations,demoFrameAt,demoDuration,dock,belts,spurs,parking,robotRoads,createSimulation,setRecords,tick,snapshotOf,magazineAt,pressAt} from './factory-floor-model.mjs';
const canvas=document.getElementById('factory-floor');
const ctx=canvas.getContext('2d');
const play=document.getElementById('floor-play'), seek=document.getElementById('floor-time');
const picker=document.getElementById('floor-station');
let time=0, playing=false, previous=0, selected='A';
let mode='live', snapshot=null, liveSimulation=createSimulation();
let magazineCycle=null,pressCycle=null,drillCycle=null,measureCycle=null;
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
seek.max=demoDuration;
const colors={unknown:'#78519a',error:'#b42332',raw:'#087cb9',wip:'#b96710',finished:'#23834f'};
function box(x,y,w,h,fill,stroke){ctx.fillStyle=fill;ctx.fillRect(x,y,w,h);if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.strokeRect(x,y,w,h);}}
function text(value,x,y,size=14,color='#233d4c',align='center'){ctx.fillStyle=color;ctx.font=`${size>=18?'600 ':''}${size}px "Microsoft JhengHei", sans-serif`;ctx.textAlign=align;ctx.fillText(value,x,y);}
function line(points,color,width,dash=[]){ctx.beginPath();ctx.moveTo(...points[0]);points.slice(1).forEach(p=>ctx.lineTo(...p));if(points.length>2&&points[0][0]===points.at(-1)[0]&&points[0][1]===points.at(-1)[1])ctx.closePath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin='round';ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);}
function circle(x,y,r,color){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
function belt(points){line(points,'#889ca8',48);line(points,'#e3eaf0',42);line(points,'#394b57',30);line(points,'#a7bac5',2,[3,10]);}
function arm(x,y,active){const a=active?Math.sin(time*2)*.35:0;line([[x,y+20],[x-25,y-10],[x+15+Math.sin(a)*25,y-35]],'#627d8b',15);line([[x,y+20],[x-25,y-10],[x+15+Math.sin(a)*25,y-35]],'#e1eaf0',9);circle(x,y+20,12,'#0079bc');circle(x-25,y-10,8,'#0079bc');box(x+8+Math.sin(a)*25,y-40,18,8,'#233d4c');}
function machine(s,active,progress=0){
  const {x,y,kind}=s; const w=kind==='rack'?160:130,h=kind==='rack'?140:112;
  box(x-w/2+5,y-h/2+7,w,h,'#b6c7d0');
  box(x-w/2,y-h/2,w,h,selected===s.id?'#d6edf8':'#f5f8fa',selected===s.id?'#006eaf':'#8ea4b1');
  box(x-w/2,y-h/2,w,9,'#007bb9');
  circle(x+w/2-12,y-h/2+22,5,active?'#29ab68':'#9aaeb8');
  if(kind==='rack'){
    for(let r=0;r<4;r++)for(let c=0;c<8;c++)box(x-67+c*17,y-48+r*22,13,17,(r+c)%3?'#304c5e':'#8ec7e2');
    line([[x,y-53],[x,y+42]],'#8c9faa',5);box(x-15,y-10+(active?Math.sin(time)*20:0),30,18,'#f0b83f');
    text('A1 / A2 均可放入、取出',x,y+60,12);
  }else if(kind==='robot'){arm(x,y,active||(mode==='demo'&&s.id==='P'));}
  else if(kind==='magazine'){
    const motion=magazineAt(progress);
    for(let i=0;i<(active?3:4);i++)box(x-35,y-28+i*14+(active?motion.shift*14:0),70,10,'#8299a5','#4d6573');
    if(active&&motion.refill>0)box(x-35,y-48+motion.refill*20,70,10,'#58a7ce','#285b75');
    if(active)line([[x-20,y+32],[x-20,dock.F[1]-16]],'#9bb0bd',2);
  }
  else if(kind==='oven'){box(x-46,y-33,92,65,'#becbd2','#6d8593');box(x-30,y-19,60,38,active?'#edaf53':'#475d69');for(let i=0;i<5;i++)line([[x-22+i*11,y-10],[x-22+i*11,y+10]],'#ecce85',3);}
  else{
    box(x-45,y-34,8,70,'#9bb0bd');box(x+37,y-34,8,70,'#9bb0bd');box(x-45,y-34,90,12,'#6c8695');box(x-30,y+23,60,12,'#567384');
    const offset=active?pressAt(progress)*(kind==='measure'?8:14):0;
    if(kind==='camera'){box(x-22,y-19,44,28,'#243b4a');circle(x,y-5,9,'#65badb');line([[x-20,y+26],[x+20,y+26]],'#d64740',2);}
    else if(kind==='measure'){line([[x-30,y+offset],[x+30,y+offset]],'#007cb8',4);line([[x-30,y-10+offset],[x-30,y+12+offset]],'#007cb8',3);line([[x+30,y-10+offset],[x+30,y+12+offset]],'#007cb8',3);}
    else {box(x-10,y-22,20,28+offset,'#7e95a2');box(x-(kind==='press'?27:3),y+6+offset,kind==='press'?54:6,10,'#283f4d');}
  }
  text(`${s.id==='P'?'新站':s.id}  ${s.name}`,kind==='magazine'?x-100:x,y+h/2+18,17);text(active?(kind==='press'&&progress>=.8?'壓製完成':kind==='drill'&&progress>=.8?'鑽孔完成':kind==='measure'&&progress>=.8?'量測完成':'加工中'):mode==='live'?'無加工紀錄':s.id==='P'?'示範站':'待機',x,kind==='magazine'?y+45:y-h/2+25,12,active?'#166c40':'#526875');
}
function pallet(x,y,id,stage){box(x-16,y-12,32,24,'#f6f9fb','#627985');box(x-11,y-8,22,16,colors[stage]);text(id,x,y+4,10,'white');}
function render(){
  ctx.clearRect(0,0,1200,780);box(0,0,1200,780,'#e5edf1');
  box(30,25,1140,710,'#edf3f5','#cedbe1');
  text('FESTO CP FACTORY',60,60,18,'#45616f','left');text(mode==='live'?'訂單進度同步':'2D 流程示範',1140,60,14,'#45616f','right');
  belts.forEach(belt);
  spurs.forEach(belt);
  line([[450,350],[690,350],[690,570],[450,570],[450,350]],'#869ba7',3,[8,8]);
  robotRoads.forEach(path=>line(path,'#869ba7',2,[6,6]));
  // Conveyor arrows follow the exact directed centerlines used by the simulator.
  for(const path of [...belts,...spurs])for(let i=1;i<path.length;i++){
    const a=path[i-1],b=path[i],length=Math.hypot(b[0]-a[0],b[1]-a[1]);if(length<35)continue;
    const x=(a[0]+b[0])/2,y=(a[1]+b[1])/2,dx=(b[0]-a[0])/length,dy=(b[1]-a[1])/length;
    line([[x-dx*5-dy*4,y-dy*5+dx*4],[x+dx*5,y+dy*5],[x-dx*5+dy*4,y-dy*5-dx*4]],'#fff',2);
  }
  text('R1 / R2 搬運區',555,425,21);text('共用路段互鎖・到站後交接',555,453,14,'#526875');
  text('左：輸出到 R　右：由 R 送入',550,480,13,'#526875');
  text('E 輸出',710,330,12,'#233d4c','right');text('E 送入',830,330,12,'#233d4c','left');
  text('B 輸出到 R',865,525,12);text('B 送入輸送帶',865,613,12);
  parking.forEach((home,i)=>{box(home[0]-33,home[1]-33,66,66,'#e2ebef','#9fb3bf');text(`R${i+1} 休息位`,home[0],home[1]+50,12);});
  text('休息區：B 與新站之間',795,727,14);
  const scene=mode==='live'?snapshotOf(liveSimulation):demoFrameAt(time),pieces=scene.pieces;
  const magazinePiece=pieces.find(p=>p.position&&p.station==='F'&&p.phase==='processing'&&(mode==='demo'||p.state==='running'));
  if(!magazinePiece)magazineCycle=null;
  else if(magazineCycle?.id!==magazinePiece.id)magazineCycle={id:magazinePiece.id,start:time};
  const magazineProgress=reducedMotion.matches?1:mode==='demo'?(magazinePiece?.progress||0):Math.min(1,(time-(magazineCycle?.start??time))/4);
  const pressPiece=pieces.find(p=>p.position&&p.station==='G'&&p.phase==='processing');
  if(!pressPiece)pressCycle=null;
  else if((mode==='demo'||pressPiece.state==='running')&&pressCycle?.id!==pressPiece.id)pressCycle={id:pressPiece.id,start:time};
  const pressProgress=reducedMotion.matches?1:mode==='demo'?(pressPiece?.progress||0):Math.min(1,(time-(pressCycle?.start??time))/4);
  const drillPiece=pieces.find(p=>p.position&&p.station==='C'&&p.phase==='processing');
  if(!drillPiece)drillCycle=null;
  else if((mode==='demo'||drillPiece.state==='running')&&drillCycle?.id!==drillPiece.id)drillCycle={id:drillPiece.id,start:time};
  const drillProgress=reducedMotion.matches?1:mode==='demo'?(drillPiece?.progress||0):Math.min(1,(time-(drillCycle?.start??time))/4);
  const measurePiece=pieces.find(p=>p.position&&p.station==='B'&&p.phase==='processing');
  if(!measurePiece)measureCycle=null;
  else if((mode==='demo'||measurePiece.state==='running')&&measureCycle?.id!==measurePiece.id)measureCycle={id:measurePiece.id,start:time};
  const measureProgress=reducedMotion.matches?1:mode==='demo'?(measurePiece?.progress||0):Math.min(1,(time-(measureCycle?.start??time))/4);
  text('A2 放入／取出',630,218,12);text('A1 放入／取出',610,310,12);
  stations.forEach(s=>machine(s,pieces.some(p=>p.position&&p.phase==='processing'&&(mode==='demo'||p.state==='running')&&(p.station===s.id||(s.id==='A'&&p.station?.startsWith('A')))),s.id==='F'?magazineProgress:s.id==='G'?pressProgress:s.id==='C'?drillProgress:s.id==='B'?measureProgress:0));
  const robotLabels={idle:'休息',pickup:'前往接貨',loading:'靠站裝載',loaded:'載貨搬運',unloading:'靠站卸貨',return:'返回休息位'};
  for(const robot of scene.robots){
    const [rx,ry]=robot.position;
    circle(rx,ry,28,'#91a8b5');circle(rx,ry,24,'#f7fafb');box(rx-20,ry-14,40,28,'#2f4d5f');
    text(robot.name,rx,ry+4,12,'white');if(robot.state!=='idle')text(`${robot.name} ${robotLabels[robot.state]}`,rx,ry+43,12);
  }
  for(const p of pieces){
    if(!p.position)continue;
    pallet(...p.position,String(p.id),p.stage);
    if(p.phase==='waiting')text('等待接貨',p.position[0],p.position[1]-20,11);
    if(mode==='demo'&&p.phase==='processing'){box(p.position[0]-16,p.position[1]+18,32,4,'#b8c9d3');box(p.position[0]-16,p.position[1]+18,32*p.progress,4,colors[p.stage]);}
  }
  if(magazinePiece){
    const s=stations.find(s=>s.id==='F'),drop=magazineAt(magazineProgress).drop;
    const width=70-48*drop,y=s.y+14+(dock.F[1]-5-s.y-14)*drop*drop;
    box(s.x-width/2,y,width,10,'#8299a5','#4d6573');
    if(drop===1)text(String(magazinePiece.id),s.x,dock.F[1]+4,10,'white');
  }
  const queued=pieces.filter(p=>p.phase==='queued').length,stored=pieces.filter(p=>p.done).length;
  text(`待上線 ${queued} 件 · 已完成 ${mode==='live'?snapshot?.pieces.filter(p=>p.state==='finished').length||0:stored} 件`,235,535,14);
  if(mode==='live')text('搬運位置與避碰為示意，非實機定位',550,510,12);
  document.getElementById('floor-count').textContent=mode==='live'?`完成 ${snapshot?.pieces.filter(p=>p.state==='finished').length||0} / ${snapshot?.amount??'—'} 件${(snapshot?.amount||0)>60?'（地圖最多顯示 60 件，明細完整）':''}`:`完成 ${pieces.filter(p=>p?.done).length} / 4 件`;
  document.getElementById('floor-clock').textContent=mode==='live'?'每 3 秒同步':`${Math.floor(time)} / ${demoDuration} 秒`;if(mode==='demo')seek.value=time;

}
function select(id){selected=id;picker.value=id;const s=stations.find(s=>s.id===id);document.getElementById('floor-detail').textContent=`${s.id==='P'?'新站':s.id} ${s.name}｜${s.job}`;render();}
stations.forEach(s=>{const option=document.createElement('option');option.value=s.id;option.textContent=`${s.id==='P'?'新站':s.id} ${s.name}`;picker.append(option);});
picker.addEventListener('change',()=>select(picker.value));
canvas.addEventListener('click',e=>{const r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)*1200/r.width,y=(e.clientY-r.top)*780/r.height;const hit=stations.find(s=>Math.abs(s.x-x)<80&&Math.abs(s.y-y)<80);if(hit)select(hit.id);});
function setPlaying(value){playing=value;play.textContent=value?'暫停播放':time>=demoDuration?'重播':'開始播放';}
play.addEventListener('click',()=>{if(time>=demoDuration)time=0;setPlaying(!playing);});
document.getElementById('floor-reset').addEventListener('click',()=>{time=0;setPlaying(false);render();});
seek.addEventListener('input',()=>{time=Number(seek.value);setPlaying(false);render();});
document.addEventListener('visibilitychange',()=>{previous=0;});
function frame(now){
  const dt=previous?Math.min((now-previous)/1000,.1):0;
  if(mode==='live'&&!document.hidden){time=now/1000;tick(liveSimulation,dt);if(!reducedMotion.matches||Math.floor(now/1000)!==Math.floor(previous/1000))render();}
  if(mode==='demo'&&playing&&!document.hidden){time=Math.min(demoDuration,time+dt*Number(document.getElementById('floor-speed').value));if(time>=demoDuration||reducedMotion.matches)setPlaying(false);render();}
  previous=now;requestAnimationFrame(frame);
}
select('A');requestAnimationFrame(frame);

const orderPicker=document.getElementById('floor-order'),modePicker=document.getElementById('floor-mode'),syncText=document.getElementById('floor-sync');
const stateLabels={running:'加工中',error:'故障停留',waiting:'等待下一步',pending:'尚未開始',finished:'製程完成',unknown:'未初始化／未知'};
let controller=null,generation=0;
function updateControls(){
  document.querySelector('.floor-heading p').textContent=mode==='live'?'依選定訂單的逐件製程紀錄顯示位置；換站時以動畫銜接。':'雙 R 搬運 · 工件沿單向輸送帶排隊，進出料分道交接。';
  [play,seek,document.getElementById('floor-reset'),document.getElementById('floor-speed'),document.querySelector('label[for="floor-speed"]'),document.querySelector('label[for="floor-time"]')].forEach(e=>e.hidden=mode==='live');
  [play,seek,document.getElementById('floor-reset'),document.getElementById('floor-speed')].forEach(e=>e.disabled=mode==='live');
  orderPicker.disabled=mode==='demo';document.getElementById('floor-piece-details').hidden=mode==='demo';
  document.getElementById('floor-source').textContent=mode==='live'?'本機訂單紀錄，非 PLC 定位':'示範動畫，非訂單進度';
  document.querySelector('.floor-legend').firstElementChild.textContent=mode==='live'?'藍：待開始／橙：加工或等待／綠：製程完成':'藍色工件：未加工';
  document.querySelector('.floor-legend').children[1].textContent=mode==='live'?'紅：故障／紫：未知；不代表分類器判定':'橙色工件：半成品';
  document.querySelector('.floor-legend').children[2].textContent=mode==='live'?'R1／R2 分別回休息位；搬運與等待時間為示意':'綠色工件：成品';
}
function acceptSnapshot(data){
  setRecords(liveSimulation,data.pieces.slice(0,60));
  snapshot=data;
  const body=document.getElementById('floor-piece-list');body.replaceChildren();
  for(const p of data.pieces){const row=document.createElement('tr');for(const value of [p.piece_no,p.station||'未定位',p.step_name||'—',stateLabels[p.state]||'未知',`${p.done_steps}/${p.total_steps}`]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}body.append(row);}
  syncText.textContent=`訂單 ${data.order_id}｜狀態 ${data.status}｜本機逐件紀錄｜最近紀錄 ${data.latest_record_at||'無時間紀錄'}｜查詢時間 ${data.queried_at}。這是已記錄的製程位置，不代表機台當下仍在運轉；不自動推進製程。`;
  render();
}
async function sync(){
  if(mode!=='live'||!orderPicker.value||controller)return;
  const current=++generation,requestController=new AbortController();controller=requestController;
  const timeout=setTimeout(()=>requestController.abort(),8000);
  try{
    const response=await fetch(`/factory/api/floor_status/${encodeURIComponent(orderPicker.value)}`,{signal:requestController.signal,cache:'no-store'});
    if(!response.ok)throw new Error('讀取失敗');
    const data=await response.json();
    if(current===generation&&mode==='live')acceptSnapshot(data);
  }catch(e){if(current===generation&&mode==='live'){snapshot=null;liveSimulation=createSimulation();magazineCycle=null;pressCycle=null;drillCycle=null;measureCycle=null;document.getElementById('floor-piece-list').replaceChildren();syncText.textContent='連線失敗或無權限：位置未知，已停止顯示舊工件。將自動重試。';render();}}
  finally{clearTimeout(timeout);if(controller===requestController)controller=null;}
}
function changeSource(){generation++;controller?.abort();controller=null;snapshot=null;liveSimulation=createSimulation();magazineCycle=null;pressCycle=null;drillCycle=null;measureCycle=null;document.getElementById('floor-piece-list').replaceChildren();setPlaying(false);time=0;updateControls();render();if(mode==='live'){syncText.textContent=orderPicker.value?'正在讀取訂單…':'沒有可讀取的訂單';sync();}else syncText.textContent='4 件示範工件，兩台 R 輪流搬運、回位休息；左側輸出到 R，右側由 R 送入。共用路段互鎖，前方有工件就等待。';}
orderPicker.addEventListener('change',changeSource);
modePicker.addEventListener('change',()=>{mode=modePicker.value;changeSource();});
async function loadOrders(){
  try{
    const response=await fetch('/factory/api/floor_orders',{cache:'no-store'});if(!response.ok)throw new Error();const data=await response.json();
    orderPicker.replaceChildren();for(const order of data.orders){const option=document.createElement('option');option.value=order.order_id;option.textContent=`${order.order_id} · ${order.status}`;orderPicker.append(option);}
    if(data.orders.some(o=>o.order_id===orderPicker.dataset.order))orderPicker.value=orderPicker.dataset.order;
    changeSource();
  }catch(e){orderPicker.replaceChildren(new Option('無法讀取訂單',''));syncText.textContent='無法讀取訂單，請確認已登入並重新整理。';}
}
updateControls();loadOrders();setInterval(sync,3000);
