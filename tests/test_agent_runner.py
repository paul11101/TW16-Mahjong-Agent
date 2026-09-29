from test_interface.agent_runner import run_agent


def test_run_agent_success():
    result = run_agent()

    assert result["success"] is True
    assert result["observation"] is not None
    assert result["decision"]["success"] is True
    assert result["decision"]["action"]["type"] == "discard"
    assert result["execution"]["success"] is True