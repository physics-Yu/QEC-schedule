# Local worktree retirement, 2026-11-04

At `main` revision `2c351d6372b9037714fa7453693567d48e46d477`,
24 merged local branch names and 14 worktrees were retired. This left
10 local branch names and eight registered worktrees. The Color666,
static-patch-compiler and active detached `8663` checkouts were retained.

## Recover a branch or experiment

The [retired branch ledger](retired-branches-2026-11-04.tsv) gives each
branch name and its full Git commit. In a clone containing the revision
above, restore a name with `git branch <branch-name> <tip>`.
For the object-factory studies with distinct histories, use the
[experiment index](../experiments/msd-historical-scans.md) to find the
executed revisions, reports and delivery hashes.

For uncommitted files or experiment outputs, open the local archive
`NADiT-archives/worktree-retirement-20261104-160049/README.md`
beside the original project directory. It maps each worktree to its
snapshot and records how to restore staged and unstaged changes. Twelve
retired worktrees have full filesystem snapshots. The two clean checkouts
can be reconstructed from Git. Historical paths for 5,878 files are hard
links to the snapshots. Copy a file before editing its contents.

The archive's `local-revisions.bundle` contains the original branch tips
and two stash recovery refs. Its SHA-256 is
`90c68c2e14f3ee5835eaa0233a57beec3290b7002d404242aa269057bc472b2a`.
The bundle was restored in an empty repository. After retirement, hashes
were checked at the original paths for 192 single-level MSD completion
records, three historical delivery archives and 14 pytest failure logs.
