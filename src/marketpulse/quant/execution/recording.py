import json

from sqlalchemy import select

from marketpulse.infrastructure.storage.models import BlobRef

from ..contracts import canonical, digest
from ..domain import ArtifactBundle
from ..storage.models import ComputeRecordRow


class ComputeJournal:
    def __init__(self, sessions, blobs):
        self.sessions, self.blobs = sessions, blobs

    def append_in_session(
        self,
        session,
        *,
        job_id,
        logical_key,
        ordinal,
        attempt,
        input_hash,
        artifact_id=None,
        error=None,
    ):
        record = {
            "job_id": job_id,
            "logical_key": logical_key,
            "ordinal": ordinal,
            "attempt": attempt,
            "input_hash": input_hash,
            "artifact_id": artifact_id,
            "error": error,
        }
        identity = digest(record)
        if session.get(ComputeRecordRow, identity):
            return
        ref = self.blobs.put_bytes(canonical(record).encode()).ref.uri
        session.add(ComputeRecordRow(record_id=identity, job_id=job_id, payload_ref=ref))

    def replay(self, *, job_id, input_hash, load_artifact) -> ArtifactBundle:
        with self.sessions() as session:
            rows = session.scalars(
                select(ComputeRecordRow).where(ComputeRecordRow.job_id == job_id)
            ).all()
            matches = []
            for row in rows:
                record = json.loads(self.blobs.get_bytes(BlobRef.from_uri(row.payload_ref)))
                if digest(record) != row.record_id or record["input_hash"] != input_hash:
                    raise ValueError("compute recording integrity mismatch")
                if record["job_id"] != job_id:
                    raise ValueError("compute recording job mismatch")
                if record["artifact_id"]:
                    matches.append(record["artifact_id"])
            if len(set(matches)) != 1:
                raise ValueError("no unambiguous completed compute recording")
            return load_artifact(matches[0])
