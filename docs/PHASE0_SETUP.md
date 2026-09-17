# Phase 0 bootstrap

Scope: P0-01/P0-02 version records and the initial P0-03/P0-04 environment.
This is not a completed Phase 0 gate or a simulator-qualified version pair.

## Reproduce the CPU data environment

Use Linux x86_64, Python 3.12.3 and uv 0.11.19 (versions recorded in
`config/versions.json`). The Python minor range follows the pinned RL project's
`pyproject.toml`. Windows users can run these commands in Ubuntu 24.04 WSL.

```sh
uv sync --locked --python 3.12.3
uv run --locked python scripts/smoke.py
```

`uv.lock` pins the transitive data-client dependencies and artifact hashes.
This environment does not install the robot daemons or RL training stack.
On a Windows-mounted checkout, prefer a Linux-local cache and environment:

```sh
export UV_CACHE_DIR=/tmp/microduck-p0-cache
export UV_PROJECT_ENVIRONMENT=/tmp/microduck-p0-environment
uv sync --locked --python 3.12.3
uv run --locked python scripts/smoke.py
```

## Authenticated dataset smoke

The [official download page](https://male-cns.janelia.org/download/) documents
neuPrint access, the `male-cns:v1.0` dataset, and CC-BY licensing. No dataset
is redistributed in this change. Obtain a token through the neuPrint account
interface and set `NEUPRINT_TOKEN` using local secret storage or a silent shell
prompt. Do not paste the token into chat, source files, command arguments or logs.

```sh
read -rsp 'neuPrint token: ' NEUPRINT_TOKEN
export NEUPRINT_TOKEN
uv run --locked python scripts/smoke.py --online
unset NEUPRINT_TOKEN
```

The online smoke queries `DNge104`, the official access example. These records
are connectivity-access evidence only, not the frozen steering population.
Missing credentials exit 2; failed access or unexpected records exit 1. Offline
mode reports `dataset_query: NOT_RUN` and cannot satisfy the dataset gate.

## Official simulator checkout path (not yet executed)

Read URLs and commit SHAs from `config/versions.json`. Clone each upstream into
sibling directories named `microduck` and `microduck_rl`, then run
`git checkout --detach <manifest commit>` in each. Never substitute a branch tip.
The observed default branch of `microduck_rl` is `develop`.

In the pinned `microduck_rl` checkout, run `uv sync --locked` with Python 3.12.
In the pinned `microduck` checkout, follow `docs/robot/simulation.md` and run
`scripts/duck-sim`, then `scripts/duck-sim status`, and stop it with
`scripts/duck-sim down`. The launcher builds Rust daemons and uses the sibling
RL environment. Install the pinned upstream's documented system prerequisites
first. Rust/cargo is currently absent from the inspected WSL PATH; simulator
builds, policy downloads, graphics and daemon compatibility remain unverified.

Review policy asset identities and upstream dependency/toolchain locks before
qualifying this pair. The upstream launcher may acquire external assets; its
existence is not evidence of a reproducible simulator build.

## Remaining Phase 0 acceptance work

- Successful authenticated known-neuron query.
- Derived deterministic graph fixture, provenance and expected hashes.
- Smoke neural step using the frozen model specification.
- Experiment configuration schema covering the frozen interface fields.
- Pinned simulator build/launch validation and asset/toolchain identities.
- Full reproduction twice from clean checkouts and fresh environments.
- Independent phase review. Bootstrap imports alone cannot pass this gate.
