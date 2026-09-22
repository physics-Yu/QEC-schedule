"""Small permutation-equivariant gate graph actor/critic over validated actions.

Torch is opt-in: this module is never imported by production or stage-A defaults.
"""
import torch
from torch import nn

KINDS=('H','X','Y','Z','T','CZ','CLEANUP')
STATUSES=('blocked','ready','reserved','running','completed','failed')


class GraphActorCritic(nn.Module):
    def __init__(self,hidden=32):
        super().__init__()
        self.hidden=hidden
        self.gate=nn.Linear(len(KINDS)+len(STATUSES)+3,hidden)
        self.messages=nn.ModuleList([nn.Linear(hidden*3,hidden) for _ in range(2)])
        self.actor=nn.Sequential(nn.Linear(hidden*2+len(KINDS)+8,hidden),nn.Tanh(),nn.Linear(hidden,1))
        self.critic=nn.Sequential(nn.Linear(hidden+5,hidden),nn.Tanh(),nn.Linear(hidden,1))

    def forward(self,obs):
        gates=obs['gates'];n=max(1,len(obs['atoms']))
        by_id={g['id']:i for i,g in enumerate(gates)}
        coords={a['id']:a['position'] for a in obs['atoms']}
        features=[]
        for g in gates:
            ps=[coords[q] for q in g['qubits']]
            features.append([float(g['type']==k) for k in KINDS]+[float(g['status']==s) for s in STATUSES]+
                [g['remaining_predecessors']/n,sum(p['x_um'] for p in ps)/len(ps)/100,
                 sum(p['y_um'] for p in ps)/len(ps)/100])
        h=torch.tanh(self.gate(torch.tensor(features,dtype=torch.float32)))
        outgoing=torch.zeros((len(gates),len(gates)))
        for g in gates:
            for target in g['successors']:outgoing[by_id[g['id']],by_id[target]]=1
        incoming=outgoing.T
        for layer in self.messages:
            successors=outgoing@h/outgoing.sum(1,keepdim=True).clamp_min(1)
            parents=incoming@h/incoming.sum(1,keepdim=True).clamp_min(1)
            h=torch.tanh(layer(torch.cat((h,successors,parents),dim=1)))
        remaining=torch.tensor([g['status']!='completed' for g in gates],dtype=torch.float32)
        pooled=(h*remaining[:,None]).sum(0)/remaining.sum().clamp_min(1)
        global_features=torch.tensor([remaining.sum().item()/n,
            sum(g['status']=='ready' for g in gates)/n,
            sum(obs['axes']['x_um'])/len(obs['axes']['x_um'])/100,
            sum(obs['axes']['y_um'])/len(obs['axes']['y_um'])/100,
            min(obs['time_remaining_us']/max(obs['reward_scale_us'],1)/100,1)],dtype=torch.float32)
        value=self.critic(torch.cat((pooled,global_features))).squeeze()
        inputs=[]
        for action in obs['candidates']:
            ids=[by_id[g] for g in action['gate_ids']]
            selected=h[ids].mean(0) if ids else h.new_zeros(self.hidden)
            points=[(a[3],a[4]) for a in action['assignments']]
            count=len(ids)
            scalars=[count/n,action['duration_us']/obs['reward_scale_us'],action['distance_um']/100,
                     action['duration_us']/obs['reward_scale_us']/max(1,count),
                     sum(len(gates[i]['successors']) for i in ids)/n,
                     sum(p[0] for p in points)/max(1,len(points))/100,
                     sum(p[1] for p in points)/max(1,len(points))/100,float(bool(ids))]
            inputs.append(torch.cat((pooled,selected,torch.tensor(
                [float(action['kind']==k) for k in KINDS]+scalars,dtype=torch.float32))))
        logits=self.actor(torch.stack(inputs)).squeeze(-1) if inputs else h.new_empty(0)
        if inputs:
            mask=torch.tensor(obs['action_mask'],dtype=torch.bool)
            logits=logits.masked_fill(~mask,float('-inf'))
        return logits,value

    def choose(self,obs,deterministic=False):
        with torch.no_grad():
            logits,value=self(obs)
            if not logits.numel():return None,0.,float(value)
            dist=torch.distributions.Categorical(logits=logits)
            index=logits.argmax() if deterministic else dist.sample()
            return int(index),float(dist.log_prob(index)),float(value)


def gae(rewards,values,terminated,bootstrap,lam=.95):
    """gamma=1: total physical time objective, not per-decision discounting."""
    if not (len(rewards)==len(values)==len(terminated)):raise ValueError('GAE lengths differ')
    result=[0.]*len(rewards);advantage=0.;next_value=bootstrap
    for i in reversed(range(len(rewards))):
        continuation=0. if terminated[i] else 1.
        delta=rewards[i]+continuation*next_value-values[i]
        advantage=delta+continuation*lam*advantage
        result[i]=advantage
        next_value=values[i]
    return result,[a+v for a,v in zip(result,values)]


class NeuralPolicy:
    """Loaded policy for DecisionEnv.collect_fragment; no production registry."""
    def __init__(self,model,deterministic=True):
        self.model=model.eval()
        self.deterministic=deterministic

    @classmethod
    def load(cls,path,deterministic=True):
        saved=torch.load(path,map_location='cpu',weights_only=True)
        if saved['schema']!='rl-graph-ppo-v1':raise ValueError('Unsupported policy checkpoint')
        model=GraphActorCritic(saved['hidden']);model.load_state_dict(saved['weights'])
        return cls(model,deterministic)

    def __call__(self,observation):
        index,_,_=self.model.choose(observation,self.deterministic)
        return observation['candidates'][index]['id'] if index is not None else None


def ppo_update(model,optimizer,samples,epochs=4,clip=.2,entropy_weight=.01):
    advantages=torch.tensor([s['advantage'] for s in samples])
    advantages=(advantages-advantages.mean())/advantages.std(unbiased=False).clamp_min(1e-6)
    losses=[]
    for _ in range(epochs):
        actor=[];critic=[];entropies=[]
        for i,sample in enumerate(samples):
            logits,value=model(sample['observation'])
            critic.append((value-sample['return'])**2)
            if sample['index'] is None:continue
            dist=torch.distributions.Categorical(logits=logits)
            logp=dist.log_prob(torch.tensor(sample['index']))
            ratio=(logp-sample['logp']).exp()
            actor.append(-torch.minimum(ratio*advantages[i],ratio.clamp(1-clip,1+clip)*advantages[i]))
            entropies.append(dist.entropy())
        loss=(torch.stack(actor).mean() if actor else torch.tensor(0.))+.5*torch.stack(critic).mean()
        if entropies:loss=loss-entropy_weight*torch.stack(entropies).mean()
        if not torch.isfinite(loss):raise FloatingPointError('Nonfinite PPO loss')
        optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),.5);optimizer.step()
        losses.append(float(loss.detach()))
    return sum(losses)/len(losses)
