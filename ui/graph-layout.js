/* Layered card placement, alignment and the original curved dependency links. */
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
    // Keep the curves unchanged. Move intermediate cards away from the vertical
    // band occupied by a spanning curve at that column instead. Endpoints can
    // move in later sweeps, so retain the best placement on dense graphs.
    const byId=new Map(result.nodes.map(n=>[n.id,n])),ratios=new Map(),padding=24;
    function fractions(from,to,rank){
      const key=`${to-from}/${rank-from}`;if(ratios.has(key))return ratios.get(key);
      const start=W,end=(to-from)*(W+GAP),bend=(end-start)*.45;
      const xAt=t=>{const u=1-t;return u*u*u*start+3*u*u*t*(start+bend)+3*u*t*t*(end-bend)+t*t*t*end;};
      const fraction=x=>{let low=0,high=1;for(let i=0;i<24;i++){const t=(low+high)/2;if(xAt(t)<x)low=t;else high=t;}const t=(low+high)/2;return t*t*(3-2*t);};
      const left=(rank-from)*(W+GAP)-padding,value=[fraction(left),fraction(left+W+2*padding)];ratios.set(key,value);return value;
    }
    const spanning=layers.map((_,rank)=>result.edges.filter(e=>level.get(e.from)<rank&&level.get(e.to)>rank).map(e=>({a:byId.get(e.from),b:byId.get(e.to),fractions:fractions(level.get(e.from),level.get(e.to),rank)})));
    const bands=rank=>spanning[rank].map(({a,b,fractions})=>{const ys=fractions.map(t=>a.y+H/2+(b.y-a.y)*t);return [Math.min(...ys)-H-padding,Math.max(...ys)+padding];});
    const collisions=()=>layers.reduce((sum,layer,rank)=>{const intervals=bands(rank);return sum+layer.reduce((count,n)=>count+intervals.filter(([low,high])=>n.y>low&&n.y<high).length,0);},0);
    let best=result.nodes.map(n=>n.y),score=collisions();
    for(let pass=0;pass<8&&score;pass++){
      const indices=layers.map((_,i)=>i);if(pass%2)indices.reverse();let moved=false;
      for(const rank of indices){const blocked=bands(rank);for(const n of layers[rank]){
        const intervals=[...blocked,...layers[rank].filter(other=>other!==n).map(other=>[other.y-H-40,other.y+H+40])].sort((a,b)=>a[0]-b[0]),merged=[];
        for(const interval of intervals){const last=merged.at(-1);if(last&&interval[0]<=last[1])last[1]=Math.max(last[1],interval[1]);else merged.push([...interval]);}
        const hit=merged.find(([low,high])=>n.y>low&&n.y<high);if(!hit)continue;
        const candidates=[Math.floor(hit[0]),Math.ceil(hit[1])].filter(y=>Math.abs(y)<=100000);if(!candidates.length)continue;
        candidates.sort((a,b)=>Math.abs(a-n.y)-Math.abs(b-n.y)||a-b);n.y=candidates[0];moved=true;
      }}
      const next=collisions();if(next<score){score=next;best=result.nodes.map(n=>n.y);}if(!moved)break;
    }
    const top=Math.min(0,...best),shift=Math.max(0,...best)-top<=100000?-top:0;result.nodes.forEach((n,i)=>n.y=best[i]+shift);
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
  function route(a,b){
    const start={x:a.x+W,y:a.y+H/2},end={x:b.x,y:b.y+H/2},bend=Math.max(70,Math.abs(end.x-start.x)*.45);
    const points=Array.from({length:33},(_,i)=>{const t=i/32,u=1-t;return {x:u*u*u*start.x+3*u*u*t*(start.x+bend)+3*u*t*t*(end.x-bend)+t*t*t*end.x,y:start.y+(end.y-start.y)*t*t*(3-2*t)};});
    return {path:`M${start.x},${start.y} C${start.x+bend},${start.y} ${end.x-bend},${end.y} ${end.x},${end.y}`,points,routed:false};
  }
  const api={arrange,align,route,intersects};globalThis.PySASGraphLayout=api;if(typeof module!=='undefined')module.exports=api;
})();
