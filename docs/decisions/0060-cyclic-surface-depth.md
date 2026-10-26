# 0060: Joint cyclic depth search on a 7x7 shared bank

Status: approved; server run pending.

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
