// Resource IDs match the existing MES service. No assumed R1/R2 identities or A port.
export const resourceStations={1:'F',2:'G',3:'A',4:'E',5:'D',6:'B',7:'C',8:'H'};
export function machineState(row,now=Date.now()){
  if(!row)return 'unknown';
  const stamp=row.recorded_at,age=now-Date.parse(stamp);
  if(!stamp||!/(Z|[+-]\d{2}:\d{2})$/.test(stamp)||!Number.isFinite(age)||age < -60000)return 'unknown';
  if(age>300000)return 'stale';
  if([row.ErrorL0,row.ErrorL1,row.ErrorL2].some(v=>v===true))return 'error';
  if(row.Busy===true)return 'busy';
  if(row.Busy===false)return 'idle';
  return 'unknown';
}
export const machineLabels={busy:'加工中（MES）',idle:'閒置（MES）',error:'故障（MES）',stale:'舊紀錄・停止動畫',unknown:'狀態未知'};
export function updateMachineCycles(cycles,rows,now=Date.now()){
  const next=new Map();
  for(const row of rows){
    const station=resourceStations[row.ResourceID];if(!station)continue;
    const state=machineState(row,now),old=cycles.get(station);
    // New timestamps while Busy remains true are not new processing cycles.
    next.set(station,{state,start:state==='busy'?(old?.state==='busy'?old.start:now):null,row});
  }
  return next;
}
export function machineMotion(cycle,now=Date.now()){
  const state=machineState(cycle?.row,now);
  return {state,active:state==='busy',progress:state==='busy'&&Number.isFinite(cycle.start)?Math.min(1,Math.max(0,(now-cycle.start)/4000)):0};
}
