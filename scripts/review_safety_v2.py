"""Export or validate source-bound review annotations entirely offline."""

import argparse
import json
from pathlib import Path

from eval.safety_v2.reports import atomic_write
from eval.safety_v2.review import assess, make_template, write_assessment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--annotations")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        output = Path(args.output)
        if not args.annotations:
            output.parent.mkdir(parents=True, exist_ok=True)
            template = make_template(args.results)
            atomic_write(output, json.dumps(template, ensure_ascii=False, indent=2) + "\n")
            print(f"Exported {len(template['annotations'])} review cases to {output}")
        else:
            annotations = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
            assessment = assess(args.results, annotations)
            write_assessment(output, assessment)
            print(
                json.dumps(
                    {
                        "output": str(output),
                        "semantic_counts": assessment["semantic_counts"],
                        "unreviewed": assessment["unreviewed_case_ids"],
                        "additional_provider_requests": 0,
                    },
                    indent=2,
                )
            )
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
