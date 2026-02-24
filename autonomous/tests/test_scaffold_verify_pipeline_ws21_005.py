from autonomous.scaffold_verify_pipeline import ScaffoldVerifyPipeline, VerifyStep


def test_verify_pipeline_stops_on_error_step() -> None:
    pipeline = ScaffoldVerifyPipeline(
        [
            VerifyStep(name="lint", fn=lambda ctx: (True, "lint ok"), severity="error"),
            VerifyStep(name="tests", fn=lambda ctx: (False, "tests failed"), severity="error"),
            VerifyStep(name="smoke", fn=lambda ctx: (True, "smoke ok"), severity="error"),
        ]
    )

    result = pipeline.run({"trace_id": "trace-ws21"})
    assert result.passed is False
    assert result.summary == "verify failed at step=tests"
    assert [item.name for item in result.step_results] == ["lint", "tests"]


def test_verify_pipeline_allows_warning_failures() -> None:
    pipeline = ScaffoldVerifyPipeline(
        [
            VerifyStep(name="lint", fn=lambda ctx: (True, "lint ok"), severity="error"),
            VerifyStep(name="style", fn=lambda ctx: (False, "style warn"), severity="warn"),
        ]
    )

    result = pipeline.run({})
    assert result.passed is True
    assert result.summary == "verify passed with warnings"
