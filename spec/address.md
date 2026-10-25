# Om Sanchar address grammar

Status: draft v0.1. This grammar is the canonical textual representation for a tenant-scoped object address.

## Syntax

```text
address = "om://" tenant "/" kind "/" name [ "@" version ]
kind    = "model" | "tool" | "agent" | "topic" | "node" | "channel"
```

`tenant` is 1–63 characters and matches `[a-z0-9](?:[a-z0-9-]*[a-z0-9])?`. `name` is 1–127 characters and `version`, when present, is 1–63 characters; those two segments match:

```regex
[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?
```

The grammar applies the corresponding maximum length above. Addresses are case-sensitive and lowercase only. Whitespace, percent escapes, query strings, fragments, extra path segments, and empty segments are rejected. Version is an opaque lowercase identifier in v0.1; it is not implicitly semantic versioning and `latest` has no special meaning.

Examples:

- `om://acme/model/gpt-4o@v1`
- `om://research/tool/vector-search`
- `om://acme/topic/orders.v2`

The parser in `spec/reference/address.py` is the executable reference. It returns a structured address and does not perform registry lookup or authorization.
