from __future__ import annotations

import argparse
import json
from pathlib import Path

from marketpulse.investigation.evaluation import Corpus, EvaluationConfig, compare


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare archive-only truncation and BM25")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-artifacts", type=int, default=12)
    parser.add_argument("--max-excerpts", type=int, default=24)
    parser.add_argument("--max-chars", type=int, default=40_000)
    parser.add_argument("--model-config-id", default="no-model")
    args = parser.parse_args()
    try:
        corpus = Corpus.model_validate_json(args.corpus.read_text(encoding="utf-8"))
        config = EvaluationConfig(
            max_artifacts=args.max_artifacts,
            max_excerpts=args.max_excerpts,
            max_chars=args.max_chars,
            model_config_id=args.model_config_id,
        )
        result = compare(corpus, config)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
