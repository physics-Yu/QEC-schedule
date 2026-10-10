"""Independent O(V+E) graph storage and causal checks for T605.

This normalized view belongs to the verifier, not to a producer wire schema.
Reachability is queried on demand; no quadratic transitive closure is stored.
"""
from collections import deque
from dataclasses import dataclass
from math import isfinite

from .checker import _hash


class DAGAudit:
    def __init__(self,scope,inputs,*,fixture=False):
        self.scope,self.inputs,self.fixture=scope,inputs,fixture
        self.failures=[]; self.unverified=[]; self.checks=[]; self.metrics={}; self.interfaces={}

    def fail(self,code,message,**context): self.failures.append({'code':code,'message':message,**context})
    def need(self,code,message,**context): self.unverified.append({'code':code,'message':message,**context})
    def check(self,name,fn):
        before=(len(self.failures),len(self.unverified))
        try: value=fn()
        except (KeyError,TypeError,ValueError,IndexError,AttributeError) as exc:
            self.fail('DAG_INPUT_INVALID',f'{type(exc).__name__}: {exc}',check=name); value=None
        self.checks.append({'id':name,'status':'failed' if len(self.failures)>before[0] else 'unverified' if len(self.unverified)>before[1] else 'passed'})
        return value

    def report(self):
        hashes={}
        for name,value in self.inputs.items():
            try: hashes[name]=_hash(value)
            except (TypeError,ValueError): self.fail('DAG_NON_JSON_INPUT','Evidence must be finite JSON',input=name)
        passed=not self.failures and not self.unverified
        return {'schema_version':'HierarchicalValidationReport/0.1.0','scope':self.scope,
                'provenance':{'owner':'R6','task':'T605','kb_revision':'kb-0006','plan_revision':'plan-0008'},
                'passed':passed,'scoped_pass':not self.failures,'full_program_passed':passed and self.scope=='complete_shor15' and not self.fixture,
                'checks':self.checks,'failures':self.failures,'unverified':self.unverified,'metrics':self.metrics,
                'input_sha256':hashes,'consumed_interfaces':self.interfaces,'fixture':self.fixture,
                'sampled':False,'quantum_state_simulated':False,'hardware_executed':False,
                'out_of_scope':['quantum_state_execution','measurement_probabilities','noise','physical_hardware','user_visual_acceptance']}


@dataclass
class DependencyGraph:
    nodes: dict
    predecessors: dict
    successors: dict
    order: list
    writers: dict

    def precedes(self,source,target):
        if source==target: return False
        # Search backwards, retaining only this query's visited set.
        seen=set(); todo=list(self.predecessors[target])
        while todo:
            current=todo.pop()
            if current==source: return True
            if current not in seen:
                seen.add(current); todo.extend(self.predecessors[current]-seen)
        return False

    def ready(self,completed,available_results=()):
        completed=set(completed); available=set(available_results)
        return sorted(n for n,node in self.nodes.items() if n not in completed and self.predecessors[n]<=completed and set(node['reads'])<=available)


