import pytest
import json
from gltest import *


def _to_hex(addr) -> str:
    """Helper to convert test address to lowercase hex."""
    if hasattr(addr, "as_hex"):
        return addr.as_hex.lower()
    if isinstance(addr, bytes):
        return "0x" + addr.hex().lower()
    return str(addr).lower()


def setup_post_message_hook(direct_vm):
    """Intercept cross-contract calls / emit_transfer to track recipient balances in tests."""
    def post_message_hook(vm, request):
        if "PostMessage" in request:
            pm = request["PostMessage"]
            dest_addr = pm["address"]
            value = int(pm.get("value", 0))
            dest_bytes = vm._to_bytes(dest_addr)
            vm._balances[dest_bytes] = vm._balances.get(dest_bytes, 0) + value
            return {"ok": None}
        if "EthSend" in request:
            es = request["EthSend"]
            dest_addr = es.get("to") or es.get("address") or es.get("recipient")
            value = int(es.get("value", 0))
            dest_bytes = vm._to_bytes(dest_addr)
            vm._balances[dest_bytes] = vm._balances.get(dest_bytes, 0) + value
            return {"ok": None}
        return None

    direct_vm._gl_call_hook = post_message_hook


@pytest.fixture
def contract(direct_deploy):
    c = direct_deploy("contracts/carbon_offset_oracle_x.py")
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "genlayer.gl" or name.endswith(".gl"):
            if hasattr(mod, "vm") and hasattr(mod.vm, "UserError"):
                setattr(mod, "UserError", mod.vm.UserError)
        if "genlayer" in name and hasattr(mod, "gl"):
            gl_obj = getattr(mod, "gl")
            if hasattr(gl_obj, "vm") and hasattr(gl_obj.vm, "UserError"):
                setattr(gl_obj, "UserError", gl_obj.vm.UserError)
    return c


def test_initial_state(contract, direct_vm):
    """Verify clean initial state on contract deployment."""
    assert contract.get_order_count() == 0
    assert contract.get_owner() == _to_hex(direct_vm.sender)
    assert contract.is_registry_allowed("registry.verra.org") is True
    assert contract.is_registry_allowed("goldstandard.org") is True
    assert contract.is_registry_allowed("unfccc.int") is True
    assert contract.is_registry_allowed("puro.earth") is True
    assert contract.is_registry_allowed("unknown-registry.xyz") is False


def test_order_creation_success(contract, direct_vm, direct_alice, direct_bob):
    """1. Test buyer creating carbon offset order with 10,000 GEN escrow."""
    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    deadline = (now_ts if now_ts > 0 else 1000) + 7200
    order_id = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-1844-2023-45678",
        tonnes_co2=500,
        beneficiary_name="Acme CleanTech Corp",
        deadline_timestamp=deadline,
    )
    assert str(order_id) == "1"
    assert contract.get_order_count() == 1

    order_data = json.loads(contract.get_order(order_id))
    assert order_data["order_id"] == "1"
    assert order_data["buyer"] == _to_hex(direct_alice)
    assert order_data["seller"] == _to_hex(direct_bob)
    assert order_data["project_standard"] == "VERRA"
    assert order_data["serial_number"] == "VCS-1844-2023-45678"
    assert order_data["tonnes_co2"] == 500
    assert order_data["beneficiary_name"] == "Acme CleanTech Corp"
    assert order_data["escrow_amount"] == "10000"
    assert order_data["seller_bond"] == "0"
    assert order_data["status"] == "CREATED"
    assert order_data["verdict"] == "PENDING"
    assert order_data["deadline"] == str(deadline)


