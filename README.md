# clash-relay-ci

Public, secret-free validation harness for the private `MetaUoa/clash-relay` production repository.

## Security boundary

This repository does **not** contain the private repository history, subscription URLs, Gist credentials, source baselines, candidate artifacts, node fingerprints, real provider nodes, or production configuration.

It also does **not** check out the private repository and does **not** require a private-repository token. `PRIVATE_REPO_READ_TOKEN` is no longer used and may be deleted from this repository's Actions secrets.

The public repository contains only:

- a sanitized effective Phase3A AI topology contract under `private-src/`;
- a standalone Mihomo runtime harness under `public-harness/`;
- `source-ref.txt`, which records the private commit SHA whose topology the sanitized contract represents;
- the public Actions workflow.

## Public CI responsibilities

`.github/workflows/public-ci.yml` runs on standard public GitHub-hosted runners and validates:

1. the sanitized Phase3A production topology contract;
2. real Mihomo Core runtime behavior on v1.19.27, v1.19.28, v1.19.29 and v1.19.30;
3. both required runtime scenarios:
   - shared Universal country pools are primary when a U node is healthy;
   - the service-specific NON-U pool is selected when all U country pools are empty/rejected.

The Mihomo release archives are SHA-256 pinned by the harness.

## Private production responsibilities

The private `MetaUoa/clash-relay` repository remains authoritative for:

- source code and full pytest/coverage;
- subscription observation and verification;
- encrypted source snapshot / source baseline;
- real candidate generation and candidate guard;
- production Secrets;
- production Mihomo compatibility recheck;
- fixed Secret Gist publication and source-baseline self-roll.

Public CI is an additional free heavy-runtime gate. It does not weaken or replace the private production fail-closed pipeline.
