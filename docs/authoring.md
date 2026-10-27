# Documentation authoring

## Source of truth

| Content | Canonical source |
|---|---|
| User and operator guidance | `docs/` |
| Wire and error contracts | `spec/` and its conformance vectors |
| Architecture choices and trade-offs | `adr/` |
| Current phase, evidence, and unresolved work | `PROGRESS.md` |
| Measured results and raw records | `bench/` and `docs/security/reports/` |
| Supplied upstream material | `docs/upstream/`; file 04 is authoritative for Om Sanchar |

Do not copy a canonical contract into a second editable source. Link to it. If a page needs a short explanation, state that it is a summary and point to the canonical file.

## Local workflow

Install the exact documentation toolchain and build the site from the repository root:

```sh
python3 -m pip install --disable-pip-version-check --no-deps -r requirements-docs.txt
make docs
```

To preview edits while writing, run `make docs-serve`. The preview server is local-only; CI's strict build is the merge gate.

## Example policy

Examples must correspond to behavior available in the checked-out revision. Keep each HTTP body, protocol vector, and sample command small. The executable quickstart is a black-box HTTP/SSE exercise; CI starts the real reference gateway, runs the commands from `quickstart.md`, checks the response, and stops the process. The protocol suites execute shared vectors referenced by `spec/`.

Shell blocks are syntax-checked in CI: Bash on Ubuntu and PowerShell on Windows. JSON examples are parsed, Python blocks are compiled, regular-expression examples are compiled, and Mermaid blocks are checked for balanced fences and a declared diagram type. The quickstart's marked HTTP/SSE example is executed against the real reference gateway. Other installation and operations snippets are syntax-checked procedures; they can change a host or require specific software, so they are not run on shared CI machines. Explain their platform preconditions and avoid embedding machine-specific paths.

When adding another runnable example, add its test to `scripts/test_docs_examples.py` and invoke it from `make docs`. Phase 1's SDK and OpenAPI examples must also be executed in CI before WP8 can be marked complete. Do not claim that a code sample runs in CI unless the test actually executes that sample or validates it against the canonical executable contract.

## Review and release

Review docs with the code change that alters behavior. Run `make docs` locally, inspect the generated navigation and site output, and update `CHANGELOG.md` for user-visible behavior. CI builds the site from a clean checkout with strict link validation. The generated `site/` directory is disposable and must not be committed.

The source tree is published on GitHub and GitHub renders Markdown there. This site build is currently a validation and preview artifact; it does not configure GitHub Pages or imply that a hosted documentation site is deployed.
