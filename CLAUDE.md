# Om Sanchar: Working Rules

- Mission: build a sovereign, self-hostable communication layer and API gateway for Evolucentsphere.
- Read `PROGRESS.md`, `/adr`, and files referenced by the task at the start of every session. Read any supplied `/docs/upstream` material first. Update `PROGRESS.md` at the end of every session.
- Read available `/docs/upstream` material before changing architecture. Raise conflicts as open questions.
- Work only on the current roadmap phase. Do not move to a later phase until current exit criteria are recorded as met.
- Write and review protocol contracts before implementation. Generated code is never edited by hand.
- Keep dependencies pinned, scan licenses, and review maintenance/security posture. Do not commit secrets.
- Use deny-by-default authorization, mTLS, capability attenuation, and explicit resource bounds. Keep the data plane functional with last-known-good configuration during control-plane outages.
- Do not invent benchmark numbers, API behavior, or library features. Run code before claiming it works and label unverified assumptions.
- Definition of done includes relevant unit/property/conformance/simulation tests, benchmark evidence, observability, docs/changelog updates, and a rollback path.
- Planned commands: `make dev`, `make test`, `make bench`, `make lint`, and `make docs`. `make dev`, `make bench`, and `make docs` are roadmap targets and must not be reported as working until implemented and run.
- Current local reference checks: `python -m unittest discover -s spec/tests -v`, `python -m unittest discover -s sim/tests -v`, and `python scripts/check_style.py`.
- Each working turn reports Status, Done, Evidence, Decisions and assumptions, Risks and open questions, and Next step.
