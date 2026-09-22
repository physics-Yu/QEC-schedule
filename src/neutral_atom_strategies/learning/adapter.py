"""Event-backed decision adapter and resumable fragments, outside the simulator."""
from dataclasses import asdict, dataclass
from copy import deepcopy
from collections import Counter
import json
from math import isfinite
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from .candidates import RestoringCandidates, terminal_target


@dataclass(frozen=True)
class EpisodeConfig:
    time_limit_us: float = 100000.0
    reward_scale_us: float = 1000.0
    max_decisions: int = 1000
    ready_limit: int = 8
    candidate_budget: int = 24
    route_budget: int = 16
    planning_seconds: float = 30.0

    def __post_init__(self):
        for field in ('time_limit_us','reward_scale_us','planning_seconds'):
            value=getattr(self,field)
            if type(value) not in (int,float) or not isfinite(value) or value<=0:
                raise ValueError(f'{field} must be positive and finite')
        for field,maximum in (('max_decisions',100000),('ready_limit',8),('candidate_budget',128),('route_budget',128)):
            value=getattr(self,field)
            if type(value) is not int or not 1<=value<=maximum:
                raise ValueError(f'{field} must be an integer from 1 to {maximum}')


class DecisionEnv:
    """Private environment per episode; caller receives JSON-safe observations.

    Stage A: HXYZTCZ, idle static boundaries, finite restoring CZ actions, no
    measurement or mid-operation decisions. Fragment boundaries never reset it.
    """
    def __init__(self, initial_snapshot, config=None):
        self.config=config or EpisodeConfig()
        self._initial=initial_snapshot
        self._audit_start=initial_snapshot
        self._env=NeutralAtomEnv.restore(initial_snapshot)
        state=self._env.state
        if state.hardware.backend not in ('row_column','row_column_orthogonal'):
            raise ValueError('Stage A uses an explicitly declared ordered-axis backend')
        if not 2<=len(state.atoms)<=8 or self._env.pending or state.placement.mobile_occupancy:
            raise ValueError('Stage A requires 2–8 static atoms and an idle initial state')
        if any(g.gate_type not in {'H','X','Y','Z','T','CZ'} or g.condition for g in state.dag.circuit.gates):
            raise ValueError('Stage A supports unconditional H/X/Y/Z/T/CZ only')
        self._terminal=terminal_target(state)
        self._start=state.time_us
        self._provider=RestoringCandidates(**{k:getattr(self.config,k) for k in
            ('ready_limit','candidate_budget','route_budget','planning_seconds')})
        self._choices=None
        self._planning={}
        self._decision_count=0
        self.total_reward=0.0
        self.status='running'
        self.failure=None
        self.history=[]
        self.plans=[]  # diagnostic only; never passed to policy
        self._refresh_terminal()

    def _refresh_terminal(self):
        if self._env.state.dag.completed:
            try:
                validate_target(self._terminal,self._env.state)
                self.status='completed'
            except ValidationError:
                pass

    def _prepare(self):
        if self._choices is None and self.status=='running':
            try:
                self._choices,self._planning=self._provider.build(self._env,self._terminal)
            except (ValidationError,TimeoutError) as error:
                code=error.violation.code if isinstance(error,ValidationError) else 'PLANNING_BUDGET'
                self._choices=[]
                self._planning={'rejections':[{'code':code,'message':str(error)}],
                                'budget_exhausted':isinstance(error,TimeoutError)}

    def observe(self):
        self._prepare()
        state=self._env.state
        public=self._env.observe()
        # Explicit whitelist: no full PhysicalGate, RNG, tableau, trace, plans,
        # readout_flip, injection labels, or future measurement results.
        graph=[]
        for gid,node in sorted(state.dag.nodes.items()):
            graph.append({'id':gid,'type':node.gate.gate_type,'qubits':list(node.gate.qubit_ids),
                          'status':node.status.value,'successors':sorted(node.successors),
                          'remaining_predecessors':node.remaining_predecessors})
        atoms=[{'id':q,'position':primitive(public.positions[q]),'holder':primitive(public.holders[q])}
               for q in sorted(public.positions)]
        candidates=[dict(primitive(action),duration_us=plan.estimated_duration_us,
                         distance_um=plan.estimated_distance_um) for action,plan in (self._choices or [])]
        return {'schema':'rl-decision-v1','version':public.version,'time_us':public.time_us,
                'elapsed_us':public.time_us-self._start,'decision_count':self._decision_count,
                'status':self.status,'gates':graph,'atoms':atoms,'axes':primitive(public.aod_configuration),
                'enabled_rows':list(public.enabled_rows),'enabled_columns':list(public.enabled_columns),
                'slm_enabled':dict(public.slm_enabled),'measurement_results':dict(public.measurement_results),
                'candidates':candidates,'action_mask':[True]*len(candidates),
                'search':deepcopy({k:v for k,v in self._planning.items() if k!='planning_seconds'}),
                'reward_scale_us':self.config.reward_scale_us,
                'time_remaining_us':max(0,self.config.time_limit_us-(public.time_us-self._start)),
                'decisions_remaining':max(0,self.config.max_decisions-self._decision_count)}

    def _fail(self,code,message):
        target=-self.config.time_limit_us/self.config.reward_scale_us-1.0
        reward=target-self.total_reward
        self.total_reward=target
        self.status='failed'
        self.failure={'code':code,'message':message}
        return reward

    def step(self,action_id):
        if self.status!='running':
            raise RuntimeError('Episode has ended; construct/reset a separate episode')
        self._prepare()
        old=self._env.state.time_us
        observation=self.observe()
        planning_seconds=self._planning.get('planning_seconds',0.0)
        selected=next(((a,p) for a,p in self._choices if a.id==action_id),None)
        executed=False
        tick=perf_counter()
        if not self._choices:
            reward=self._fail('CANDIDATES_EXHAUSTED','No realized candidate in recorded finite search; not an impossibility proof')
        elif selected is None:
            reward=self._fail('INVALID_ACTION','Action ID is not in this decision candidate table')
        elif self._decision_count>=self.config.max_decisions:
            reward=self._fail('DECISION_BUDGET','Episode decision budget exhausted')
        elif old-self._start+selected[1].estimated_duration_us>self.config.time_limit_us+1e-8:
            reward=self._fail('PHYSICAL_TIME_LIMIT','Chosen full service would exceed declared episode horizon')
        else:
            try:
                self._env.submit(selected[1])
                self.plans.append(selected[1])
                self._env.run()
                executed=True
                self._decision_count+=1
                reward=-(self._env.state.time_us-old)/self.config.reward_scale_us
                self.total_reward+=reward
                self._refresh_terminal()
                if self.status=='running' and self._decision_count>=self.config.max_decisions:
                    reward+=self._fail('DECISION_BUDGET','Episode decision budget exhausted before full terminal')
            except ValidationError as error:
                reward=self._fail(error.violation.code,str(error))
        execution_seconds=perf_counter()-tick
        self._choices=None
        self._planning={}
        transition={'observation':observation,'action_id':action_id,'reward':reward,
                    'delta_time_us':self._env.state.time_us-old,'terminated':self.status!='running',
                    'truncated':False,'executed':executed,'failure':self.failure,
                    'execution_seconds':execution_seconds,'planning_seconds':planning_seconds,
                    'total_reward':self.total_reward}
        self.history.append(transition)
        return transition

    def reset(self,initial_snapshot=None):
        self.__init__(initial_snapshot or self._initial,self.config)
        return self.observe()

    def collect_fragment(self,policy,length):
        if type(length) is not int or length<1:
            raise ValueError('Fragment length must be a positive integer')
        transitions=[]
        for _ in range(length):
            if self.status!='running':break
            obs=self.observe()
            transitions.append(self.step(policy(obs)))
        final=self.observe()
        return {'transitions':transitions,'final_observation':final,
                'fragment_cut':self.status=='running','bootstrap_required':self.status=='running',
                'terminated':self.status!='running','truncated':False}

    def snapshot(self):
        """Privileged checkpoint for runner persistence, not a policy observation."""
        return {'schema':'rl-checkpoint-v1','initial':self._initial,'current':self._env.snapshot(),
                'config':asdict(self.config),'decisions':self._decision_count,'total_reward':self.total_reward,
                'status':self.status,'failure':self.failure}

    @classmethod
    def restore(cls,checkpoint):
        if checkpoint['schema']!='rl-checkpoint-v1':raise ValueError('Unsupported learning checkpoint')
        instance=cls(checkpoint['initial'],EpisodeConfig(**checkpoint['config']))
        instance._env=NeutralAtomEnv.restore(checkpoint['current'])
        instance._audit_start=checkpoint['current']
        instance._decision_count=checkpoint['decisions'];instance.total_reward=checkpoint['total_reward']
        instance.status=checkpoint['status'];instance.failure=checkpoint['failure']
        return instance

    def audit(self):
        """Independent execution of this adapter segment's submitted programs."""
        replay=NeutralAtomEnv.restore(self._audit_start)
        for plan in self.plans:
            replay.submit(plan);replay.run()
        equal=replay.snapshot()==self._env.snapshot()
        terminal=False
        if self.status=='completed':
            validate_target(self._terminal,self._env.state);terminal=True
        records=(json.loads(r) for r in self._env.state.trace.records)
        effects=Counter(g for r in records if r.get('effect_completed') for g in r.get('effect_gate_ids',[]))
        expected=Counter({gid:1 for gid,node in self._env.state.dag.nodes.items() if node.status.value=='completed'})
        return {'replay_equal':equal,'terminal_verified':terminal,'effects_once':effects==expected,'status':self.status,
                'elapsed_us':self._env.state.time_us-self._start,'total_reward':self.total_reward,
                'decisions':self._decision_count,'failure':self.failure}
