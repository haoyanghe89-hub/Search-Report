import asyncio
import hashlib
from decimal import Decimal

import pytest

from marketpulse.quant.compute.metrics import compute_metrics
from marketpulse.quant.contracts import canonical
from marketpulse.quant.domain import ArtifactBundle, MetricSpec
from marketpulse.quant.execution.worker import bounded_read
from marketpulse.quant.validation import compare_reproduction
from tests.unit.quant.test_compute_n import series


def artifact(*, difference="0", python="original", unit=None, name="return"):
    value = next(
        v
        for v in compute_metrics(series=series([100, 110, 99]), spec=MetricSpec())
        if v.name == "return"
    ).model_copy(update={"name": name})
    value = value.model_copy(update={"value": value.value + Decimal(difference)})
    if unit:
        value = value.model_copy(update={"unit": unit})
    output = canonical([value.model_dump(mode="json")])
    output_hash = hashlib.sha256(output.encode()).hexdigest()
    manifest = canonical(
        {
            "environment": {"source_tree_hash": "tree", "lock_hash": "lock", "python": python},
            "inputs": [],
            "output_hash": output_hash,
        }
    )
    manifest_hash = hashlib.sha256(manifest.encode()).hexdigest()
    return ArtifactBundle(
        artifact_id="qart_" + manifest_hash,
        manifest_hash=manifest_hash,
        manifest_json=manifest,
        output_hash=output_hash,
        output_json=output,
        input_snapshot_ids=(),
        values=(value,),
    )


def test_same_environment_requires_bytes_not_tolerance():
    with pytest.raises(ValueError, match="bytes"):
        compare_reproduction(artifact(), artifact(difference="1e-12"), MetricSpec())


@pytest.mark.parametrize("name", ["return", "pe", "pb"])
def test_cross_environment_numeric_tolerance(name):
    compare_reproduction(
        artifact(name=name),
        artifact(name=name, difference="1e-12", python="other"),
        MetricSpec(),
    )
    with pytest.raises(ValueError, match="tolerance"):
        compare_reproduction(
            artifact(name=name),
            artifact(name=name, difference="1e-7", python="other"),
            MetricSpec(),
        )


def test_cross_environment_never_tolerates_changed_units():
    with pytest.raises(ValueError, match="unit/time"):
        compare_reproduction(artifact(), artifact(python="other", unit="percent"), MetricSpec())


async def test_output_stream_cap_is_enforced_between_chunks():
    stream = asyncio.StreamReader()
    stream.feed_data(b"a" * 65537)
    stream.feed_eof()
    with pytest.raises(ValueError, match="output limit"):
        await bounded_read(stream, 65536)
