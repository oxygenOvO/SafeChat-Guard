from argparse import Namespace

from scripts.evaluate_pipeline import evaluate, write_outputs


def test_evaluate_pipeline_writes_expected_fields(tmp_path):
    input_path = tmp_path / "cases.csv"
    output_path = tmp_path / "results.csv"
    summary_path = tmp_path / "summary.json"
    input_path.write_text(
        "input_text,expected_category,expected_action,mock_model_output\n"
        "hello,normal,pass,\n"
        "please contact vx for details,ad,sanitize,\n",
        encoding="utf-8",
    )
    args = Namespace(
        config="config.yaml",
        input=str(input_path),
        output=str(output_path),
        summary=str(summary_path),
        text_column="input_text",
        label_column="expected_category",
        action_column="expected_action",
        raw_output_column="mock_model_output",
    )

    rows, summary = evaluate(args)
    write_outputs(rows, summary, args)

    assert len(rows) == 2
    assert {
        "rule_result",
        "semantic_result",
        "input_action",
        "output_action",
        "final_action",
        "risk_score",
        "correct",
    } <= set(rows[0])
    assert output_path.exists()
    assert summary_path.exists()
    assert summary["total"] == 2
    assert "model_version" in summary
    assert "model_sha256" in summary
    assert "config_version" in summary
    assert rows[1]["input_action"] == "sanitize"
    assert rows[1]["final_action"] == "sanitize"
    assert summary["correct"] == 2