def test_order_creation_validations(contract, direct_vm, direct_alice, direct_bob):
    """2. Test input validation guards on order creation."""
    direct_vm.sender = direct_alice

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200

    # Zero deposit
    direct_vm.value = 0
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=500,
            beneficiary_name="Acme CleanTech Corp",
            deadline_timestamp=valid_deadline,
        )
    assert "Escrow payment must be greater than 0 GEN" in str(exc.value)

    # Short serial number
    direct_vm.value = 5000
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS",
            tonnes_co2=500,
            beneficiary_name="Acme CleanTech Corp",
            deadline_timestamp=valid_deadline,
        )
    assert "serial_number must be a valid unique credit identifier" in str(exc.value)

    # Tonnes <= 0
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=0,
            beneficiary_name="Acme CleanTech Corp",
            deadline_timestamp=valid_deadline,
        )
    assert "tonnes_co2 must be greater than zero" in str(exc.value)

    # Short beneficiary name
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=500,
            beneficiary_name="AB",
            deadline_timestamp=valid_deadline,
        )
    assert "beneficiary_name must be a valid legal or individual entity" in str(exc.value)

    # Buyer == Seller
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_alice,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=500,
            beneficiary_name="Acme CleanTech Corp",
            deadline_timestamp=valid_deadline,
        )
    assert "Buyer and seller cannot be identical" in str(exc.value)

    # Non-positive deadline
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=500,
            beneficiary_name="Acme CleanTech Corp",
            deadline_timestamp=0,
        )
    assert "deadline_timestamp must be positive" in str(exc.value)


def test_seller_bond_deposit(contract, direct_vm, direct_alice, direct_bob, direct_charlie):
    """3. Test seller depositing performance/authenticity bond."""
    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="GOLD_STANDARD",
        serial_number="GS1-1-DE-GS12345",
        tonnes_co2=100,
        beneficiary_name="EcoLogistics Europe",
        deadline_timestamp=valid_deadline,
    )

    # Non-seller cannot deposit bond
    direct_vm.sender = direct_charlie
    direct_vm.value = 2000
    with pytest.raises(Exception) as exc:
        contract.deposit_seller_bond(oid)
    assert "Only designated seller can deposit seller bond" in str(exc.value)

    # Seller deposits 2,000 GEN bond
    direct_vm.sender = direct_bob
    direct_vm.value = 2000
    contract.deposit_seller_bond(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["seller_bond"] == "2000"


def test_submit_retirement_proof_success_and_validations(contract, direct_vm, direct_alice, direct_bob, direct_charlie):
    """4. Test submission of official retirement proof and canonical security checks."""
    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-1844-2023-45678",
        tonnes_co2=500,
        beneficiary_name="Acme CleanTech Corp",
        deadline_timestamp=valid_deadline,
    )

    # Non-seller cannot submit proof
    direct_vm.sender = direct_charlie
    with pytest.raises(Exception) as exc:
        contract.submit_retirement_proof(oid, "https://registry.verra.org/ui/verify/VCS-1844-2023-45678")
    assert "Only designated seller can submit retirement proof" in str(exc.value)

    # Invalid scheme
    direct_vm.sender = direct_bob
    with pytest.raises(Exception) as exc:
        contract.submit_retirement_proof(oid, "ftp://registry.verra.org/ui/verify/VCS-1844-2023-45678")
    assert "retirement_url must start with http:// or https://" in str(exc.value)

    # Non-whitelisted registry domain
    with pytest.raises(Exception) as exc:
        contract.submit_retirement_proof(oid, "https://fake-carbon-registry.org/verify/VCS-1844-2023-45678")
    assert "not in the allowed registry whitelist" in str(exc.value)

    # Serial number spoofing (missing assigned serial number in URL)
    with pytest.raises(Exception) as exc:
        contract.submit_retirement_proof(oid, "https://registry.verra.org/ui/verify/OTHER-SERIAL-99999")
    assert "must contain the assigned serial number" in str(exc.value)

    # Successful submission with canonical URL
    valid_url = "https://registry.verra.org/ui/verify/VCS-1844-2023-45678"
    contract.submit_retirement_proof(oid, valid_url)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["status"] == "SUBMITTED"
    assert order_data["retirement_url"] == valid_url


def test_registry_whitelist_management(contract, direct_vm, direct_bob):
    """5. Test owner adding custom carbon registry domains."""
    from genlayer import Address
    owner_addr = Address(contract.get_owner())
    direct_vm.sender = owner_addr
    assert contract.is_registry_allowed("carbon.registry.gov.sg") is False

    # Owner adds new registry domain
    contract.add_allowed_registry("carbon.registry.gov.sg")
    assert contract.is_registry_allowed("carbon.registry.gov.sg") is True

    # Non-owner cannot add registry domain
    direct_vm.sender = direct_bob
    with pytest.raises(Exception) as exc:
        contract.add_allowed_registry("fake-registry.io")
    assert "Only owner can add allowed registry domains" in str(exc.value)


