from __future__ import annotations

from core.benchmarks import run_suite


def main() -> int:
    report = run_suite(write_report=True)
    for case in report["cases"]:
        state = "PASS" if case["passed"] else "FAIL"
        print(f"{state:4}  {case['name']:<34} {case['duration_ms']:>8.3f} ms  {case['detail']}")
    print(f"\n{report['passed']}/{len(report['cases'])} passed in {report['total_ms']:.3f} ms")
    print(f"Report: {report['report_path']}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
