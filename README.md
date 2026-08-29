# clash-relay-ci

Public validation harness for the private `MetaUoa/clash-relay` production repository.

## Security boundary

This repository does **not** store the private repository history, subscription URLs, Gist credentials, source baselines, candidate artifacts, node fingerprints, real provider nodes, or production configuration.

There are two validation modes:

- **Standalone public mode** uses only the sanitized Phase3A contract and the standalone Mihomo runtime harness committed in this repository.
- **Private-source dispatch mode** temporarily checks out one exact `MetaUoa/clash-relay` commit into an ephemeral GitHub-hosted runner using `PRIVATE_REPO_SSH_KEY`, a read-only Deploy Key scoped only to that private repository. Private source is not committed to this public repository and is not uploaded as an artifact.

The dispatch mode also uses `PRIVATE_STATUS_TOKEN`, scoped only to writing commit statuses back to `MetaUoa/clash-relay`. It has no production subscription or Gist permissions. The old `PRIVATE_REPO_READ_TOKEN` is not used.

The public repository itself contains only:

- a sanitized effective Phase3A AI topology contract under `private-src/`;
- a standalone Mihomo runtime harness under `public-harness/`;
- `source-ref.txt`, which records the private commit SHA represented by the sanitized contract;
- the permanent public Actions workflow.

## Public CI responsibilities

`.github/workflows/public-ci.yml` runs heavy validation on standard public GitHub-hosted runners. For private-source dispatches it validates the exact requested SHA with:

- Ruff;
- pytest and coverage;
- Native Mihomo API smoke;
- Ubuntu and Windows compatibility;
- frozen strict Mihomo Core compatibility;
- production strict Mihomo Core compatibility.

The standalone public harness also verifies Mihomo v1.19.27, v1.19.28, v1.19.29 and v1.19.30 for both required Phase3A runtime scenarios:

- shared Universal country pools are primary when a U node is healthy;
- the service-specific NON-U pool is selected when all U country pools are empty/rejected.

The Mihomo release archives used by the standalone harness are SHA-256 pinned.

## Private production responsibilities

The private `MetaUoa/clash-relay` repository remains authoritative for:

- source code and production configuration;
- subscription observation and verification;
- encrypted source snapshot / source baseline;
- real candidate generation and candidate guard;
- production Secrets;
- the final private production Mihomo compatibility gate;
- fixed Secret Gist publication and source-baseline self-roll.

The private CI bridge only marks `public-ci/complete` pending and dispatches the public workflow; it does not wait on a private runner for the heavy tests. Public CI writes the final success/failure status back to the exact private commit.

Public validation does not weaken or replace the private production fail-closed pipeline. Production publication remains private and is blocked whenever its own required gates cannot run or pass.
