"""
Buy or Wait? — pipeline entry point.

Running this script executes all stages in order.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from stage1 import run_stage1
from stage2 import run_stage2
from stage3 import run_stage3


def run_pipeline(
    mode: str = "all",
    regress_sample: bool = True,
    use_llm_explanations: bool = True,
    offline_sample_explanations: bool = False,
) -> None:
    """Run Stage 1, then Stage 2, then Stage 3 with the given mode and explanation options."""
    print("Stage 1: consolidating user context...")
    result = run_stage1(mode=mode)
    print(
        f"  Wrote {result.row_count} rows ({result.mode}) -> {result.output_path}"
    )

    print("Stage 2: resolving ledger...")
    stage2 = run_stage2(mode=mode)
    print(
        f"  Wrote {stage2.user_count} ledgers ({stage2.mode}) -> {stage2.output_path}"
    )

    print("Stage 3: decisions and final output...")
    stage3 = run_stage3(
        mode=mode,
        regress_sample=regress_sample,
        use_llm_explanations=use_llm_explanations,
        offline_sample_explanations=offline_sample_explanations,
    )
    print(f"  Wrote {stage3.row_count} rows -> {stage3.output_path}")
    if stage3.regression:
        print(f"  {stage3.regression}")


def main() -> None:
    """Parse CLI flags and invoke one stage or the full pipeline."""
    parser = argparse.ArgumentParser(description="Buy or Wait? pipeline")
    parser.add_argument(
        "--mode",
        choices=("all", "sample", "eval"),
        default="all",
        help="Scope for stages (default: all)",
    )
    parser.add_argument("--stage1-only", action="store_true")
    parser.add_argument("--stage2-only", action="store_true")
    parser.add_argument("--stage3-only", action="store_true")
    parser.add_argument(
        "--no-regression",
        action="store_true",
        help="Skip sample regression report in Stage 3",
    )
    parser.add_argument(
        "--stub-explanations",
        action="store_true",
        help="Skip DeepSeek; use deterministic explanation stubs in Stage 3",
    )
    parser.add_argument(
        "--offline-explanations",
        action="store_true",
        help=(
            "For sample users, use gold decision_explanation from sample_labels "
            "(no DeepSeek). Remove this flag when you want live LLM explanations again."
        ),
    )
    args = parser.parse_args()

    flags = [args.stage1_only, args.stage2_only, args.stage3_only]
    if sum(flags) > 1:
        parser.error("Use only one of --stage1-only, --stage2-only, --stage3-only.")

    regress = not args.no_regression
    use_llm = not args.stub_explanations and not args.offline_explanations
    offline_explanations = args.offline_explanations

    if args.stage1_only:
        result = run_stage1(mode=args.mode)
        print(f"Wrote {result.row_count} rows ({result.mode}) -> {result.output_path}")
        return

    if args.stage2_only:
        stage2 = run_stage2(mode=args.mode)
        print(
            f"Wrote {stage2.user_count} ledgers ({stage2.mode}) -> {stage2.output_path}"
        )
        return

    if args.stage3_only:
        stage3 = run_stage3(
            mode=args.mode,
            regress_sample=regress,
            use_llm_explanations=use_llm,
            offline_sample_explanations=offline_explanations,
        )
        print(f"Wrote {stage3.row_count} rows -> {stage3.output_path}")
        if stage3.regression:
            print(stage3.regression)
        return

    run_pipeline(
        mode=args.mode,
        regress_sample=regress,
        use_llm_explanations=use_llm,
        offline_sample_explanations=offline_explanations,
    )


if __name__ == "__main__":
    main()
