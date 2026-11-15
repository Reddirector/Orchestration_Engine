import json
from unittest.mock import MagicMock
from regenbench.core.scenario import ScenarioGenerator


def test_scenario_prompts_contain_all_fields():
    # S1: order_id, amount (in cents matching schema), currency, reference
    sc1 = ScenarioGenerator.generate("S1", seed=42)
    s1_prompt = sc1.context_prompts[0]
    assert sc1.target_step.args["order_id"] in s1_prompt
    assert str(sc1.target_step.args["amount"]) in s1_prompt
    assert sc1.target_step.args["currency"] in s1_prompt
    assert sc1.target_step.args["reference"] in s1_prompt

    # S2: to, subject, body
    sc2 = ScenarioGenerator.generate("S2", seed=42)
    s2_prompt = sc2.context_prompts[0]
    assert sc2.target_step.args["to"] in s2_prompt
    assert sc2.target_step.args["subject"] in s2_prompt
    assert sc2.target_step.args["body"] in s2_prompt

    # S3: customer_id, title, body, external_ref
    sc3 = ScenarioGenerator.generate("S3", seed=42)
    s3_prompt = sc3.context_prompts[0]
    assert sc3.target_step.args["customer_id"] in s3_prompt
    assert sc3.target_step.args["title"] in s3_prompt
    assert sc3.target_step.args["body"] in s3_prompt
    assert sc3.target_step.args["external_ref"] in s3_prompt


def test_mode_m_pair_structure_uses_model_calls_never_generator_args():
    # Mocking model calls
    mock_client = MagicMock()
    # Call 1 (initial call) returns modified args differing from generator args
    call_1_args = {"order_id": "ord_93810", "amount": 1000, "currency": "USD", "reference": "ref-custom"}
    call_2_args = {"order_id": "ord_93810", "amount": 1000.0, "currency": "USD", "reference": "ref-custom"}

    mock_client.generate_tool_call.side_effect = [
        {"arguments": call_1_args},
        {"arguments": call_2_args},
    ]

    sc = ScenarioGenerator.generate("S1", seed=42)
    generator_args = sc.target_step.args
    assert generator_args["reference"] != "ref-custom"

    # Simulate Mode M execution
    initial_res = mock_client.generate_tool_call(messages=[{"role": "user", "content": sc.context_prompts[0]}])
    initial_args = initial_res["arguments"]

    # C4 condition passes initial call in system message
    c4_sys_msg = f"Prior tool invocation attempt: {json.dumps(initial_args)}"
    c4_res = mock_client.generate_tool_call(messages=[
        {"role": "system", "content": c4_sys_msg},
        {"role": "user", "content": sc.context_prompts[0]}
    ])
    regenerated_args = c4_res["arguments"]

    pair = {
        "original": initial_args,
        "regenerated": regenerated_args,
    }

    # Verify pair is (call_1, call_2), NOT generator args
    assert pair["original"] == call_1_args
    assert pair["original"] != generator_args
    assert pair["regenerated"] == call_2_args
    assert "ref-custom" in c4_sys_msg
