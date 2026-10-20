const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui/graph.js'), 'utf8'), context);
const h = context.PySASGraph.helpers;
const plain = value => JSON.parse(JSON.stringify(value));
const node = (id, values = {}) => ({id, name: id, source: {type: 'file', path: 'C:/code/'+id+'.sas'}, x: 0, y: 0, ...values});
const graph = (nodes = [], edges = [], setup = []) => ({format:'pysas-graph-1', id:'example', name:'Example', workers:10, connection:'', setup, nodes, edges});

test('a single program and an empty saved draft are valid graphs', () => {
  assert.equal(h.validate(graph()).nodes.length, 0);
  assert.deepEqual(plain(h.order(graph([node('A')]))), ['A']);
});

test('task IDs are readable and remain unique across setup and normal programs', () => {
  const model=graph([node('p_Realised')],[],[node('P_REALISED_2')]);
  assert.equal(h.programId(model,'Realised.sas'),'p_Realised_3');
  assert.equal(h.programId(model,'Realização.sas'),'p_Realizacao');
  assert.match(h.programId(model,'CON.sas'),/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$/);
});

test('dependency arrows order prerequisites first, including skipped chains', () => {
  const model = graph([node('C'), node('B', {skip:true}), node('A')], [{from:'A',to:'B'}, {from:'B',to:'C'}]);
  assert.deepEqual(plain(h.order(h.validate(model))), ['A','B','C']);
});

test('links reject cycles, duplicate arrows, dangling targets and setup dependencies', () => {
  const model = graph([node('A'),node('B')], [{from:'A',to:'B'}], [node('S')]);
  for (const [from, to] of [['B','A'], ['A','B'], ['A','missing'], ['S','A'], ['A','A']]) {
    assert.throws(() => h.link(model, from, to));
  }
  assert.equal(model.edges.length, 1);
});

test('adding a dependency never mutates the previous graph or source', () => {
  const model = graph([node('A'),node('B')]);
  const linked = h.link(model, 'A', 'B');
  linked.nodes[0].source.path = 'different.sas';
  assert.equal(model.edges.length, 0);
  assert.equal(model.nodes[0].source.path, 'C:/code/A.sas');
});

test('removing a node removes incoming and outgoing arrows without losing unrelated links', () => {
  const model = graph(['A','B','C','D'].map(id=>node(id)), [{from:'A',to:'B'}, {from:'B',to:'C'}, {from:'A',to:'D'}]);
  const next = h.remove(model, 'B');
  assert.deepEqual(plain(next.edges), [{from:'A',to:'D'}]);
  assert.equal(model.nodes.length, 4);
  assert.equal(h.validate(next).nodes.length, 3);
});

test('auto layout puts dependent programs in later columns and siblings on separate rows', () => {
  const model = graph(['D','C','B','A'].map(id=>node(id)), [{from:'A',to:'B'}, {from:'A',to:'C'}, {from:'B',to:'D'}, {from:'C',to:'D'}]);
  const arranged = h.arrange(model), n = Object.fromEntries(arranged.nodes.map(n=>[n.id,n]));
  assert.ok(n.A.x<n.B.x && n.B.x<n.D.x);
  assert.equal(n.B.x,n.C.x);
  assert.notEqual(n.B.y,n.C.y);
  assert.equal(h.validate(arranged).nodes.length,4);
  assert.equal(model.nodes[0].x,0);
});

test('canvas arrows browse the closest program in the chosen direction', () => {
  const nodes = [node('A',{x:100,y:100}),node('B',{x:400,y:100}),node('C',{x:100,y:300})];
  assert.equal(h.nearest(nodes,'A','ArrowRight'),'B');
  assert.equal(h.nearest(nodes,'A','ArrowDown'),'C');
  assert.equal(h.nearest(nodes,'A','ArrowLeft'),'A');
  assert.equal(h.nearest(nodes,null,'ArrowLeft'),'A');
});

test('undo and redo retain complete graph source and setup snapshots', () => {
  const history = new h.History(), before = graph([node('A')], [], [node('S')]);
  history.push(before);
  const after = graph([node('A'),node('B')]);
  before.setup[0].source.path='live change';
  const undone=history.undo(after);
  assert.equal(undone.setup[0].source.path,'C:/code/S.sas');
  assert.equal(history.redo(undone).nodes.length,2);
  history.push(after);
  assert.equal(history.after.length,0);
  for(let i=0;i<50;i++)history.push(after);
  assert.equal(history.before.length,40);
});

test('invalid rows, coordinates, IDs and worker counts fail before saving', () => {
  const bad = [node('A',{row_start:5,row_end:3}),node('A',{section:'X',row_start:3}),node('A',{x:Infinity}),node('A',{tables:'yes'})];
  for(const n of bad) assert.throws(()=>h.validate(graph([n])));
  assert.throws(()=>h.validate(graph([node('A'),node('a')])));
  for(const workers of [0,33,1.5])assert.throws(()=>h.validate({...graph(),workers}));
});

test('rendered editor imports safely and keyboard linking saves a real graph dependency', async () => {
  const elements=new Map(), listeners=new Map(), requests=[];
  function element(id){
    if(!elements.has(id))elements.set(id,{id,innerHTML:'',textContent:'',value:'',hidden:false,dataset:{},style:{},
      classList:{toggle(){}},setAttribute(){},focus(){},matches(){return false;},
      querySelectorAll(){return [];},
      addEventListener(type,callback){listeners.set(id+':'+type,callback);}});
    return elements.get(id);
  }
  element('details-dialog').hidden=true;
  const document={getElementById:element,querySelectorAll:()=>[],querySelector:()=>null,addEventListener(){},activeElement:null};
  const host={badge:()=>'',timer:()=>'',fileActions:()=>'',request:async(url,body)=>{
    requests.push([url,body]);
    return url==='/api/graphs'&&body?{graph:body.graph,revision:'revision',path:'settings/graphs/example.json'}:{graphs:[],sources:[]};
  }};
  const ui=vm.createContext({document,crypto:{randomUUID:()=> '12345678-1234-1234-1234-123456789abc'},PySASGraphHost:host});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/graph.js'),'utf8'),ui);
  const model=graph([node('A',{name:'<img src=x onerror=alert(1)>'}),node('B',{x:400})]);
  await listeners.get('graph-import:change')({target:{files:[{size:100,text:async()=>JSON.stringify(model)}]}});
  assert.match(element('graph-nodes').innerHTML,/&lt;img/);
  assert.doesNotMatch(element('graph-nodes').innerHTML,/<img/);
  ui.PySASGraph.update({windows:true,files:[],commands:[],initialization_files:[]},'graph');
  const click=identifier=>listeners.get('graph-canvas:click')({target:{closest:selector=>selector==='[data-graph-node]'?{dataset:{graphNode:identifier}}:null}});
  click('A');
  listeners.get('graph-connect:click')();
  const press=key=>listeners.get('graph-canvas:keydown')({key,preventDefault(){}});
  press('ArrowRight');press('Enter');
  await listeners.get('graph-save:click')();
  const saved=requests.find(([url,body])=>url==='/api/graphs'&&body)[1].graph;
  assert.deepEqual(plain(saved.edges),[{from:'A',to:'B'}]);
  assert.equal(saved.nodes[0].name,'<img src=x onerror=alert(1)>');
});
