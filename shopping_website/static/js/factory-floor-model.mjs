export const stations = [
  {id:'F', name:'盒匣', job:'放置下蓋', x:180,y:130,kind:'magazine'},
  {id:'G', name:'氣壓壓製', job:'上下蓋壓合', x:180,y:365,kind:'press'},
  {id:'A', name:'自動倉儲', job:'A1、A2 均可放入／取出，共用倉儲', x:550,y:120,kind:'rack'},
  {id:'E', name:'視覺檢測', job:'組裝檢驗／R 搬運交接', x:770,y:130,kind:'camera'},
  {id:'D', name:'機器人室', job:'PCB 組裝', x:1020,y:130,kind:'robot'},
  {id:'C', name:'鑽孔', job:'上蓋鑽孔', x:1090,y:390,kind:'drill'},
  {id:'H', name:'烘烤加熱', job:'膠合固化', x:865,y:435,kind:'oven'},
  {id:'B', name:'尺寸量測', job:'尺寸量測／R 搬運交接', x:1090,y:600,kind:'measure'},
  {id:'P', name:'入貨・包裝・出貨', job:'新增機械手臂站／R 搬運交接', x:570,y:680,kind:'robot'},
];
export const dock={A1:[550,280],A2:[550,235],B:[1000,570],C:[1000,375],D:[1020,235],E:[770,235],F:[180,235],G:[180,280],H:[965,435],P:[570,615]};
// Drawing and routing share these centerlines. Each conveyor is a directed loop.
export const belts=[
  [[1100,235],[1020,235],[770,235],[550,235],[180,235],[130,235],[130,280],[180,280],[550,280],[700,280],[745,280],[795,280],[1100,280],[1100,235]],
  [[1000,640],[1000,570],[1000,375],[1000,350],[965,350],[965,435],[965,500],[965,545],[965,595],[965,640],[1000,640]],
];
// Facing the main belt: left lane goes to R; right lane returns from R.
export const spurs=[[[745,280],[745,325]],[[795,325],[795,280]],[[965,545],[920,545]],[[920,595],[965,595]]];
export const pickupHolds=[{hold:[700,280],bay:[745,325]},{hold:[965,500],bay:[920,545]}];
export const parking=[[750,650],[835,650]];
export const robotRoads=[[[745,325],[745,380],[690,380],[690,570],[750,570],[835,570],[900,570]],[[745,380],[795,380],[795,325]],[[900,570],[900,545],[920,545]],[[900,570],[900,595],[920,595]],[[690,570],[570,570],[570,615]],[[750,570],parking[0]],[[835,570],parking[1]]];
export const sequence=['A1','B','C','D','E','F','G','H','A2'];
export function magazineAt(progress){
  const part=(start,length)=>Math.max(0,Math.min(1,(progress-start)/length));
  return {drop:part(.12,.38),shift:part(.5,.2),refill:part(.7,.25)};
}
export function pressAt(progress){
  if(progress<.1||progress>=.8)return 0;
  if(progress<.35)return (progress-.1)/.25;
  if(progress<=.55)return 1;
  return (.8-progress)/.25;
}
const key=p=>p.join(',');
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
const same=(a,b)=>distance(a,b)<.001;
function edgesFor(paths,both=false,kind='belt'){
  return paths.flatMap(path=>path.slice(1).flatMap((p,i)=>both?[{a:path[i],b:p,kind},{a:p,b:path[i],kind}]:[{a:path[i],b:p,kind}]));
}
const roadEdges=edgesFor(robotRoads,true,'robot');
export const transportEdges=[...edgesFor(belts),...edgesFor(spurs,false,'spur'),...roadEdges];
function shortest(edges,from,to){
  const queue=[{point:from,path:[from],cost:0}],seen=new Set();
  while(queue.length){
    queue.sort((a,b)=>a.cost-b.cost);const item=queue.shift(),id=key(item.point);
    if(id===key(to))return item.path;if(seen.has(id))continue;seen.add(id);
    for(const edge of edges.filter(e=>same(e.a,item.point)))queue.push({point:edge.b,path:[...item.path,edge.b],cost:item.cost+distance(edge.a,edge.b)});
  }
  return null;
}
export const routeBetween=(from,to)=>dock[from]&&dock[to]?shortest(transportEdges,dock[from],dock[to]):null;
const isRobotEdge=(a,b)=>roadEdges.some(e=>same(e.a,a)&&same(e.b,b));
export function createSimulation(demo=false){
  const sim={time:0,demo,pieces:[],nextRobot:0,robots:parking.map((home,i)=>({name:`R${i+1}`,home,position:[...home],path:[],state:'idle',cargo:null}))};
  if(demo)for(let i=0;i<4;i++){
    const route=i%2?sequence.map(s=>s==='A1'?'A2':s==='A2'?'A1':s):sequence;
    sim.pieces.push({id:i+1,station:route[0],target:route[0],route,step:0,release:i*12,position:null,path:[],phase:'queued',remaining:8,stage:'raw'});
  }
  return sim;
}
export function setRecords(sim,records){
  const previous=new Map(sim.pieces.map(p=>[p.id,p]));
  for(const row of records){
    let p=previous.get(row.piece_no);
    if(!p){p={id:row.piece_no,station:row.station,target:row.station,position:null,path:[],phase:row.state==='finished'?'stored':'queued',release:sim.time};sim.pieces.push(p);}
    if(!dock[p.station]||(p.phase==='stored'&&row.state!=='finished')){p.station=row.station;p.phase='queued';p.position=null;}
    p.target=row.station;p.state=row.state;p.stage=row.state==='finished'?'finished':row.state==='error'?'error':!dock[row.station]?'unknown':row.state==='pending'?'raw':'wip';
  }
}
function overlaps(a,halfA,b,halfB){return Math.abs(a[0]-b[0])<halfA[0]+halfB[0]+1&&Math.abs(a[1]-b[1])<halfA[1]+halfB[1]+1;}
function clearMove(sim,from,to,half,ignorePiece,ignoreRobot=null){
  // Axis-aligned swept rectangles prevent tunnelling even at the fastest playback speed.
  const center=[(from[0]+to[0])/2,(from[1]+to[1])/2],size=[half[0]+Math.abs(to[0]-from[0])/2,half[1]+Math.abs(to[1]-from[1])/2];
  return sim.pieces.every(p=>!p.position||p.id===ignorePiece||!overlaps(center,size,p.position,[16,12]))&&sim.robots.every(r=>r===ignoreRobot||!overlaps(center,size,r.position,[28,28]));
}
function advance(sim,item,dt,speed,half,ignorePiece,ignoreRobot){
  if(!item.path.length)return false;
  const target=item.path[0],length=distance(item.position,target),f=Math.min(1,speed*dt/(length||1));
  const next=item.position.map((v,i)=>v+(target[i]-v)*f);
  if(!clearMove(sim,item.position,next,half,ignorePiece,ignoreRobot))return false;
  item.position=next;if(f===1)item.path.shift();return true;
}
function beginTrip(p,to){
  const path=routeBetween(p.station,to);if(!path)return;
  p.path=path.slice(1);p.destination=to;p.phase='travel';
}
function pickupPoint(p){
  let point=p.position;
  for(const next of p.path){if(isRobotEdge(point,next))return point;point=next;}
  return null;
}
function arrive(sim,p){
  p.station=p.destination;p.phase='processing';p.remaining=8;
  if(sim.demo)p.step++;
  else if(p.state==='finished'&&p.station===p.target){p.phase='stored';p.position=null;}
}
export function tick(sim,dt){
  // Fixed substeps keep collision behaviour identical at 1x, 2x, 4x and after seeking.
  while(dt>1e-8){const step=Math.min(.025,dt);stepSimulation(sim,step);dt-=step;}
}
function stepSimulation(sim,dt){
  sim.time+=dt;
  for(const p of sim.pieces){
    if(p.phase==='stored')continue;
    if(p.phase==='queued'){
      if(sim.time<p.release||!dock[p.station])continue;
      if(clearMove(sim,dock[p.station],dock[p.station],[16,12],p.id)){p.position=[...dock[p.station]];p.phase='processing';}
    }
    if(p.phase==='processing'){
      if(sim.demo){p.remaining-=dt;p.stage=p.step<2?'raw':p.step<7?'wip':'finished';
        if(p.remaining<=0){if(p.step===p.route.length-1){p.phase='stored';p.position=null;}else beginTrip(p,p.route[p.step+1]);}
      }else if(p.station!==p.target)beginTrip(p,p.target);
      else if(p.state==='finished'){p.phase='stored';p.position=null;}
    }
    if(p.phase==='travel'){
      if(!p.path.length){arrive(sim,p);continue;}
      const pickup=pickupPoint(p);
      if(pickup&&(pickupHolds.some(h=>same(p.position,h.hold)&&same(pickup,h.bay))||isRobotEdge(p.position,p.path[0]))){p.phase='waiting';p.waitSince=sim.time;continue;}
      const unloading=sim.robots.find(r=>r.state==='unloading'&&r.cargo===p.id);
      advance(sim,p,dt,100,[16,12],p.id,unloading);
      if(!p.path.length)arrive(sim,p);
    }
  }
  // One vehicle at a time in the shared narrow corridor, including the empty return trip.
  if(sim.robots.every(r=>r.state==='idle')){
    const p=sim.pieces.filter(p=>p.phase==='waiting').sort((a,b)=>a.waitSince-b.waitSince)[0];
    if(p){const r=sim.robots[sim.nextRobot];sim.nextRobot=1-sim.nextRobot;r.path=shortest(roadEdges,r.home,pickupPoint(p)).slice(1);r.state='pickup';r.cargo=p.id;}
  }
  for(const r of sim.robots){
    if(r.state==='idle')continue;
    const p=sim.pieces.find(p=>p.id===r.cargo);
    if(r.state==='loading'){
      if(!same(p.position,r.position)){advance(sim,p,dt,80,[16,12],p.id,r);continue;}
      p.phase='carried';r.state='loaded';let point=p.position;
      while(p.path.length&&isRobotEdge(point,p.path[0])){point=p.path.shift();r.path.push(point);}
    }
    if(r.state==='unloading'){
      if(p?.position&&overlaps(r.position,[28,28],p.position,[16,12]))continue;
      r.cargo=null;r.state='return';r.path=shortest(roadEdges,r.position,r.home).slice(1);
    }
    advance(sim,r,dt,120,[28,28],r.cargo,r);
    if(r.state==='loaded')p.position=[...r.position];
    if(r.path.length)continue;
    if(r.state==='pickup'){
      p.phase='boarding';r.state='loading';
    }else if(r.state==='loaded'){p.phase='travel';r.state='unloading';}
    else if(r.state==='return'){r.state='idle';r.position=[...r.home];}
  }
}
export function snapshotOf(sim){
  return {pieces:sim.pieces.map(p=>({id:p.id,station:p.station,state:p.state,stage:p.stage,phase:p.phase,position:p.position?[...p.position]:null,done:p.phase==='stored',inTransit:['travel','waiting','boarding','carried'].includes(p.phase),progress:Math.max(0,Math.min(1,1-(p.remaining||0)/8))})),robots:sim.robots.map(r=>({name:r.name,position:[...r.position],state:r.state,id:r.state==='loaded'||r.state==='loading'||r.state==='unloading'?r.cargo:null}))};
}
const demo=createSimulation(true),frames=[snapshotOf(demo)];
while(demo.time<900&&!(demo.pieces.every(p=>p.phase==='stored')&&demo.robots.every(r=>r.state==='idle'))){tick(demo,.05);frames.push(snapshotOf(demo));}
export const demoDuration=(frames.length-1)*.05;
export function demoFrameAt(time){
  const index=Math.min(frames.length-1,Math.max(0,time/.05)),a=frames[Math.floor(index)],b=frames[Math.min(frames.length-1,Math.floor(index)+1)],f=index%1;
  const interpolate=(items,next)=>items.map((p,i)=>({...p,position:p.position&&next[i].position&&p.phase===next[i].phase&&p.state===next[i].state&&p.id===next[i].id?p.position.map((v,j)=>v+(next[i].position[j]-v)*f):p.position}));
  return {pieces:interpolate(a.pieces,b.pieces),robots:interpolate(a.robots,b.robots)};
}