def inspect_graph(audit,nodes,edges,*,external_results=()):
    if not isinstance(nodes,list) or not isinstance(edges,list): raise ValueError('nodes and edges must be lists')
    by_id={}; writers={}; external=set(external_results)
    for node in nodes:
        identity=node['id']
        if not isinstance(identity,str) or not identity or identity in by_id:
            audit.fail('DAG_NODE_ID','Node IDs must be nonempty and unique',node_id=identity); continue
        by_id[identity]=node
        for field in ('reads','writes'):
            if not isinstance(node[field],list) or any(not isinstance(r,str) or not r for r in node[field]) or len(set(node[field]))!=len(node[field]):
                raise ValueError(f'{identity}.{field} must contain unique result IDs')
        condition=node.get('condition')
        if condition is not None:
            if set(condition)!={'bit','equals'} or type(condition['equals']) is not int or condition['equals'] not in (0,1):
                audit.fail('DAG_CONDITION_UNSUPPORTED','Condition must be an explicit bit comparison',node_id=identity)
            elif condition['bit'] not in node['reads']:
                audit.fail('DAG_CONDITION_READ_MISSING','Condition is absent from explicit classical reads',node_id=identity,result_id=condition['bit'])
        for result in node['writes']:
            if result in writers or result in external: audit.fail('DAG_RESULT_WRITER','A result has multiple or external writers',result_id=result)
            writers[result]=identity
    predecessors={n:set() for n in by_id}; successors={n:set() for n in by_id}; seen_edges=set()
    for edge in edges:
        source,target=edge['source'],edge['target']; key=_hash(edge)
        if source not in by_id or target not in by_id or source==target:
            audit.fail('DAG_EDGE_ENDPOINT','Edge endpoints must identify distinct existing nodes',edge=edge); continue
        if edge['kind'] not in {'quantum','classical','classical_ready','protocol','lifecycle','resource'}:
            audit.fail('DAG_EDGE_KIND','Unknown dependency semantics',edge=edge)
        if key in seen_edges: audit.fail('DAG_DUPLICATE_EDGE','Dependency edge is repeated',edge=edge)
        seen_edges.add(key); predecessors[target].add(source); successors[source].add(target)
    indegree={n:len(p) for n,p in predecessors.items()}; todo=deque(sorted(n for n,d in indegree.items() if d==0)); order=[]
    while todo:
        node=todo.popleft(); order.append(node)
        for later in sorted(successors[node]):
            indegree[later]-=1
            if indegree[later]==0: todo.append(later)
    if len(order)!=len(by_id):
        audit.fail('DAG_CYCLE','Dependency graph is cyclic',remaining_nodes=sorted(n for n,d in indegree.items() if d)); return None
    graph=DependencyGraph(by_id,predecessors,successors,order,writers)
    for identity,node in by_id.items():
        for result in node['reads']:
            if result in external: continue
            if result not in writers: audit.fail('DAG_RESULT_PRODUCER_MISSING','Read has no declared producer',node_id=identity,result_id=result)
            elif not graph.precedes(writers[result],identity):
                audit.fail('DAG_CLASSICAL_DEPENDENCY_MISSING','Read is not ordered after its actual writer',node_id=identity,result_id=result,producer=writers[result])
    audit.metrics.update(node_count=len(by_id),edge_count=len(seen_edges),result_count=len(writers),initial_ready=graph.ready((),external),storage_model='O(V+E); on-demand reachability')
    return graph


def audit_dependency_graph(nodes,edges,*,external_results=(),fixture=False):
    audit=DAGAudit('dependency_graph_component',{'nodes':nodes,'edges':edges,'external_results':list(external_results)},fixture=fixture)
    audit.check('graph_structure_and_classical_dependencies',lambda:inspect_graph(audit,nodes,edges,external_results=external_results))
    return audit.report()