def test_adjudicate_verified_retired_and_double_spend_prevention(contract, direct_vm, direct_alice, direct_bob):
    """
    6. Scenario: VERIFIED_RETIRED
    AI consensus confirms valid retirement -> 100% funds released to seller, serial permanently consumed.
    Subsequent order creation with that serial MUST be rejected (double-spending protection).
    """
    setup_post_message_hook(direct_vm)

    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-1844-2023-45678",
        tonnes_co2=500,
        beneficiary_name="Acme CleanTech Corp",
        deadline_timestamp=valid_deadline,
    )

    # Seller stakes 2,000 GEN bond
    direct_vm.sender = direct_bob
    direct_vm.value = 2000
    contract.deposit_seller_bond(oid)

    # Seller submits proof
    proof_url = "https://registry.verra.org/ui/verify/VCS-1844-2023-45678"
    contract.submit_retirement_proof(oid, proof_url)

    # Mock web rendering of official registry page
    registry_html = (
        "Certificate Details: Verra VCS Registry. "
        "Serial Number: VCS-1844-2023-45678. "
        "Status: RETIRED / PERMANENTLY CANCELLED. "
        "Quantity: 500 metric tonnes CO2. "
        "Beneficiary: Acme CleanTech Corp. "
        "Retirement Reason: Scope 1 & 2 Emissions Neutralization 2026."
    )
    direct_vm.mock_web(".*registry\\.verra\\.org.*", {"status": 200, "body": registry_html})

    # Mock LLM verdict
    direct_vm.mock_llm(
        ".*",
        json.dumps({
            "verdict": "VERIFIED_RETIRED",
            "confidence": 98,
            "reason": "Official Verra VCS certificate confirms 500 tonnes permanently retired for Acme CleanTech Corp."
        })
    )

    contract.adjudicate_retirement(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["status"] == "SETTLED"
    assert order_data["verdict"] == "VERIFIED_RETIRED"
    assert contract.is_serial_consumed("VERRA", "VCS-1844-2023-45678") is True

    # Check seller received escrow + bond (10,000 + 2,000 = 12,000 GEN)
    bob_bytes = direct_vm._to_bytes(direct_bob)
    assert direct_vm._balances.get(bob_bytes, 0) == 12000

    # DOUBLE-SPEND REJECTION: Attempting to create new order with consumed serial must fail
    direct_vm.sender = direct_alice
    direct_vm.value = 8000
    with pytest.raises(Exception) as exc:
        contract.create_order(
            seller=direct_bob,
            project_standard="VERRA",
            serial_number="VCS-1844-2023-45678",
            tonnes_co2=500,
            beneficiary_name="Other Buyer",
            deadline_timestamp=valid_deadline + 1000,
        )
    assert "already been retired and settled on-chain" in str(exc.value)


def test_adjudicate_fraud_or_active_punishes_seller(contract, direct_vm, direct_alice, direct_bob):
    """
    7. Scenario: FRAUD_OR_ACTIVE
    Credits are still active (not retired) or assigned to a different entity:
    100% escrow refunded to buyer + seller bond forfeited to buyer as compensation.
    Serial is NOT marked as consumed.
    """
    setup_post_message_hook(direct_vm)

    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="GOLD_STANDARD",
        serial_number="GS1-999-ACTIVE-001",
        tonnes_co2=200,
        beneficiary_name="Global Green Energy",
        deadline_timestamp=valid_deadline,
    )

    # Seller posts 3,000 GEN bond
    direct_vm.sender = direct_bob
    direct_vm.value = 3000
    contract.deposit_seller_bond(oid)

    # Seller submits link
    proof_url = "https://registry.goldstandard.org/credit/GS1-999-ACTIVE-001"
    contract.submit_retirement_proof(oid, proof_url)

    # Webpage shows active status
    active_html = (
        "Gold Standard Registry: Serial GS1-999-ACTIVE-001. "
        "Status: ACTIVE / TRADABLE. Credits have not been retired."
    )
    direct_vm.mock_web(".*goldstandard\\.org.*", {"status": 200, "body": active_html})

    direct_vm.mock_llm(
        ".*",
        json.dumps({
            "verdict": "FRAUD_OR_ACTIVE",
            "confidence": 95,
            "reason": "Credits are still listed as ACTIVE and tradable on Gold Standard registry, not permanently retired."
        })
    )

    contract.adjudicate_retirement(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["status"] == "CANCELLED"
    assert order_data["verdict"] == "FRAUD_OR_ACTIVE"
    assert contract.is_serial_consumed("GOLD_STANDARD", "GS1-999-ACTIVE-001") is False

    # Buyer receives escrow + seller bond compensation (10,000 + 3,000 = 13,000 GEN)
    alice_bytes = direct_vm._to_bytes(direct_alice)
    assert direct_vm._balances.get(alice_bytes, 0) == 13000


def test_adjudicate_insufficient_data_retains_submitted_state(contract, direct_vm, direct_alice, direct_bob):
    """
    8. Scenario: INSUFFICIENT_DATA (Registry 404 or unparseable page)
    Order remains in SUBMITTED state to allow seller to fix URL or wait for registry uptime.
    """
    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="PURO",
        serial_number="CORC-PURO-2026-9999",
        tonnes_co2=150,
        beneficiary_name="Nordic Carbon Offsets",
        deadline_timestamp=valid_deadline,
    )

    direct_vm.sender = direct_bob
    proof_url = "https://registry.puro.earth/view/CORC-PURO-2026-9999"
    contract.submit_retirement_proof(oid, proof_url)

    # 404 Not Found
    direct_vm.mock_web(".*puro\\.earth.*", {"status": 404, "body": "404 Not Found - Registry service temporarily unavailable."})

    contract.adjudicate_retirement(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["status"] == "SUBMITTED"
    assert order_data["verdict"] == "INSUFFICIENT_DATA"
    assert "404" in order_data["reason"] or "offline" in order_data["reason"]


def test_adjudicate_low_confidence_downgrades_to_insufficient(contract, direct_vm, direct_alice, direct_bob):
    """
    9. Scenario: LLM returns low confidence (< 65)
    Should automatically downgrade verdict to INSUFFICIENT_DATA.
    """
    direct_vm.sender = direct_alice
    direct_vm.value = 10000

    now_ts = contract.get_current_time()
    valid_deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="UNFCCC",
        serial_number="CDM-CER-2026-12345",
        tonnes_co2=300,
        beneficiary_name="Pacific Eco Clean",
        deadline_timestamp=valid_deadline,
    )

    direct_vm.sender = direct_bob
    proof_url = "https://unfccc.int/registry/CDM-CER-2026-12345"
    contract.submit_retirement_proof(oid, proof_url)

    direct_vm.mock_web(".*unfccc\\.int.*", {"status": 200, "body": "Ambiguous CDM Registry page with blurry details."})
    direct_vm.mock_llm(
        ".*",
        json.dumps({
            "verdict": "VERIFIED_RETIRED",
            "confidence": 45,  # Below 65 threshold
            "reason": "Ambiguous certificate text, unable to confirm beneficiary with certainty."
        })
    )

    contract.adjudicate_retirement(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["verdict"] == "INSUFFICIENT_DATA"
    assert order_data["status"] == "SUBMITTED"


def test_safe_buyer_recovery_cancel_expired_order(contract, direct_vm, direct_alice, direct_bob, direct_charlie):
    """
    10. Safe Buyer Recovery Path:
    Buyer cancels expired order if seller fails to submit proof before deadline.
    Recovers 100% escrow payment; seller bond is also returned to seller.
    """
    setup_post_message_hook(direct_vm)

    direct_vm.warp("2026-06-01T10:00:00Z")
    now_ts = contract.get_current_time()
    deadline = now_ts + 3600  # 1 hour in the future

    direct_vm.sender = direct_alice
    direct_vm.value = 10000
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-9999-EXPIRED",
        tonnes_co2=100,
        beneficiary_name="Solar Energy Initiative",
        deadline_timestamp=deadline,
    )

    # Seller deposited 1,000 GEN bond
    direct_vm.sender = direct_bob
    direct_vm.value = 1000
    contract.deposit_seller_bond(oid)

    # Cannot cancel before deadline has passed
    direct_vm.sender = direct_alice
    with pytest.raises(Exception) as exc:
        contract.cancel_expired_order(oid)
    assert "Order deadline has not passed yet" in str(exc.value)

    # Warp past deadline
    direct_vm.warp("2026-06-01T12:00:00Z")
    assert contract.get_current_time() > deadline

    # Non-buyer cannot cancel
    direct_vm.sender = direct_charlie
    with pytest.raises(Exception) as exc:
        contract.cancel_expired_order(oid)
    assert "Only buyer can cancel expired order" in str(exc.value)

    # Buyer cancels expired unsubmitted order
    direct_vm.sender = direct_alice
    contract.cancel_expired_order(oid)

    order_data = json.loads(contract.get_order(oid))
    assert order_data["status"] == "CANCELLED"
    assert order_data["verdict"] == "INSUFFICIENT_DATA"

    # Buyer got 10,000 GEN refund
    alice_bytes = direct_vm._to_bytes(direct_alice)
    assert direct_vm._balances.get(alice_bytes, 0) == 10000

    # Seller got 1,000 GEN bond returned
    bob_bytes = direct_vm._to_bytes(direct_bob)
    assert direct_vm._balances.get(bob_bytes, 0) == 1000


