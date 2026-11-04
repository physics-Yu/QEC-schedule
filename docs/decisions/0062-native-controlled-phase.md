# 0062: Native controlled-phase pulses

Status: accepted for the Search Smarter ready-scheduler path.

The small Shor inputs contain parameterized controlled phases and semiclassical
measurement-controlled local phases. Preserving these gates requires explicit
atom actions; changing only the frontend basis leaves placement and emission
unsupported.

`CPhasePulse` applies `diag(1, 1, 1, exp(i * angle))` to each interacting pair
within its coverage. It is a distinct action from `CZPulse`; it carries its
angle, channel, duration and native source IDs. Angles use radians without
approximate angle bucketing. One pulse serves disjoint pairs with exactly equal
angles. Separate CP pulses, or CP and CZ pulses, cannot overlap on one channel.

Devices opt in through `cphase` and explicit `cp` zone permissions. The first
Search Smarter implementation requires the same CP/CZ channel, interaction
radius, holders and spectator policy, so existing pair placement and rigid
transport constraints remain applicable. CP duration is configured independently.
Unsupported schedulers and built-in compilers reject these native gates at
admission. The generic compiler registry remains extensible.

The native DAG retains H, T, T dagger and Phase. Emission uses one exact LocalU
per gate: H = U(pi/2, 0, pi), Phase(a) = U(0, 0, a). Source labels are shown in
the viewer. This avoids the global-phase difference between Phase and RZ.

Independent validation checks source angles, actual illuminated interactions,
zone/holder permissions, channel conflicts, movement overlap and duration.
Existing feedback validation checks availability latency and executed/skipped
decisions. Playback represents one resolved measurement case, not a branch tree.

Serialization adds a new action kind while retaining old result readers in the
new implementation. Older software rejects the unknown kind. Devices without
CP omit the new field when encoded, preserving historical Device hashes.
Activity events retain CP angles and pairs; result metrics separately record
CP gates per pulse. Existing cost models reject native CP until a suitable
calibration is supplied; no CZ error model is silently reused.

The four-qubit CLI example uses 0.75 us per CP pulse as an explicit study assumption.
Software validation establishes circuit and scheduling consistency, not
hardware calibration, factoring success probability or fault tolerance.