def inspect_schedule(audit,graph,intervals,decisions,results):
    """Check the normalized public scheduler record against independently ready nodes."""
    by_id={row['node_id']:row for row in intervals}
    if len(by_id)!=len(intervals) or set(by_id)!=set(graph.nodes):
        audit.fail('SCHEDULE_NODE_COVERAGE','Every DAG node needs exactly one scheduled/explicitly skipped record'); return
    for node_id,interval in by_id.items():
        begin,end=interval['start_us'],interval['end_us']
        if any(type(t) not in (int,float) or not isfinite(t) for t in (begin,end)) or begin<0 or end<begin:
            audit.fail('SCHEDULE_INTERVAL','Invalid node interval',node_id=node_id); continue
        if interval['status'] not in ('completed','skipped'): audit.need('SCHEDULE_NODE_NOT_EXECUTED','Node has no committed outcome',node_id=node_id)
        for dep in graph.predecessors[node_id]:
            if by_id[dep]['end_us']>begin: audit.fail('SCHEDULE_DEPENDENCY','Node precedes completion of a DAG predecessor',node_id=node_id,predecessor=dep)
        for rid in graph.nodes[node_id]['reads']:
            if rid not in results or results[rid]['ready_us']>begin:
                audit.fail('SCHEDULE_RESULT_NOT_READY','Logical node reads a missing/not-ready result',node_id=node_id,result_id=rid)
        cond=graph.nodes[node_id].get('condition')
        if cond and cond['bit'] in results:
            expected='completed' if results[cond['bit']]['value']==cond['equals'] else 'skipped'
            if interval['status']!=expected: audit.fail('SCHEDULE_CONDITION','Logical branch outcome differs from actual result',node_id=node_id)
        elif not cond and interval['status']=='skipped': audit.fail('SCHEDULE_UNCONDITIONAL_SKIP','Unconditional DAG node cannot be skipped',node_id=node_id)
    selected_all=set()
    for decision in decisions:
        at=decision['time_us']; selected=set(decision['selected']); published={r for r,v in results.items() if v['ready_us']<=at}
        completed={n for n,i in by_id.items() if i['end_us']<=at and n in selected_all}
        ready=set(graph.ready(completed,published))-selected_all
        if set(decision['ready'])!=ready: audit.fail('SCHEDULE_READY_SET','Reported ready set differs from causal readiness',time_us=at,expected=sorted(ready))
        if not selected or not selected<=ready or selected&selected_all:
            audit.fail('SCHEDULE_SELECTION','Selection contains missing, unready or previously selected nodes',time_us=at)
        for n in selected:
            if n in by_id and by_id[n]['start_us']!=at: audit.fail('SCHEDULE_SELECTION_TIME','Chosen node does not start at the recorded decision time',node_id=n)
        selected_all.update(selected)
    if selected_all!=set(by_id): audit.fail('SCHEDULE_DECISION_COVERAGE','Actual schedule lacks a complete ready-set decision history')


def physical_parallel_witnesses(audit,graph,node_actions,actions,node_patches,*,node_sources=None):
    """Only overlapping executed local gates/readouts/resets count as this witness."""
    actual={a['id']:a for a in actions}; owned={}; candidates=[]; witnesses=[]
    for nid,ids in node_actions.items():
        for aid in ids: owned.setdefault(aid,set()).add(nid)
    shared={aid:nodes for aid,nodes in owned.items() if len(nodes)>1}
    for aid,owners in shared.items():
        source_ids=set(actual.get(aid,{}).get('payload',{}).get('physical_op_ids',[]))
        expected=set() if node_sources is None else {nid for nid,ops in node_sources.items() if source_ids&set(ops)}
        if not source_ids or expected!=owners:
            audit.need('DAG_SHARED_ACTION_MAPPING','Shared physical action needs an exact multi-node source mapping',action_id=aid)
    for node_id,ids in node_actions.items():
        for aid in ids:
            if aid not in actual: audit.fail('DAG_ACTION_MISSING','DAG node names an absent action',node_id=node_id,action_id=aid); continue
            # Shared transport/pulses exist only once in the actual timeline.
            # This witness deliberately counts distinct local actions only.
            if aid in shared: continue
            a=actual[aid]
            if a.get('status','completed')=='completed' and a['kind'] in ('gate','measure','reset') and a['t_end_us']>a['t_start_us']:
                candidates.append((a['t_start_us'],a['t_end_us'],node_id,aid))
    active=[]
    for start,end,node,aid in sorted(candidates):
        active=[row for row in active if row[1]>start]
        for begin,finish,other,other_id in active:
            if other==node or set(node_patches[other])&set(node_patches[node]): continue
            if graph.precedes(other,node) or graph.precedes(node,other): continue
            witnesses.append({'node_ids':[other,node],'action_ids':[other_id,aid],'overlap_us':min(end,finish)-start})
        active.append((start,end,node,aid))
    if not witnesses: audit.need('PHYSICAL_PARALLELISM_NOT_DEMONSTRATED','Overlapping call intervals alone do not demonstrate independent physical work')
    audit.metrics['physical_parallel_witnesses']=witnesses
    audit.metrics['shared_physical_actions_counted_once']=len(shared)
    return witnesses
