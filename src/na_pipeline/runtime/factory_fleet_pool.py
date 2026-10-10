"""One finite world, independent factory epochs, shared target exclusions."""
from copy import deepcopy
from .resource_pool import FiniteResourcePool
from .errors import fail


class FactoryFleetPool(FiniteResourcePool):
    def __init__(self,requirements,initial_state):
        super().__init__(requirements,initial_state)
        if not requirements.get('factories'):fail('FLEET_RESOURCE_SCHEMA','Explicit factory line inventory required')
        self.line_epochs={f:0 for f in requirements['factories']}

    def epoch_for(self,factory_id):
        if factory_id not in self.line_epochs:fail('FLEET_UNKNOWN_LINE','Unknown factory line')
        return self.line_epochs[factory_id]

    def acquire_production(self,owner,factory_id,session):
        epoch=self.epoch_for(factory_id);line=self.requirements['factories'][factory_id]
        if owner in self.used_owners:fail('POOL_LEASE_IDENTITY','Producer owner must be unique')
        if {a['qubit_id']:a['atom_id'] for a in session.snapshot()['world_state']['atoms']}!=self.qubit_to_atom:
            fail('POOL_CARRIER_REPLACED','All factory and data carriers must remain in the shared world')
        resources=line['exclusive_resources'];occupied={r for lease in self.active.values() for r in lease['resources']}
        if occupied & set(resources):fail('POOL_RESOURCE_BUSY','This production line is still occupied')
        lease={'owner':owner,'operation':'T','purpose':'produce_A_plus','factory_id':factory_id,
            'target_patch':None,'resources':list(resources),'epoch':epoch,'acquired_us':session.now_us,
            'session_run_id':session.run_id,'entry_revision':session.revision,'entry_plan_count':session.submitted_plan_count,
            'requirements_hash':self.requirements_hash,'ready_magic_token':None,'target_protection_intervals':[]}
        self.active[owner]=lease;self.used_owners.add(owner);self.next_epoch+=1;self.line_epochs[factory_id]+=1
        self.history.append({'event':'acquire',**deepcopy(lease)})
        return deepcopy(lease)

    def snapshot(self):
        value=super().snapshot();value['factory_epochs']=dict(self.line_epochs);return value

    @classmethod
    def restore(cls,requirements,initial_state,data):
        obj=super().restore(requirements,initial_state,data)
        epochs=data.get('factory_epochs')
        expected={f:sum(r['event']=='acquire' and r.get('factory_id')==f for r in obj.history) for f in obj.line_epochs}
        if epochs!=expected:fail('FLEET_EPOCH_HISTORY','Factory epochs differ from real acquisitions')
        obj.line_epochs=dict(epochs);return obj
