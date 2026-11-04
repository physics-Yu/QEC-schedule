# 0060: Joint cyclic depth search on a 7x7 shared bank

Status: completed; depth 4/5 UNSAT and depth 6 SAT on the frozen 7x7 bank.

Keep the fixed four N/Z interaction layers and the initially idle free placement.
Expand the bank to 7 by 7 double-trap cells (98 SLM traps). Add `cyclic=true` to
the depth problem: every atom's final x/y coordinates equal its own initial
coordinates. The LOAD/MOVE/STORE normal form ends every move in SLM with the
AOD inactive, so identical coordinates restore the complete physical entry.
The independent witness checker and Atom IR lowerer both enforce this equality.

The solver jointly chooses the initial placement and all movement states; no
placement from the previous open-path result is fixed. Default `cyclic=false`
retains the previous open search. No symmetry-breaking constraint fixes an atom
to a location or assumes the answer is greater than four.

Search on the server in increasing exact MOVE depths 4 through 8, beginning
with the requested depth 4. The depth-4 check has at most 60 seconds; subsequent
checks share the remaining 7200-second total wall deadline. Stop at the first
validated SAT schedule. Optimality requires UNSAT at every searched lower depth;
UNKNOWN is not a lower-bound proof. For this initially idle four-pulse problem,
depths below 4 are excluded by the already stated gate-stage bound.

Depth 8 has a constructive feasible upper bound: the earlier open four-MOVE
solution fits within the 7x7 bank, and reversing its four movements restores
the initial state. This is only a reference certificate; its positions or groups
are not constraints on the new joint search. Source, Device, input and result
hashes are frozen separately from the earlier campaign.

This experiment closes the gate-phase physical layout only. It still omits
ancilla readout and readout transport. It must not be reported as the complete
measurement/reset cycle needed for repeated syndrome extraction.

## Server outcome

The server stopped after 76.204 seconds of the 7200-second total budget. Z3
reported UNSAT at depth 4 (0.271 s) and depth 5 (69.329 s), then SAT at depth 6
(1.376 s). Independent validation and re-lowering of the saved witness passed.
Every atom returns to its own selected initial SLM site and the AOD is empty.
The minimum MOVE depth is therefore 6 within the declared model.

The four gate layers occur at states 2, 3, 4 and 5. The first two moves prepare
the first gate layer; moves 3/4/5 prepare the next layers; move 6 restores the
initial layout. Carrier counts are 5/8/9/9/7/6. There are six LOAD, six MOVE and
six STORE actions, with 44 atom loads and stores each. The emitted duration is
332.303 us (transport 300.863 us); time was not optimized.

Evidence: `modules/physical_compiler/artifacts/surface-d3-depth-cyclic7/`.
Manifest: `a072d1a57ab1a48a0de604181e6cdfcacaf94cb51aaa126be5ba0b0e9bf9da7e`.
Server originals: `/home/yyq/nadit-experiments/surface-d3-depth-cyclic7-a072d1a5`.
Seven fast tests and one slow test passed, along with scoped lint/type checks.
No existing test assertion was weakened. No commit was made.

The live local runner changed after freezing (terminal-task replay guards were
removed). That change was preserved; verification used the uploaded source
archive, whose bytes match the server manifest, rather than overwriting live code.
