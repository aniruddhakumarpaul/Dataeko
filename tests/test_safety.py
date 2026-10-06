from triage.safety import detect_security_signals
import pytest


@pytest.mark.parametrize("ticket", [
    "There are purchases on my account that I did not authorize.",
    "My profile name and email were edited by a stranger.",
    "My account email is different and I never requested that change.",
    "Another person is reading my private messages.",
    "I didn't approve these transactions.",
    "Someone else made orders using my details.",
    "My account was hacked. How do I protect it?",
])
def test_compositional_security_paraphrases_escalate(ticket):
    assert detect_security_signals(ticket).score >= 0.45


def test_unauthorized_charge_is_security_signal():
    result = detect_security_signals("There is an unauthorized charge on my card and it is not mine.")
    assert result.triggered
    assert result.score >= 0.45


def test_normal_billing_question_is_not_forced_security():
    result = detect_security_signals("Where can I download my invoice for last month?")
    assert result.score < 0.45
