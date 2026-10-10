"""Reporting and Pauli algebra for static semantic audits (no state backend)."""
from .checker import _hash


class SemanticAudit:
    def __init__(self, subject, program):
        self.subject, self.program = subject, program
        self.failures, self.unverified, self.checks, self.metrics = [], [], [], {}

    def require(self, condition, code, message, source_id=None):
        if not condition:
            self.failures.append({"code": code, "message": message, "source_id": source_id})

    def check(self, name, fn):
        before = len(self.failures)
        try:
            fn()
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError) as exc:
            self.failures.append({"code": "SEMANTIC_INPUT_UNSUPPORTED", "message": str(exc), "source_id": name})
        self.checks.append({"id": name, "status": "passed" if len(self.failures) == before else "failed"})

    def report(self):
        return {"schema_version": "SemanticValidationReport/0.1.0", "artifact_id": f"semantic/{self.subject}/{_hash(self.program)[:16]}",
                "provenance": {"producer": "R6", "task": "T602", "kb_revision": "kb-0004", "method": "independent_static_algebra"},
                "input_sha256": _hash(self.program), "input_schema_version": self.program.get("schema_version"),
                "passed": not self.failures and not self.unverified, "scoped_pass": not self.failures,
                "checks": self.checks, "failures": self.failures, "unverified": self.unverified, "metrics": self.metrics,
                "quantum_state_simulated": False, "hardware_executed": False, "sampled": False,
                "out_of_scope": ["quantum_state_execution", "outcome_probability", "noise", "fault_tolerance", "physical_schedule", "full_Shor_physical_integration", "factory_protocol_until_reviewed"]}


def symplectic(a, b):
    return ((a[0] & b[1]).bit_count() + (a[1] & b[0]).bit_count()) % 2


def multiply(a, b):
    """i^p X^x Z^z, with all X factors ordered before all Z factors."""
    return a[0]^b[0], a[1]^b[1], (a[2]+b[2]+2*(a[1]&b[0]).bit_count()) % 4


def conjugate(pauli, gate, indices):
    x,z,p=pauli
    q=indices[0]; bit=1<<q
    if gate=='H':
        p+=2*bool(x&bit)*bool(z&bit)
        if bool(x&bit)!=bool(z&bit): x^=bit; z^=bit
    elif gate=='CX':
        c,t=indices
        if x&(1<<c): x^=1<<t
        if z&(1<<t): z^=1<<c
    elif gate=='CZ':
        c,t=indices
        p+=2*((x>>c)&1)*((x>>t)&1)
        z^=((x>>c)&1)<<t
        z^=((x>>t)&1)<<c
    elif gate in ('X','Z'):
        p+=2*bool((z if gate=='X' else x)&bit)
    elif gate in ('S','SDG'):
        if x&bit: p+=1 if gate=='S' else -1; z^=bit
    else:
        raise ValueError(f'unsupported static Clifford gate {gate}')
    return x,z,p%4


def span_basis(values):
    pivots={}
    for value in values:
        while value:
            pivot=value.bit_length()-1
            if pivot in pivots: value ^= pivots[pivot]
            else: pivots[pivot]=value; break
    return pivots


def in_span(value, pivots):
    while value:
        pivot=value.bit_length()-1
        if pivot not in pivots: return False
        value ^= pivots[pivot]
    return True
