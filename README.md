# clash-relay-ci

Public CI runner for the private `MetaUoa/clash-relay` repository.

## Security boundary

This repository does **not** store the private project source tree, subscription URLs, Gist credentials, source baselines, candidate artifacts, node fingerprints, or production configuration.

The workflow checks out one explicitly pinned commit from the private repository at runtime using a read-only fine-grained token stored as `PRIVATE_REPO_READ_TOKEN`. Test output that may contain private-source details is redirected to runner-local temporary files and is not uploaded as an artifact.

The public runner is used only for validation work:

- Ruff
- full pytest / coverage
- Ubuntu and Windows compatibility
- Native Mihomo smoke
- strict Mihomo Core compatibility matrix

Production-only work remains in the private repository:

- subscription observation
- source snapshot / baseline
- real candidate generation
- production Secrets
- fixed Secret Gist publication

`source-ref.txt` contains the exact private commit SHA that this public CI repository is expected to validate.
