from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, EndDisposition
from neutral_atom_env.domain.errors import ValidationError


class EagerBaseline:
    def __init__(self,compiler=None):
        from neutral_atom_env.motion.compiler import MotionCompiler
        self.compiler=compiler or MotionCompiler()

    def compile_first(self,state):
        """Try the entire ready frontier in stable ID order; no live-state writes."""
        failures=[]
        for gate in state.dag.ready_gates():
            intent=ExecuteGateBatchIntent(frozenset({gate.id}),EndDisposition.RETURN_AND_OFFLOAD)
            try:
                return self.compiler.compile(intent,state),tuple(failures)
            except ValidationError as error:
                failures.append((gate.id,error.violation))
        return None,tuple(failures)

    def choose(self,state):
        gates=[g for g in state.dag.ready_gates() if g.is_two_qubit]
        if not gates:
            raise ValidationError('NO_READY_TWO_QUBIT_GATE','No logical two-qubit candidate is ready')
        return ExecuteGateBatchIntent(frozenset({gates[0].id}),EndDisposition.RETURN_AND_OFFLOAD)
