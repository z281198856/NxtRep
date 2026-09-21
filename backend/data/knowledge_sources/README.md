# RAG source workspace

`raw/` stores locally downloaded source files and is intentionally ignored by Git. Large files,
licensed publications, and mutable web snapshots must not be committed to the application source
tree.

`sources.json` is the tracked provenance manifest. It records the official URL, publisher, retrieval
time, local filename, SHA-256 digest, licensing evidence, topic, locale, review scope, and review
state for every download.

Review states:

- `approved_for_ingestion`: provenance and reuse terms were checked, and the current loader can
  prepare the file. This does not approve every generated chunk for publication.
- `hold_license_restriction`: the known licence is incompatible with the intended product use.
- `hold_permission_required`: the publisher reserves rights and explicit permission is required.
- `hold_permission_unverified`: the material is official, but reuse permission has not been verified.

Only `approved_for_ingestion` files may proceed to source registration and formal import. Every
imported document must still pass the database review and publication steps before the Agent can
retrieve it. The human-readable decision record and permitted answer scope are documented in
`docs/RAG_KNOWLEDGE_SOURCES.md`.

Later, the ingestion pipeline will upload raw files to private OSS storage and persist only the
object key and derived, reviewed text in PostgreSQL.
