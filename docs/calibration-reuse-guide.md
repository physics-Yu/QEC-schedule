# Which calibrations survive adding a factory?

In `22456ff`, decide reuse **per saved component record**. For an existing component, adding a factory changes the full placement fingerprint. Its calibration can still match if the added blocks fall outside its declared local influence envelope and every other field of its applicability key stays equal. A world-scoped record includes all spectators, so adding those blocks changes its key. [Design decision](decisions/0056-logical-placement-and-calibration-context.md)

## 1. Predict two outcomes before opening the implementation

Start with the existing component and keep its participants, parameters and device settings fixed. Add one factory far outside the component's envelope. Predict the result under each scope, then move one spectator block and predict again.

| Change to the original lookup | Expected outcome | Deciding observation |
| --- | --- | --- |
| Add the distant factory, local scope | Hit the original record | The full plan fingerprint changes, but the local key stays equal. |
| Add the same factory, world scope | The old key no longer matches | Even the distant blocks enter the spectator list. |
| Move a spectator within the local envelope | Miss | Its position relative to the first participant changes, even though the participant stays put. |

## 2. Trace one lookup to the owner of each decision

1. **Where are the blocks?** The code provider supplies footprints and allowed orientations. Placement returns a validated `PlacementPlan` with block poses and a fingerprint for the whole layout. [Placement contract](../modules/logical_compiler/docs/placement.md)
2. **Which surroundings matter?** The d=3 fast provider's `component_context` explicitly selects `local`. It builds an envelope from participant footprints and the component's declared spaces, and describes relevant control, transport and readout conditions. This locality is a versioned model assumption. [d=3 provider](../modules/codes/rotated_surface_d3/protocols/fast_context.py)
3. **Who decides and consumes a match?** The generic `calibration_context` defaults to `world`. It builds the key from component identity/version, parameters and selection, participant-relative geometry, device context and scoped spectators. The fast runtime binds the profile to a layout. Its `BoundFastProfile.lookup` queries the cache and reports `MissingCalibration` for a missing production record. Recalibration is a separate operation. [Key and cache](../modules/logical_compiler/src/estimation/calibration.py) · [Bound lookup](../modules/codes/rotated_surface_d3/protocols/fast_applicability.py)

## 3. Check the prediction through a consumer

Look up `logical_x` on W1 in factory 0 of a one-factory layout, then on W1 in factory 2 of a three-factory horizontal layout. With the same applicable record, both calls to `BoundFastProfile.lookup` should return the same value and the cache should still contain one record. For a miss, change the readout boundary for `logical_mz` by 5 µm and inspect the reported missing key. The original inputs and assertions can be read with `git show 22456ff:modules/logical_compiler/tests/test_fast_applicability.py`. Coverage of a new factory requires checking every component variant it requests.

## 4. Choose the edit and test it

If a component needs a wider envelope, change its provider declaration and version. Test the boundary at the **same new version**. Save a record with a spectator just outside, move its footprint just inside, and expect a miss. Comparing two versions would allow the version change alone to explain the miss. If spectator comparison changes for every provider, edit the generic key builder and verify both the cache and its fast consumer. Start with `python -m tools.testing.run fast --changed <edited-path>` from the repository root. [Test selection](testing.md)

**Transfer question.** Translate the entire layout. Can the old measurement record serve it? Hold the component and the relative spectator geometry fixed, then compare the readout region as seen from the first participant. An equivalent device context permits the same key. A changed relative readout intersection changes the measurement key. Inspect the participant-relative readout bounds in the two keys.
