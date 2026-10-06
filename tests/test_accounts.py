from concurrent.futures import ThreadPoolExecutor
import hashlib
import time

import pytest

from conftest import PASSWORD, otp_for
from triage.accounts import password_hash, check_password


def challenge(backend):
    return backend.accounts.begin_login("EMP-ALICE", backend.people["alice"].phone, PASSWORD)


def test_password_hash_is_salted_and_wrong_password_rejected():
    a, b = password_hash(PASSWORD), password_hash(PASSWORD)
    assert a != b and PASSWORD not in a
    assert check_password(PASSWORD, a)
    assert not check_password("wrong password", a)


@pytest.mark.parametrize("password", ["1", "a", "abc", "x" * 256])
def test_demo_password_has_no_length_or_complexity_policy(password):
    assert check_password(password, password_hash(password, demo=True))


def test_empty_demo_password_and_short_non_demo_password_rejected():
    with pytest.raises(ValueError, match="Enter a password"):
        password_hash("", demo=True)
    with pytest.raises(ValueError, match="12 to 128"):
        password_hash("1")


def test_demo_registration_accepts_single_character_password(backend):
    backend.accounts.invite_employee(tenant_id=backend.people["alice"].tenant_id,
        employee_id="EMP-SHORT",name="Short demo",phone="+12025550119",email="short@example.test")
    c = backend.accounts.register_customer(employee_id="EMP-SHORT",name="Short demo",
        phone="+12025550119",email="short@example.test",password="1")
    token = backend.accounts.verify_otp(c,otp_for(backend,c))
    p = backend.accounts.resolve_session(token)
    with backend.store._connect() as db:
        stored = db.execute("SELECT password_hash FROM accounts WHERE id=?",(p.user_id,)).fetchone()[0]
    assert check_password("1",stored)


def test_login_requires_otp_and_code_is_single_use(backend):
    c = challenge(backend)
    assert backend.accounts.resolve_session(c) is None
    token = backend.accounts.verify_otp(c, otp_for(backend, c))
    assert backend.accounts.resolve_session(token).user_id == backend.people["alice"].user_id
    with pytest.raises(ValueError, match="already used"):
        backend.accounts.verify_otp(c, otp_for(backend, c))


def test_wrong_otp_attempts_are_persisted_and_capped(backend):
    c = challenge(backend)
    actual = otp_for(backend, c)
    wrong = "999999" if actual != "999999" else "111111"
    for _ in range(5):
        with pytest.raises(ValueError):
            backend.accounts.verify_otp(c, wrong)
    with pytest.raises(ValueError, match="expired"):
        backend.accounts.verify_otp(c, actual)


def test_expired_otp_rejected(backend):
    c = challenge(backend)
    code = otp_for(backend, c)
    with backend.store._connect() as db:
        db.execute("UPDATE login_challenges SET expires_at=? WHERE id=?", (time.time() - 1, c))
    with pytest.raises(ValueError, match="expired"):
        backend.accounts.verify_otp(c, code)


def test_concurrent_otp_reuse_only_creates_one_session(backend):
    c = challenge(backend)
    code = otp_for(backend, c)
    def attempt():
        try:
            return backend.accounts.verify_otp(c, code)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(token is not None for token in tokens) == 1


def test_wrong_tenant_and_password_cannot_sign_in(backend):
    with pytest.raises(ValueError, match="incorrect"):
        backend.accounts.begin_login("EMP-EVE", backend.people["alice"].phone, PASSWORD)
    with pytest.raises(ValueError, match="incorrect"):
        backend.accounts.begin_login("EMP-ALICE", backend.people["alice"].phone, "wrong")


def test_login_throttle_survives_new_service_instances(backend):
    for _ in range(5):
        with pytest.raises(ValueError):
            backend.accounts.begin_login("EMP-ALICE", backend.people["alice"].phone, "wrong")
    with pytest.raises(ValueError, match="15 minutes"):
        backend.accounts.begin_login("EMP-ALICE", backend.people["alice"].phone, PASSWORD)


def test_logout_revokes_session(backend):
    c = challenge(backend)
    token = backend.accounts.verify_otp(c, otp_for(backend, c))
    backend.accounts.logout(token)
    assert backend.accounts.resolve_session(token) is None


def test_registration_uses_assigned_employee_id_and_does_not_grant_staff_role(backend):
    backend.accounts.invite_employee(tenant_id=backend.people["alice"].tenant_id, employee_id="EMP-NEW", name="New customer", phone="+12025550116", email="new@example.test")
    c = backend.accounts.register_customer(employee_id="EMP-NEW", name="New customer",
        phone="+12025550116", email="new@example.test", password=PASSWORD)
    token = backend.accounts.verify_otp(c, otp_for(backend, c))
    p = backend.accounts.resolve_session(token)
    assert p.role == "customer" and p.tenant_id == backend.people["alice"].tenant_id


def test_employee_id_cannot_be_registered_with_another_email(backend):
    backend.accounts.invite_employee(tenant_id=backend.people["alice"].tenant_id, employee_id="EMP-NEW", name="New customer", phone="+12025550116", email="new@example.test")
    with pytest.raises(ValueError, match="assigned"):
        backend.accounts.register_customer(employee_id="EMP-NEW", name="Wrong person", phone="+12025550116", email="attacker@example.test", password=PASSWORD)


def test_missing_email_configuration_cannot_bypass_otp(backend, monkeypatch):
    backend.mail.mode = "smtp"
    backend.mail.settings = {}
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        challenge(backend)


def test_demo_custom_employee_registration_creates_private_inbox_without_invite(backend):
    from triage.mailboxes import MailboxService
    access = {}
    c = backend.accounts.register_customer(employee_id="em-2026",name="Test customer",
        phone="+12025550122",email="custom@example.test",password="1",demo_access=access)
    assert access["email"] == "custom@example.test" and access["password"]
    boxes = MailboxService(backend.store)
    assert boxes.resolve_session(boxes.sign_in(access["email"],access["password"]))
    token = backend.accounts.verify_otp(c,otp_for(backend,c))
    person = backend.accounts.resolve_session(token)
    assert person.employee_id == "EM-2026" and person.role == "customer"
    assert person.tenant_name == "Dataeko demo"


@pytest.mark.parametrize("employee_id",["EM2026","EMP-2026","EM-26","EM-20267"])
def test_demo_custom_id_format_is_em_plus_four_digits(backend,employee_id):
    with pytest.raises(ValueError,match="four digits"):
        backend.accounts.register_customer(employee_id=employee_id,name="Test customer",
            phone="+12025550122",email="custom@example.test",password="1")


def test_custom_id_cannot_overwrite_existing_account(backend):
    access = {}
    c = backend.accounts.register_customer(employee_id="EM-2026",name="Test customer",
        phone="+12025550122",email="custom@example.test",password="1",demo_access=access)
    with pytest.raises(ValueError,match="already in use"):
        backend.accounts.register_customer(employee_id="EM-2026",name="Different customer",
            phone="+12025550123",email="different@example.test",password="2")
    assert backend.accounts.verify_otp(c,otp_for(backend,c))


def test_non_demo_custom_registration_still_requires_an_invitation(backend):
    backend.mail.mode = "smtp"
    backend.mail.settings = {"host":"smtp.example.test","from":"support@example.test"}
    with pytest.raises(ValueError,match="assigned by"):
        backend.accounts.register_customer(employee_id="EM-2026",name="Test customer",
            phone="+12025550122",email="custom@example.test",password=PASSWORD)
