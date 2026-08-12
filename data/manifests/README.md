# Provenance Manifests

This is the tracked metadata boundary for ignored data payloads and generated output artifacts. `src/ddvc/provenance.py` owns the portable stamps; release modules own release-specific manifests and pointers. A manifest records identities and lineage but does not make a payload scientifically admissible by itself.

See the [`canonical repository and data map`](../../docs/repository-data-map.md#data-layers) for ownership, consumers, and retirement rules. Remove a manifest only in the same reviewed change that retires its artifact, owner, and downstream references.