def test_cannot_adjudicate_unsubmitted_or_settled_order(contract, direct_vm, direct_alice, direct_bob):
    """11. Adjudication can only happen when status is SUBMITTED."""
    direct_vm.sender = direct_alice
    direct_vm.value = 5000

    now_ts = contract.get_current_time()
    deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-UNSUBMITTED-01",
        tonnes_co2=50,
        beneficiary_name="Clean Earth Fund",
        deadline_timestamp=deadline,
    )

    # In CREATED state, adjudication must fail
    with pytest.raises(Exception) as exc:
        contract.adjudicate_retirement(oid)
    assert "Order must be in SUBMITTED state to adjudicate" in str(exc.value)


def test_cannot_deposit_bond_to_submitted_order(contract, direct_vm, direct_alice, direct_bob):
    """12. Seller cannot deposit bond once order is SUBMITTED."""
    direct_vm.sender = direct_alice
    direct_vm.value = 5000

    now_ts = contract.get_current_time()
    deadline = (now_ts if now_ts > 0 else 1000) + 7200
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-BOND-AFTER-SUBMIT",
        tonnes_co2=50,
        beneficiary_name="Clean Earth Fund",
        deadline_timestamp=deadline,
    )

    direct_vm.sender = direct_bob
    contract.submit_retirement_proof(oid, "https://registry.verra.org/ui/verify/VCS-BOND-AFTER-SUBMIT")

    # Try to deposit bond after submission
    direct_vm.value = 1000
    with pytest.raises(Exception) as exc:
        contract.deposit_seller_bond(oid)
    assert "Cannot deposit bond to non-active order" in str(exc.value)


def test_cannot_cancel_submitted_order(contract, direct_vm, direct_alice, direct_bob):
    """13. Buyer cannot cancel order once proof has been submitted."""
    direct_vm.warp("2026-06-01T10:00:00Z")
    now_ts = contract.get_current_time()
    deadline = now_ts + 3600

    direct_vm.sender = direct_alice
    direct_vm.value = 5000
    oid = contract.create_order(
        seller=direct_bob,
        project_standard="VERRA",
        serial_number="VCS-SUBMITTED-CANNOT-CANCEL",
        tonnes_co2=50,
        beneficiary_name="Clean Earth Fund",
        deadline_timestamp=deadline,
    )

    direct_vm.sender = direct_bob
    contract.submit_retirement_proof(oid, "https://registry.verra.org/ui/verify/VCS-SUBMITTED-CANNOT-CANCEL")

    # Warp past deadline
    direct_vm.warp("2026-06-01T12:00:00Z")

    # Buyer tries to cancel submitted order
    direct_vm.sender = direct_alice
    with pytest.raises(Exception) as exc:
        contract.cancel_expired_order(oid)
    assert "Cannot cancel order once proof has been submitted" in str(exc.value)
