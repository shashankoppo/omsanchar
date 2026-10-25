# Dependency and artifact policy

The Python reference gateway uses only the standard library. `requirements-dev.txt` contains pinned developer tooling; the Rust conformance crate has a locked test dependency tree in `dataplane/sanchar-core/Cargo.lock`.

Before adding a third-party dependency:

1. Pin an exact release or immutable revision in the ecosystem's lock file.
2. Record its direct purpose, SPDX license expression, and source in the dependency inventory; retain maintenance/security review notes with the dependency change.
3. Add the exact resolved dependency set to the reviewed inventory. CI checks Python package metadata and Cargo.lock/metadata versions, sources, and licenses, generates a dependency-level SPDX SBOM with Syft, and scans it with Grype (failing on high or critical findings).
4. Prefer a replaceable interface and avoid network access from unit tests; use local mocks.

The source SBOM generator inventories repository files and hashes; it is not a dependency SBOM. The Syft SBOM is uploaded as a CI artifact and scanned before the build passes. Container-image SBOM generation and image vulnerability policy remain separate release-hardening work.

Only exact-pinned Python packages and locked Cargo packages listed in `docs/security/dependency-inventory.json` are accepted. The current Cargo license allowlist is Apache-2.0, BSL-1.0, MIT, Unicode-3.0, and Unlicense; every identifier in a compound expression must be on that list. When a package introduces transitive dependencies, inventory the full resolved set so each package has a reviewed purpose, source, and license record.
