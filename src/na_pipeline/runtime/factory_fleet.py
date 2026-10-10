"""Demand, inventory and work-frontier interface for independent A+ producers.

The fleet does not pretend that separate lines have separate lasers/AODs.
It offers the complete ready frontier to one physical scheduler; only actual
submitted events may advance a producer or complete a T consumer.
"""
from copy import deepcopy
from math import hypot,isfinite
from pathlib import Path
from hashlib import sha256
from na_pipeline.qec.factory import build_factory_producer
from .factory_session import FactoryExecution
from .factory_fleet_pool import FactoryFleetPool
from .factory_ports import FactoryDataInterface,data_surface_port
from .engine import digest
from .errors import fail


class FactoryFleet:
    def __init__(self,session,requirements,*,reserve_ready=None,logical_scheduler=None):
        self.session=session;self.pool=FactoryFleetPool(requirements,session.initial_state)
        self.lines={f:None for f in requirements['factories']}
        self.reserve_ready=len(self.lines) if reserve_ready is None else reserve_ready
        if type(self.reserve_ready) is not int or not 0<=self.reserve_ready<=len(self.lines):
            fail('FLEET_BUFFER_LIMIT','Ready target is bounded by physical output capacity')
        self.requests={};self.history=[];self.completed=[];self.revision=0
        self.logical_scheduler=logical_scheduler

    def enqueue_logical_ready(self,logical_frames):
        scheduler=self.logical_scheduler
        if scheduler is None:fail('FLEET_LOGICAL_SCHEDULER','Attach the calling logical scheduler first')
        scheduler.advance(self.session.now_us)
        scheduler.commit_ready_skips()
        enqueued=[]
        for nid in scheduler.ready_set():
            node=scheduler.nodes[nid]
            if node['operation'] not in ('T','TDG') or nid in self.requests:continue
            target=node['patch_operands']['block']
            if target not in logical_frames:fail('FLEET_INPUT_CONTRACT','Declare the current frame for every ready data target')
            enqueued.append(self.request(nid,target,gate=node['operation'],condition=node['condition'],
                encoded_state_ref=nid,logical_frame=logical_frames[target],logical_source=node))
        return enqueued

    def _boundary(self):
        if self.session.queue or self.session.pending_results or self.session.snapshot()['in_flight']:
            fail('FLEET_COMMITTED_BOUNDARY','Frontier changes require a committed physical boundary')

    def request(self,request_id,target_patch,*,gate='T',priority=0,not_before_us=0.,deadline_us=None,
                condition=None,encoded_state_ref,logical_frame,logical_source=None):
        if not isinstance(request_id,str) or not request_id or request_id in self.requests:
            fail('FLEET_REQUEST_ID','Each logical demand has one unique request identity')
        if gate not in ('T','TDG') or self.pool.requirements['patches'].get(target_patch,{}).get('role')!='algorithm':
            fail('FLEET_REQUEST_TARGET','T/TDG requires an existing algorithm data patch')
        if logical_frame!='identity' or not isinstance(encoded_state_ref,str) or not encoded_state_ref:
            fail('FLEET_INPUT_CONTRACT','Declare an encoded input and resolve its logical frame before consumption')
        if type(priority) is not int or type(not_before_us) not in (int,float) or not isfinite(not_before_us) or not_before_us<0 or (deadline_us is not None and (type(deadline_us) not in (int,float) or not isfinite(deadline_us) or deadline_us<not_before_us)):
            fail('FLEET_REQUEST_TIME','Finite release/deadline times and integer priority required')
        if condition is not None and (not isinstance(condition,dict) or set(condition)!= {'bit','equals'} or type(condition['equals']) is not int or condition['equals'] not in (0,1)):
            fail('FLEET_CONDITION','A condition must name a published result and expected bit')
        if logical_source is not None:
            if logical_source.get('operation')!=gate or logical_source.get('patch_operands',{}).get('block')!=target_patch or logical_source.get('condition')!=condition:
                fail('FLEET_LOGICAL_SOURCE','Request must preserve its original operation, target and condition')
        row={'schema_version':'MagicDemand/0.1','request_id':request_id,'target_patch':target_patch,'gate':gate,
            'priority':priority,'sequence':len(self.requests),'not_before_us':not_before_us,'deadline_us':deadline_us,
            'condition':deepcopy(condition),'encoded_state_ref':encoded_state_ref,'logical_frame':logical_frame,
            'logical_source':deepcopy(logical_source),'status':'pending','submitted_us':self.session.now_us}
        self.requests[request_id]=row;self.revision+=1
        return deepcopy(row)

    def cancel(self,request_id):
        row=self.requests[request_id]
        if row['status']!='pending':fail('FLEET_REQUEST_ALREADY_CLAIMED','Only unreserved demand can be cancelled')
        row.update(status='cancelled',completed_us=self.session.now_us);self.revision+=1

    def start_idle(self):
        """Start disjoint producer leases; this creates no actions or tokens."""
        self._boundary()
        supply=sum(c is not None and c.stage_id not in ('consume','consume_correction','consume_cleanup') for c in self.lines.values())
        pending=sum(r['status']=='pending' for r in self.requests.values())
        wanted=min(len(self.lines),pending+self.reserve_ready)
        started=[]
        for fid,c in self.lines.items():
            if c is not None or supply>=wanted:continue
            epoch=self.pool.epoch_for(fid);batch='batch-'+digest({'run':self.session.run_id,'factory':fid,'epoch':epoch})[:24]
            protocol=build_factory_producer(factory_id=fid,epoch=epoch,batch_id=batch)
            owner=fid+':epoch:'+str(epoch)
            self.lines[fid]=FactoryExecution(protocol,self.pool,self.session,owner=owner)
            started.append({'factory_id':fid,'epoch':epoch,'owner':owner,'target_patch':None});supply+=1
        self.history.extend({'event':'production_started','time_us':self.session.now_us,**r} for r in started)
        self.revision+=bool(started)
        return started

    def publish_ready(self):
        self._boundary();published=[]
        for fid,c in self.lines.items():
            if c is not None and c.stage_id=='ready':
                c.advance_lifecycle();port=FactoryDataInterface(c).output_port()
                self.history.append({'event':'output_ready','factory_id':fid,'time_us':self.session.now_us,'output':port})
                published.append(port)
        self.revision+=bool(published);return published

    def abort_production(self,factory_id):
        """Cancel speculative unfinished work through real factory cleanup."""
        self._boundary();c=self.lines[factory_id]
        if c is None or c.token is not None or c.accepted is True:
            fail('FLEET_ABORT_STATE','Only an unfinished, unaccepted producer may enter abort cleanup')
        c.lifecycle.append({'event':'production_abort_requested','time_us':self.session.now_us,'from_stage':c.stage_id})
        c.accepted=False;c.stage_id='reject_cleanup';c.graph=None;self.revision+=1

    def inventory(self):
        return [{**FactoryDataInterface(c).output_port(),'factory_id':fid} for fid,c in self.lines.items()
                if c is not None and c.stage_id=='reserve_delivery' and c.token and c.token['status']=='ready']

    def available_data_patches(self):
        occupied={r for lease in self.pool.active.values() for r in lease['resources']}
        return sorted(p for p,spec in self.pool.requirements['patches'].items() if spec['role']=='algorithm' and p not in occupied)

    def _eligible(self,row):
        if row['status']!='pending' or row['not_before_us']>self.session.now_us:return False
        cond=row['condition']
        if cond:
            result=self.session.results.get(cond['bit'])
            if result is None or result['ready_us']>self.session.now_us:return False
            row['condition_evidence']=deepcopy(result)
            if result['value']!=cond['equals']:
                row.update(status='skipped',completed_us=self.session.now_us);return False
        return True

    def assign_ready(self):
        """Priority/deadline then FIFO; select an available same-carrier output."""
        self._boundary();self.publish_ready();assigned=[]
        if self.logical_scheduler is not None:self.logical_scheduler.advance(self.session.now_us)
        ordered=sorted(self.requests.values(),key=lambda r:(-r['priority'],r['deadline_us'] if r['deadline_us'] is not None else float('inf'),r['sequence']))
        for row in ordered:
            if not self._eligible(row):
                if row['status']=='skipped' and self.logical_scheduler is not None:self.logical_scheduler.commit_ready_skips()
                continue
            if self.logical_scheduler is not None and row['logical_source'] is not None:
                if row['logical_source']['id'] not in self.logical_scheduler.ready_set():continue
                if row['logical_source']!=self.logical_scheduler.nodes[row['logical_source']['id']]:
                    fail('FLEET_LOGICAL_SOURCE','Queued logical source changed before reservation')
            occupied={r for lease in self.pool.active.values() for r in lease['resources']}
            if row['target_patch'] in occupied:continue
            ports=self.inventory()
            if not ports:break
            target=data_surface_port(self.session,self.pool,row['target_patch'],encoded_state_ref=row['encoded_state_ref'],logical_frame=row['logical_frame'])
            world={a['atom_id']:a for a in self.session.snapshot()['world_state']['atoms']}
            point=target['sites']['d0']['position_um']
            def score(p):
                positions=[world[a]['position_um'] for a in p['atom_ids']]
                center=[sum(x[i] for x in positions)/len(positions) for i in (0,1)]
                return (p['ready_us'],hypot(point[0]-center[0],point[1]-center[1]),p['factory_id'])
            chosen=min(ports,key=score);fid=chosen['factory_id'];c=self.lines[fid];api=FactoryDataInterface(c)
            reservation=api.reserve(api.output_port(),target,request_id='consumer-'+digest(row['request_id'])[:24],gate=row['gate'],logical_source=row['logical_source'])
            row.update(status='reserved',factory_id=fid,epoch=c.protocol['epoch'],token_id=c.token['token_id'],
                reservation=reservation,reserved_us=self.session.now_us,deadline_missed_at_assignment=row['deadline_us'] is not None and self.session.now_us>row['deadline_us'])
            if self.logical_scheduler is not None and row['logical_source'] is not None:
                self.logical_scheduler.advance(self.session.now_us)
                self.logical_scheduler.begin_magic_consumption(row['logical_source']['id'],c.protocol,c.consumer_protocol,c.lease,c.token,reservation)
            record={'event':'consumer_reserved','request_id':row['request_id'],'factory_id':fid,
                'token_id':c.token['token_id'],'target_patch':row['target_patch'],'gate':row['gate'],'time_us':self.session.now_us,
                'delivery_ranking':'oldest_ready_then_distance_proxy; physical transport is still compiled'}
            self.history.append(record);assigned.append(deepcopy(record))
        self.revision+=bool(assigned);return assigned

    def frontier(self):
        """All ready lines at once. One shared physical scheduler owns legality."""
        self._boundary();self.publish_ready();work=[]
        for fid,c in self.lines.items():
            if c is None or c.terminal is not None or c.stage_id=='reserve_delivery':continue
            graph=c.next_graph()
            work.append({'schema_version':'FactoryWork/0.1','factory_id':fid,'owner':c.owner,'epoch':c.protocol['epoch'],
                'stage_id':c.stage_id,'session_revision':self.session.revision,'physical_dag':graph,
                'work_id':digest({'owner':c.owner,'stage':c.stage_id,'dag':graph,'revision':self.session.revision}),
                'source_mode':'independent_producer' if not c.stage_id.startswith('consume') else 'data_consumer',
                'requires_shared_device_schedule':True})
        return work

    def compile_frontier(self,prepare_batch,*,additional_dags=()):
        """prepare_batch receives the whole frontier, never one hidden line."""
        work=self.frontier()
        if not work and not additional_dags:return {'work':[],'prepared':None}
        dags=[w['physical_dag'] for w in work]+list(additional_dags)
        prepared=prepare_batch(dags,self.session)
        if prepared['physical_plan']['physical_dags']!=dags:
            fail('FLEET_BATCH_SOURCE','Shared compiler must retain every selected line DAG')
        self.session.validate_context(prepared['context'])
        from na_pipeline.validation.dag_physical import validate_physical_plan
        report=validate_physical_plan(prepared['physical_plan'],self.session.device)
        published=prepared['context'].get('published_results',{})
        failures=[f for f in report['failures'] if not (f['code']=='RESULT_UNKNOWN' and f.get('resource') in published)]
        if failures:fail('FLEET_SHARED_DEVICE_PLAN','Joint source/geometry/resource checks failed: '+str(failures[:2]))
        prepared['fleet_static_validation']=report
        return {'work':work,'prepared':prepared}

    def commit(self,work,plan,atom_program,*,allow_other_work=False):
        """Commit only actual, completed shared-session events; no fake ready API."""
        self._boundary()
        if not work:
            if not allow_other_work or not any(p['plan_hash']==digest(atom_program) for p in self.session.plans):
                fail('FLEET_PLAN_NOT_SUBMITTED','Data-only work must still be actually submitted and committed')
            return []
        if len({w['factory_id'] for w in work})!=len(work):fail('FLEET_WORK_ALIAS','Select each producer at most once per frontier')
        expected=[w['physical_dag'] for w in work]
        if (not allow_other_work and plan.get('physical_dags')!=expected) or any(d not in plan.get('physical_dags',[]) for d in expected):
            fail('FLEET_BATCH_SOURCE','Plan differs from selected work')
        joint=len(plan['physical_dags'])>1
        controllers=[]
        for w in work:
            c=self.lines.get(w['factory_id'])
            if c is None or c.owner!=w['owner'] or c.protocol['epoch']!=w['epoch'] or c.stage_id!=w['stage_id']:
                fail('FLEET_STALE_WORK','Work belongs to a previous stage/epoch')
            if atom_program.get('session_binding',{}).get('execution_context',{}).get('revision')!=w['session_revision']:
                fail('FLEET_STALE_FRONTIER','Plan did not bind the selected physical frontier')
            c.validate_submission(plan,atom_program,joint=joint);controllers.append(c)
        if not any(p['plan_hash']==digest(atom_program) for p in self.session.plans):
            fail('FLEET_PLAN_NOT_SUBMITTED','A frontier cannot complete without this exact submitted plan')
        if any(self.session.events.get(a['id'],{}).get('status') not in ('completed','skipped') for a in atom_program['actions']):
            fail('FLEET_ACTIONS_NOT_COMMITTED','Every shared action must have reached its real terminal event')
        if any(r not in self.session.results or self.session.results[r]['ready_us']>self.session.now_us for c in controllers for r in c.graph['result_producers']):
            fail('FLEET_RESULTS_NOT_READY','All selected producer results must actually be ready')
        receipts=[c.commit_stage(plan,atom_program,joint=joint) for c in controllers]
        if self.logical_scheduler is not None:
            for c,receipt in zip(controllers,receipts,strict=True):
                source=getattr(c,'consumer_protocol',{}).get('fleet_logical_source')
                if source is not None:
                    own=set(receipt['action_ids'])
                    intervals=[{**v,'share_key':v['action_id']} for v in plan['resource_intervals'] if v['action_id'] in own]
                    self.logical_scheduler.record_protocol_stage(source['id'],{'resource_intervals':intervals},receipt,
                        origin_us=atom_program['session_binding']['time_origin_us'])
            self.logical_scheduler.advance(self.session.now_us)
        for w,c,receipt in zip(work,controllers,receipts,strict=True):
            self.history.append({'event':'stage_committed','factory_id':w['factory_id'],'receipt':receipt})
            logical_source=getattr(c,'consumer_protocol',{}).get('fleet_logical_source')
            if c.terminal is not None:
                ledger=c.snapshot();self.completed.append(ledger)
                if c.terminal=='consumed':
                    request=next((r for r in self.requests.values() if r.get('token_id')==c.token['token_id']),None)
                    if request is None:fail('FLEET_CONSUMER_OWNER','Consumed token has no matching original demand')
                    request.update(status='completed',completed_us=self.session.now_us,completion_ledger_hash=digest(ledger))
                    if self.logical_scheduler is not None and logical_source is not None:
                        self.logical_scheduler.complete_magic_consumption(logical_source['id'],ledger)
                self.lines[w['factory_id']]=None
        if self.logical_scheduler is not None:self.logical_scheduler.advance(self.session.now_us)
        self.revision+=1;self.publish_ready();return deepcopy(receipts)

    def snapshot(self):
        return {'schema_version':'FactoryFleet/0.1','run_id':self.session.run_id,'revision':self.revision,'time_us':self.session.now_us,
            'reserve_ready':self.reserve_ready,'lines':{f:c.snapshot() if c else None for f,c in self.lines.items()},
            'requests':deepcopy(self.requests),'ready_inventory':self.inventory(),'pool':self.pool.snapshot(),
            'history':deepcopy(self.history),'completed_attempts':deepcopy(self.completed),
            'maximum_ready_inventory':len(self.lines),'quantum_state_simulated':False,'hardware_executed':False,'sampled':False,
            'metrics':{'physical_carriers':len(self.pool.qubit_to_atom),'factory_carriers':120*len(self.lines),
                'allocated_factory_carriers':120*sum(c is not None for c in self.lines.values()),
                'pending_requests':sum(r['status']=='pending' for r in self.requests.values()),
                'completed_requests':sum(r['status']=='completed' for r in self.requests.values()),
                'request_wait_us':{r['request_id']:r.get('reserved_us',self.session.now_us)-r['submitted_us'] for r in self.requests.values() if r['status'] not in ('skipped','cancelled')}},
            'physical_concurrency':'only the actual shared compiled plan may claim overlapping device operations'}

    @staticmethod
    def _sources():
        root=Path(__file__).resolve().parent
        return {n:sha256((root/n).read_bytes()).hexdigest() for n in
            ('factory_fleet.py','factory_fleet_pool.py','factory_session.py','factory_ports.py','resource_pool.py')}

    def checkpoint(self):
        fields=('owner','stage_id','receipts','decisions','lifecycle','graph','accepted','token','terminal','lease')
        controllers={}
        for fid,c in self.lines.items():
            if c is None:controllers[fid]=None;continue
            controllers[fid]={'protocol':deepcopy(c.protocol),**{k:deepcopy(getattr(c,k)) for k in fields}}
            for key in ('consumer_protocol','consumer_binding'):
                if hasattr(c,key):controllers[fid][key]=deepcopy(getattr(c,key))
        body={'schema_version':'FactoryFleetCheckpoint/0.1','requirements':deepcopy(self.pool.requirements),
            'initial_state':deepcopy(self.session.initial_state),'session':self.session.checkpoint(),'pool':self.pool.snapshot(),
            'reserve_ready':self.reserve_ready,'revision':self.revision,'requests':deepcopy(self.requests),
            'history':deepcopy(self.history),'completed':deepcopy(self.completed),'controllers':controllers,'source_hashes':self._sources(),
            'logical_scheduler':self.logical_scheduler.checkpoint() if self.logical_scheduler is not None else None}
        return {'body':body,'sha256':digest(body)}

    @classmethod
    def restore(cls,device,checkpoint,*,archive_root=None,logical_dag=None,decision_root=None):
        from .session import EventSession
        body=checkpoint['body']
        if body.get('schema_version')!='FactoryFleetCheckpoint/0.1' or checkpoint['sha256']!=digest(body) or body['source_hashes']!=cls._sources():
            fail('FLEET_CHECKPOINT_IDENTITY','Fleet checkpoint/source identity changed')
        session=EventSession.restore(device,body['session'],archive_root=archive_root)
        obj=cls(session,body['requirements'],reserve_ready=body['reserve_ready'])
        obj.pool=FactoryFleetPool.restore(body['requirements'],body['initial_state'],body['pool'])
        obj.revision=body['revision'];obj.requests=deepcopy(body['requests']);obj.history=deepcopy(body['history']);obj.completed=deepcopy(body['completed'])
        if body.get('logical_scheduler'):
            if logical_dag is None:fail('FLEET_LOGICAL_SCHEDULER','Restoring attached logical work requires its original DAG')
            from .logical_scheduler import LogicalListScheduler
            obj.logical_scheduler=LogicalListScheduler.restore(logical_dag,body['logical_scheduler'],decision_root=decision_root)
        for fid,record in body['controllers'].items():
            if record is None:continue
            c=FactoryExecution.__new__(FactoryExecution)
            for key,value in record.items():setattr(c,key,deepcopy(value))
            c.session=session;c.pool=obj.pool
            effective=getattr(c,'consumer_protocol',c.protocol)
            c.live_atoms={obj.pool.qubit_to_atom[q] for q in effective['live_data_information_qubit_ids']}
            c.output_atoms=[obj.pool.qubit_to_atom[q] for q in c.protocol['output']['qubit_ids']]
            c.output_data={obj.pool.qubit_to_atom[q] for q in c.protocol['output']['qubit_ids'] if '/d' in q}
            obj.lines[fid]=c
        return obj
