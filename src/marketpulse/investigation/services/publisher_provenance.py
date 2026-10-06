"""Derive publisher identity from same-run, hash-verified publication records.

These are deterministic validation views, not mutations of archived Sources. Cloud
host names and model assertions alone never establish an official publisher.
"""

from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.enums import SourceType
from marketpulse.investigation.domain.sources import Source, SourceSnapshot


def publisher_views(
    sources: tuple[Source, ...],
    snapshots: tuple[SourceSnapshot, ...],
    blobs: BlobStoragePort,
) -> tuple[tuple[Source, ...], tuple[SourceSnapshot, ...]]:
    source_map = {s.source_id: s for s in sources}
    snapshot_map = {s.snapshot_id: s for s in snapshots}
    publishers = tuple(
        (source_map[s.source_id], s)
        for s in sorted(snapshots, key=lambda s: s.snapshot_id)
        if s.source_id in source_map
        and source_map[s.source_id].is_official
        and source_map[s.source_id].is_first_hand
        and source_map[s.source_id].publisher
        and s.http_status == 200
        and s.evidence_eligible
    )
    for document in snapshots:
        if document.mime_type != "application/pdf" or not document.evidence_eligible:
            continue
        source = source_map[document.source_id]
        if not blobs.verify_hash(document.raw_blob_ref):
            continue
        document_url = document.provenance.get("final_url") or str(source.canonical_url)
        proofs = []
        for publisher, record in publishers:
            if record.run_id != document.run_id or not blobs.verify_hash(record.raw_blob_ref):
                continue
            chain = record.provenance.get("publisher_redirect_chain")
            redirected = (
                isinstance(chain, dict)
                and chain.get("document_url") == document_url
                and chain.get("official_url") == str(publisher.canonical_url)
                and chain.get("publisher") == publisher.publisher
                and record.raw_sha256 == document.raw_sha256
            )
            links = record.provenance.get("publisher_document_links", [])
            linked = (
                record.mime_type == "text/html"
                and record.retrieved_at <= document.retrieved_at
                and isinstance(links, list)
                and any(
                    isinstance(link, dict)
                    and link.get("url") == document_url
                    and link.get("publication_statement")
                    for link in links
                )
            )
            if redirected or linked:
                proofs.append(
                    (publisher, record, "same-hash redirect" if redirected else "published link")
                )
        # Competing publishers are not settled by URL order or a quality-score target.
        if not proofs or len({p.publisher for p, _, _ in proofs}) != 1:
            continue
        publisher, record, relation = proofs[0]
        cluster = publisher.syndication_cluster_id or f"issuer:{publisher.publisher}"
        source_map[publisher.source_id] = publisher.model_copy(
            update={"syndication_cluster_id": cluster}
        )
        source_map[source.source_id] = source.model_copy(
            update={
                "publisher": publisher.publisher,
                "organization": publisher.organization,
                "is_official": True,
                "is_first_hand": True,
                "source_type": SourceType.OFFICIAL_REPORT,
                "syndication_cluster_id": cluster,
            }
        )
        provenance = dict(document.provenance)
        provenance["publisher_proof"] = {
            "publisher": publisher.publisher,
            "source_id": publisher.source_id,
            "snapshot_id": record.snapshot_id,
            "raw_sha256": record.raw_sha256,
            "official_url": str(publisher.canonical_url),
            "document_url": document_url,
            "relation": relation,
        }
        if record.provenance.get("methodology"):
            provenance["methodology"] = record.provenance["methodology"]
        snapshot_map[document.snapshot_id] = document.model_copy(update={"provenance": provenance})
    return (
        tuple(source_map[s.source_id] for s in sources),
        tuple(snapshot_map[s.snapshot_id] for s in snapshots),
    )
