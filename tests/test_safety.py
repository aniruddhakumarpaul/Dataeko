from triage.safety import detect_security_signals


def test_unauthorized_charge_is_security_signal():
    result = detect_security_signals("There is an unauthorized charge on my card and it is not mine.")
    assert result.triggered
    assert result.score >= 0.45


def test_normal_billing_question_is_not_forced_security():
    result = detect_security_signals("Where can I download my invoice for last month?")
    assert result.score < 0.45
