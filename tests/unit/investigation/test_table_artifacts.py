from marketpulse.investigation.ingestion.html import HtmlDocumentParser
from marketpulse.investigation.ingestion.models import DocumentParseRequest


def test_table_artifact_retains_entity_columns_and_complete_rows():
    body = b"""<html><main><h1>Official model evaluation</h1>
    <p>A public evaluation with sufficiently detailed methodology and traceable
    original benchmark measurements, preserving units and the measured scope.</p>
    <table><caption>Agentic coding</caption><tr><th>Benchmark</th>
    <th>Gemini 4 Argon</th><th>Other model</th></tr>
    <tr><td>DeepSWE v1.1</td><td>77.9%</td><td>74.1%</td></tr></table>
    </main></html>"""
    result = HtmlDocumentParser().parse(
        DocumentParseRequest(
            snapshot_id="SS-table",
            content=body,
            declared_content_type="text/html",
            url="https://example.org/evaluation",
        )
    )
    table = result.artifacts[1].content.decode()
    assert "Official model evaluation" in table
    assert "Agentic coding" in table
    assert "Benchmark: DeepSWE v1.1" in table
    assert "Gemini 4 Argon: 77.9%" in table
    assert "Other model: 74.1%" in table
    assert result.untrusted_content.trust == "UNTRUSTED"
