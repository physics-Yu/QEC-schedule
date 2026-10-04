"""Independent adversarial two-device motion qualification fixtures."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import math

import pytest

from neutral_atom_kernel import KernelExecutor, Operation
from neutral_atom_kernel.model import thaw
from tools.audit_modular_aod import (CONTRACT, _certify_relative, ReviewError,
    audit, audit_modular_operations, review_input_sha256)


def profile(sites, *, overlap=False):
    return {"profile_id": "independent-small-two-device/1", "bounds_um": [-30, -30, 100, 100],
            "devices": {"AOD_0": {"rows": 2, "columns": 2, "capacity": 4, "envelope_um": [-20,-20,90 if overlap else 9,90]},
                        "AOD_MAGIC": {"rows": 2, "columns": 2, "capacity": 4, "envelope_um": [-20 if overlap else 15,-20,90,90]}},
            "declared_slm_sites_um": list(sites), "slm_grid_um": 5, "slm_origin_um": [0,0],
            "aod_axis_spacing_um": 2, "transport_clearance_um": 1,
            "load_duration_us": 15, "store_duration_us": 15,
            "move_scale_us": 200, "move_reference_um": 110, "active_axes_contract": CONTRACT}


def op(id, kind, atoms, start, duration, axes, target=None, points=(), deps=(), device="AOD_0", resources=(), metadata=None):
    md = {"source_axes": axes, "target_axes": target or axes} if kind != "WAIT" else {}
    md.update(metadata or {})
    return Operation(id, kind, tuple(atoms), duration, tuple(points), aod_id=device,
                     metadata=md, start_us=start, end_us=start+duration,
                     depends_on=tuple(deps), resources=tuple(resources))


def fixture():
    initial = {"A": (0.,0.), "B": (20.,0.)}
    axes = {"AOD_0": {"rows":[0.,5.],"columns":[0.,5.]},
            "AOD_MAGIC": {"rows":[0.,5.],"columns":[20.,25.]}}
    p = profile([(0,0),(20,0),(0,10),(20,15)])
    ops = []
    for q, device, displacement, delay in (("A","AOD_0",10,30), ("B","AOD_MAGIC",15,10)):
        a = axes[device]; b = {"rows":[y+displacement for y in a["rows"]], "columns":a["columns"]}
        travel = 200*math.sqrt(displacement/110)
        clock = 0; previous = None
        for name, kind, duration, source, target, points in (
            ("load","LOAD",15,a,a,()),
            ("out","MOVE",travel,a,b,((q,(initial[q][0],displacement)),)),
            ("park","STORE",15,b,b,()),
            ("dwell","WAIT",delay,b,b,()),
            ("reload","LOAD",15,b,b,()),
            ("back","MOVE",travel,b,a,((q,initial[q]),)),
            ("home","STORE",15,a,a,())):
            id = q+name
            ops.append(op(id,kind,[q],clock,duration,source,target,points,() if previous is None else (previous,),device,
                          (device,) if kind == "WAIT" else (), {"label":"actual dwell"} if kind == "WAIT" else {}))
            clock += duration; previous = id
    return initial, axes, p, tuple(ops)


def review(initial, axes, p, ops, **extra):
    return audit_modular_operations(initial, ops, p, initial_axes=axes, **extra)


def actual(initial, axes, ops, *, mid=False):
    k = KernelExecutor(initial, initial_aod_axes=axes)
    block = k.bind_block("independent-fixture", ops, execution_mode="scheduled")
    if mid:
        k.run(block, until_us=40)
        k = KernelExecutor.restore(k.checkpoint(include_journal=True))
        k.run()
    else:
        k.run(block)
    return thaw(k.journal), k.checkpoint(include_journal=True)


def fail(result, code):
    assert not result["passed"] and result["status"] == "FAIL", result
    assert result["failures"][0]["code"] == code, result


def test_unequal_common_cubic_concurrent_returns_and_receipt():
    initial, axes, p, ops = fixture()
    result = review(initial, axes, p, ops)
    assert result["passed"], result
    assert result["input_sha256"] == review_input_sha256(initial, ops, p, initial_axes=axes)
    from neutral_atom_strategies.scheduling.aod_modules import review_input_sha256 as runtime_digest
    assert result["input_sha256"] == runtime_digest(initial, ops, p, initial_axes=axes)
    assert result["final_reviewed_state"]["positions"] == {q:list(point) for q, point in initial.items()}
    assert set(result["final_reviewed_state"]["holders"].values()) == {"slm"}
    assert result["continuous_geometry"]["minimum_certified_lower_bound_um"] >= 1
    assert not result["actual_execution_verified"]


@pytest.mark.parametrize("mid",[False,True])
def test_actual_public_kernel_journal_and_cold_final_replay(mid):
    initial, axes, p, ops = fixture()
    journal, checkpoint = actual(initial, axes, ops, mid=mid)
    result = review(initial, axes, p, ops, journal=journal, final_checkpoint=checkpoint)
    assert result["passed"], result
    assert result["actual_execution_verified"]
    assert result["actual_execution"]["full_original_state_kernel_replay"]


def test_two_moving_carriers_collide_despite_safe_endpoints():
    initial = {"A":(0.,0.),"B":(10.,0.)}
    axes = {"AOD_0":{"rows":[0,5],"columns":[0,5]},"AOD_MAGIC":{"rows":[0,5],"columns":[10,15]}}
    p = profile([(0,0),(10,0)],overlap=True)
    time = 200*math.sqrt(10/110)
    ops=[]
    for q,device,dx in (("A","AOD_0",10),("B","AOD_MAGIC",-10)):
        source=axes[device]; target={"rows":source["rows"],"columns":[x+dx for x in source["columns"]]}
        ops.extend((op(q+"load","LOAD",[q],0,15,source,device=device),
                    op(q+"move","MOVE",[q],15,time,source,target,((q,(initial[q][0]+dx,0)),),(q+"load",),device)))
    fail(review(initial,axes,p,ops),"CONTINUOUS_COLLISION")


def test_empty_active_cartesian_cross_sweeps_static_spectator():
    initial={"A":(0.,0.),"C":(10.,10.),"S":(0.,15.),"B":(50.,0.)}
    axes={"AOD_0":{"rows":[0,10],"columns":[0,10]},"AOD_MAGIC":{"rows":[0,5],"columns":[50,55]}}
    p=profile(initial.values(),overlap=True)
    target={"rows":[10,20],"columns":[0,10]}; time=200*math.sqrt(10/110)
    ops=(op("load","LOAD",["A","C"],0,15,axes["AOD_0"]),
         op("move","MOVE",["A","C"],15,time,axes["AOD_0"],target,(("A",(0,10)),("C",(10,20))), ("load",)))
    # Neither real carrier path is within 1um of S. The empty (0,10) cell crosses S.
    fail(review(initial,axes,p,ops),"CONTINUOUS_COLLISION")


@pytest.mark.parametrize("field,value,code",[
    ("extra_active_empty_axes",True,"ACTIVE_AXES_CONTRACT"),
    ("transport_clearance_um",.5,"PROFILE_THRESHOLD"),
    ("aod_axis_spacing_um",1,"PROFILE_THRESHOLD"),
    ("move_scale_us",100,"PROFILE_THRESHOLD"),
])
def test_profile_cannot_relax_thresholds_or_invent_rf_masks(field,value,code):
    initial,axes,p,ops=fixture(); p[field]=value
    fail(review(initial,axes,p,ops),code)


def test_disabled_spare_axes_still_bounded_and_ordered():
    initial,axes,p,ops=fixture(); axes["AOD_0"]["columns"][1]=10
    fail(review(initial,axes,p,ops),"RF_ENVELOPE")
    axes["AOD_0"]["columns"][1]=1
    fail(review(initial,axes,p,ops),"RF_SPACING")


def test_extra_initial_active_axis_is_rejected():
    initial,axes,p,ops=fixture(); axes["AOD_0"]["active_rows"]=[5]
    fail(review(initial,axes,p,ops),"ACTIVE_AXES_CONTRACT")


@pytest.mark.parametrize("mutation,code",[
    ("source_axes","SOURCE_AXES"), ("source_positions","SOURCE_IDENTITY"),
    ("source_holders","SOURCE_IDENTITY"), ("target","POSITION_IDENTITY"),
    ("mask","ACTIVE_AXES_CONTRACT"), ("short_time","MOTION_DURATION"),
    ("early_dependency","DEPENDENCY_NOT_READY"), ("transfer_target","POSITION_IDENTITY"),
])
def test_source_target_dependencies_masks_and_native_timing_are_not_metadata_truth(mutation,code):
    initial,axes,p,values=fixture(); ops=list(values); index=1; o=ops[index]; md=thaw(o.metadata)
    if mutation=="source_axes": md["source_axes"]["rows"]=[0,10]; ops[index]=replace(o,metadata=md)
    if mutation=="source_positions": md["source_positions"]={"A":[1,0]}; ops[index]=replace(o,metadata=md)
    if mutation=="source_holders": md["source_holders"]={"A":"slm"}; ops[index]=replace(o,metadata=md)
    if mutation=="target": ops[index]=replace(o,positions=(("A",(0,11)),))
    if mutation=="mask": md["active_rows"]=[15]; ops[index]=replace(o,metadata=md)
    if mutation=="short_time": ops[index]=replace(o,duration_us=10,end_us=o.start_us+10)
    if mutation=="early_dependency": ops[index]=replace(o,start_us=14,end_us=14+o.duration_us)
    if mutation=="transfer_target": ops[0]=replace(ops[0],positions=(("A",(0,5)),))
    fail(review(initial,axes,p,ops),code)


def test_global_resources_conflict_across_independent_devices():
    initial,axes,p,ops=fixture()
    ops=list(ops); ops[0]=replace(ops[0],resources=("GLOBAL_TRANSFER",)); ops[7]=replace(ops[7],resources=("GLOBAL_TRANSFER",))
    fail(review(initial,axes,p,ops),"RESOURCE_CONFLICT")


def test_wait_atoms_reserve_identity_and_cannot_move_or_add_effects():
    initial,axes,p,ops=fixture()
    ops=list(ops); ops.append(op("foreign-wait","WAIT",["A"],0,20,axes["AOD_0"],metadata={"label":"reservation"}))
    fail(review(initial,axes,p,ops),"RESOURCE_CONFLICT")
    ops=ops[:-1]; ops[3]=replace(ops[3],metadata={"gate_kind":"H"})
    fail(review(initial,axes,p,ops),"PURE_TRANSPORT_SCOPE")


@pytest.mark.parametrize("kind",["RESET","MEASURE","CZ","H"])
def test_pure_transport_does_not_approve_gate_or_report_profiles(kind):
    initial,axes,p,ops=fixture(); ops=list(ops); ops[0]=replace(ops[0],kind=kind)
    fail(review(initial,axes,p,ops),"PURE_TRANSPORT_SCOPE")


@pytest.mark.parametrize("field",["changed_atoms","axes_delta","resources","end_us"])
def test_actual_end_effects_holder_axis_and_time_forgery(field):
    initial,axes,p,ops=fixture(); journal,cp=actual(initial,axes,ops)
    row=next(row for row in journal if row["event"]=="OPERATION_COMPLETED")
    if field=="changed_atoms": row[field][0][2][0]="AOD_MAGIC"
    if field=="axes_delta": row[field][2][2]=[5]
    if field=="resources": row[field]=[]
    if field=="end_us": row[field]+=1
    fail(review(initial,axes,p,ops,journal=journal,final_checkpoint=cp),"ACTUAL_EVENT_BINDING")


def test_missing_or_duplicate_end_rejected_and_actual_requires_both_inputs():
    initial,axes,p,ops=fixture(); journal,cp=actual(initial,axes,ops)
    fail(review(initial,axes,p,ops,journal=journal[:-2],final_checkpoint=cp),"ACTUAL_EVENT_IDENTITY")
    fail(review(initial,axes,p,ops,journal=journal+[journal[-2]],final_checkpoint=cp),"ACTUAL_EVENT_IDENTITY")
    fail(review(initial,axes,p,ops,journal=journal),"ACTUAL_EVENT_SCOPE")


def test_final_checkpoint_forged_complete_fields_fail_cold_replay():
    initial,axes,p,ops=fixture(); journal,cp=actual(initial,axes,ops)
    from tools.audit_modular_aod import _digest
    cp["operation_cursor"]+=1
    cp["checkpoint_digest"]=_digest({k:v for k,v in cp.items() if k!="checkpoint_digest"})
    fail(review(initial,axes,p,ops,journal=journal,final_checkpoint=cp),"INDEPENDENT_KERNEL_REPLAY")


def test_exact_bezier_certificate_finds_off_midpoint_collision_and_rejects_unresolved():
    def stats(): return {"certificate_nodes":0,"pair_partition_checks":0,"minimum_certified_lower_bound_um":math.inf}
    # Relative x is a cubic crossing zero near u=.2; midpoint/endpoints alone miss it.
    x=tuple(map(F,[-2,2,12,18])); y=(F(0),)*4
    with pytest.raises(ReviewError,match="below 1"):
        _certify_relative(x,y,stats())
    # A hull spanning the origin remains unresolved although endpoint/midpoint
    # samples are safe; a finite zero-depth budget rejects it.
    with pytest.raises(ReviewError) as error:
        _certify_relative(tuple(map(F,[-2,-1,1,2])),tuple(map(F,[2,0,2,2])),stats(),max_depth=0)
    assert error.value.code=="UNCERTIFIED_CONTINUOUS_CLEARANCE"
    assert _certify_relative((F(0),)*4,(F(1),)*4,stats())==1


def test_artifact_entrypoint_binds_all_actual_files(tmp_path):
    initial,axes,p,ops=fixture(); journal,cp=actual(initial,axes,ops)
    payloads={"initial.json":{"positions":initial,"holders":{q:"slm" for q in initial},"initial_axes":axes},
              "profile.json":p,"operations.json":[thaw({field:getattr(o,field) for field in o.__dataclass_fields__}) for o in ops],
              "journal.json":journal,"checkpoint-final.json":cp}
    for name,data in payloads.items(): (tmp_path/name).write_text(json.dumps(data),encoding="utf-8")
    result=audit(tmp_path)
    assert result["passed"],result
    assert set(result["artifact_sha256"])==set(payloads)


@pytest.mark.parametrize("key",["gate_spec","effects","enabled_rows","enabled_cols","extra_active_rows"])
def test_unsupported_effect_or_mask_metadata_is_rejected_even_if_empty(key):
    initial,axes,p,ops=fixture(); ops=list(ops)
    md=thaw(ops[1].metadata); md[key]=[]
    ops[1]=replace(ops[1],metadata=md)
    fail(review(initial,axes,p,ops),"PURE_TRANSPORT_SCOPE")


def test_move_cannot_omit_a_supported_carrier_or_hide_full_spare_motion_time():
    initial={"A":(0.,0.),"C":(5.,0.),"B":(20.,0.)}
    axes={"AOD_0":{"rows":[0,5],"columns":[0,5]},"AOD_MAGIC":{"rows":[0,5],"columns":[20,25]}}
    p=profile(initial.values()); target={"rows":[10,15],"columns":[0,5]}; time=200*math.sqrt(10/110)
    ops=(op("load","LOAD",["A","C"],0,15,axes["AOD_0"]),
         op("move","MOVE",["A"],15,time,axes["AOD_0"],target,(("A",(0,10)),),("load",)))
    fail(review(initial,axes,p,ops),"POSITION_IDENTITY")
    # A loaded atom stays fixed while the disabled y=5 spare moves to y=15.
    target={"rows":[0,15],"columns":[0,5]}
    ops=(op("load","LOAD",["A"],0,15,axes["AOD_0"]),
         op("move","MOVE",["A"],15,0,axes["AOD_0"],target,(("A",(0,0)),),("load",)))
    fail(review(initial,axes,p,ops),"MOTION_DURATION")


def test_actual_start_source_and_end_completion_are_not_producer_booleans():
    initial,axes,p,ops=fixture(); journal,cp=actual(initial,axes,ops)
    row=next(row for row in journal if row["event"]=="OPERATION_STARTED")
    row["source_axes"]["active_rows"]=[5]
    fail(review(initial,axes,p,ops,journal=journal,final_checkpoint=cp),"ACTUAL_EVENT_BINDING")

