# initialize_0

Logical operation: initialize_0 on one encoded qubit.

The translation frontend emits this exact component name. It initializes or
reinitializes the logical qubit to the Z-positive zero state, independently of its prior state.
The atom-level circuit and its physical entry/exit requirements remain open.

The frontend may fold an immediately following unconditional H into the other
initializer. Such folding is not allowed across an intervening operation on
the same qubit or an unresolved branch condition.
