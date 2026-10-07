import runtime_state


def test_read_alarm_state_no_file_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "ALARM_STATE_PATH", tmp_path / "alarm_state.json")

    state = runtime_state.read_alarm_state()

    assert state == {"condition": None, "action": "NONE", "latched": False}


def test_write_then_read_alarm_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "ALARM_STATE_PATH", tmp_path / "alarm_state.json")

    runtime_state.write_alarm_state("MISLOAD", "STOP", latched=True)

    assert runtime_state.read_alarm_state() == {
        "condition": "MISLOAD",
        "action": "STOP",
        "latched": True,
    }


def test_write_alarm_state_creates_state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "nested" / "setup_state"
    monkeypatch.setattr(runtime_state, "STATE_DIR", state_dir)
    monkeypatch.setattr(runtime_state, "ALARM_STATE_PATH", state_dir / "alarm_state.json")

    runtime_state.write_alarm_state("OK", "NONE", latched=False)

    assert (state_dir / "alarm_state.json").exists()


def test_consume_ack_request_false_when_no_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "ACK_REQUEST_PATH", tmp_path / "ack_request.flag")

    assert runtime_state.consume_ack_request() is False


def test_request_ack_then_consume_returns_true_once(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "STATE_DIR", tmp_path)
    flag_path = tmp_path / "ack_request.flag"
    monkeypatch.setattr(runtime_state, "ACK_REQUEST_PATH", flag_path)

    runtime_state.request_ack()
    assert flag_path.exists()

    assert runtime_state.consume_ack_request() is True
    assert runtime_state.consume_ack_request() is False
