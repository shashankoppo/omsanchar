# Protocol versioning

Status: draft v0.1.

- The Protobuf package version (`om.sanchar.v1`) identifies a schema compatibility line. `Envelope.version` identifies envelope semantics and must be `1` for this draft.
- Additive fields use new field numbers and are optional or have safe defaults. Never change the type or meaning of a published field number. Removed field numbers and names are reserved permanently.
- Unknown Protobuf fields are ignored by v1 readers and preserved by intermediaries that decode and re-encode messages. Unknown enum values must be rejected at policy-sensitive boundaries unless the operation explicitly allows opaque forwarding.
- A change that breaks wire compatibility requires a new package major (`v2`) and a migration period with explicit negotiation. Do not infer support from a server version string.
- Public JSON uses Protobuf JSON field names, enum names, and base64 for `bytes`. It must not silently coerce numbers, enum strings, or binary payloads.
- Before the first `v0.1.0` tag, this review candidate may receive wire-contract corrections; its field numbers and semantics freeze at that tag. After release, CI checks Buf compatibility against both the pull-request base and the latest supported release tag, beginning with `v0.1.0`. Conformance vectors are versioned with the package and remain available for older supported versions.
