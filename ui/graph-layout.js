/* Geometry for the task canvas: layered placement, alignment and card-aware links. */
(function(){
  'use strict';
  const W=264,H=158,GAP=110,ROW=223,clone=value=>JSON.parse(JSON.stringify(value));
  function arrange(model){
    const result=clone(model),level=new Map(),remaining=new Set(result.nodes.map(n=>n.id));
    while(remaining.size){
      const ready=result.nodes.filter(n=>remaining.has(n.id)&&!result.edges.some(e=>e.to===n.id&&remaining.has(e.from)));
      if(!ready.length)throw Error('Circular dependency detected. Remove a link.');
      for(const n of ready){level.set(n.id,Math.max(0,...result.edges.filter(e=>e.to===n.id).map(e=>level.get(e.from)+1)));remaining.delete(n.id);}
    }
    const layers=[];for(const n of result.nodes)(layers[level.get(n.id)]??=[]).push(n);
    // Reduce crossings between neighboring layers while preserving stable ties.
    for(let pass=0;pass<4;pass++){
      const reverse=pass%2===1,indices=layers.map((_,i)=>i);if(reverse)indices.reverse();
      const positions=new Map(layers.flatMap(layer=>layer.map((n,i)=>[n.id,(i+.5)/layer.length])));
      for(const index of indices){const original=new Map(layers[index].map((n,i)=>[n.id,i]));
        const score=n=>{const neighbors=result.edges.filter(e=>reverse?e.from===n.id:e.to===n.id).map(e=>positions.get(reverse?e.to:e.from));return neighbors.length?neighbors.reduce((a,b)=>a+b,0)/neighbors.length:positions.get(n.id);};
        layers[index].sort((a,b)=>score(a)-score(b)||original.get(a.id)-original.get(b.id));
        layers[index].forEach((n,i)=>positions.set(n.id,(i+.5)/layers[index].length));
      }
    }
    // Reserve a bypass lane where an edge spans an intermediate rank. This
    // prevents A→C from occupying the same row as B in A→B→C plus A→C.
    const lanes=layers.map((_,rank)=>result.edges.some(e=>level.get(e.from)<rank&&level.get(e.to)>rank)?1:0);
    const height=Math.max(0,...layers.map((layer,i)=>layer.length+lanes[i]));
    layers.forEach((layer,rank)=>layer.forEach((n,index)=>{n.x=rank*(W+GAP);n.y=Math.round(((height-layer.length-lanes[rank])/2+lanes[rank]+index)*ROW);}));
    return result;
  }
  function align(model,ids,kind){
    const result=clone(model),selected=result.nodes.filter(n=>ids.includes(n.id));if(selected.length<2)return result;
    const left=Math.min(...selected.map(n=>n.x)),right=Math.max(...selected.map(n=>n.x)),top=Math.min(...selected.map(n=>n.y)),bottom=Math.max(...selected.map(n=>n.y));
    if(kind==='horizontal'||kind==='vertical'){
      if(selected.length<3)return result;const field=kind==='horizontal'?'x':'y',start=field==='x'?left:top,end=field==='x'?right:bottom;
      selected.sort((a,b)=>a[field]-b[field]).forEach((n,i)=>n[field]=Math.round(start+(end-start)*i/(selected.length-1)));
    }else for(const n of selected){
      if(kind==='left')n.x=left;else if(kind==='right')n.x=right;else if(kind==='center')n.x=Math.round((left+right)/2);
      else if(kind==='top')n.y=top;else if(kind==='bottom')n.y=bottom;else if(kind==='middle')n.y=Math.round((top+bottom)/2);else throw Error('Choose an alignment.');
    }
    return result;
  }
  function intersects(a,b,box){
    let low=0,high=1;
    for(const [key,min,max] of [['x',box.left,box.right],['y',box.top,box.bottom]]){
      const distance=b[key]-a[key];if(!distance){if(a[key]<=min||a[key]>=max)return false;continue;}
      const first=(min-a[key])/distance,last=(max-a[key])/distance;low=Math.max(low,Math.min(first,last));high=Math.min(high,Math.max(first,last));if(low>=high)return false;
    }return high>0&&low<1;
  }
  function clear(points,boxes){for(let i=1;i<points.length;i++)for(const box of boxes)if(intersects(points[i-1],points[i],box))return false;return true;}
  const number=value=>Math.round(value*10)/10;
  function rounded(points){
    points=points.filter((p,i)=>!i||p.x!==points[i-1].x||p.y!==points[i-1].y);let path=`M${number(points[0].x)},${number(points[0].y)}`;
    for(let i=1;i<points.length-1;i++){
      const previous=points[i-1],p=points[i],next=points[i+1],before=Math.hypot(previous.x-p.x,previous.y-p.y),after=Math.hypot(next.x-p.x,next.y-p.y),r=Math.min(9,before/2,after/2);
      path+=` L${number(p.x+(previous.x-p.x)*r/before)},${number(p.y+(previous.y-p.y)*r/before)} Q${number(p.x)},${number(p.y)} ${number(p.x+(next.x-p.x)*r/after)},${number(p.y+(next.y-p.y)*r/after)}`;
    }const end=points.at(-1);return path+` L${number(end.x)},${number(end.y)}`;
  }
  function route(a,b,nodes=[],lane=0){
    const start={x:a.x+W,y:a.y+H/2},end={x:b.x,y:b.y+H/2},bend=Math.max(70,Math.abs(end.x-start.x)*.45);
    const boxes=nodes.filter(n=>n.id!==a.id&&n.id!==b.id).map(n=>({left:n.x-16,right:n.x+W+16,top:n.y-16,bottom:n.y+H+16}));
    const curve=Array.from({length:25},(_,i)=>{const t=i/24,u=1-t;return {x:u*u*u*start.x+3*u*u*t*(start.x+bend)+3*u*t*t*(end.x-bend)+t*t*t*end.x,y:u*u*u*start.y+3*u*u*t*start.y+3*u*t*t*end.y+t*t*t*end.y};});
    if(clear(curve,boxes))return {path:`M${start.x},${start.y} C${start.x+bend},${start.y} ${end.x-bend},${end.y} ${end.x},${end.y}`,points:curve,routed:false};
    const offset=24+(lane%5)*7,between=boxes.filter(box=>box.right>Math.min(start.x,end.x)&&box.left<Math.max(start.x,end.x));
    const levels=[Math.min(start.y,end.y,...between.map(n=>n.top))-offset,Math.max(start.y,end.y,...between.map(n=>n.bottom))+offset,Math.min(a.y,b.y,...boxes.map(n=>n.top))-offset,Math.max(a.y+H,b.y+H,...boxes.map(n=>n.bottom))+offset];
    const candidates=levels.map(y=>[start,{x:start.x+24,y:start.y},{x:start.x+24,y},{x:end.x-24,y},{x:end.x-24,y:end.y},end]);
    const length=points=>points.slice(1).reduce((sum,p,i)=>sum+Math.abs(p.x-points[i].x)+Math.abs(p.y-points[i].y),0);
    const points=candidates.filter(points=>clear(points,boxes)).sort((a,b)=>length(a)-length(b))[0]||candidates[2];
    return {path:rounded(points),points,routed:true};
  }
  const api={arrange,align,route,intersects};globalThis.PySASGraphLayout=api;if(typeof module!=='undefined')module.exports=api;
})();
