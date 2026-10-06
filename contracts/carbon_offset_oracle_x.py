# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
import json

if not hasattr(gl, "UserError"):
    try:
        gl.UserError = gl.vm.UserError
    except Exception:
        pass


def _addr_str(addr: Address) -> str:
    """Safely format an Address instance into a lowercase hex string."""
    try:
        return addr.as_hex.lower()
    except Exception:
        return str(addr).lower()


def _get_sender() -> Address:
    """Safely obtain transaction sender across GenVM runtime versions."""
    try:
        return gl.message.sender
    except Exception:
        try:
            return gl.message.sender_address
        except Exception:
            raise gl.UserError("Cannot resolve sender address.")


def _safe_transfer(recipient: Address, amount: bigint) -> None:
    """Safely disburse native GEN to an address using official GenLayer SDK pattern."""
    if amount <= bigint(0):
        return
    gl.get_contract_at(recipient).emit_transfer(value=u256(int(amount)))


DEFAULT_CARBON_REGISTRIES = (
    "registry.verra.org",
    "verra.org",
    "goldstandard.org",
    "registry.goldstandard.org",
    "unfccc.int",
    "cdm.unfccc.int",
    "puro.earth",
    "registry.puro.earth",
    "american-carbon-registry.org",
    "climateactionreserve.org",
    "mock-carbon.genlayer.com",
)


def _parse_url_host(raw_url: str) -> str:
    """Extract and validate normalized hostname from URL."""
    clean = raw_url.strip()
    if "?" in clean:
        clean = clean.split("?")[0]
    if "#" in clean:
        clean = clean.split("#")[0]
    clean = clean.strip()

    if clean.startswith("https://"):
        rest = clean[8:]
    elif clean.startswith("http://"):
        rest = clean[7:]
    else:
        raise gl.UserError("URL must begin with http:// or https://")

    host = rest.split("/", 1)[0].strip().lower()
    if ":" in host:
        host = host.split(":")[0].strip()
    if not host:
        raise gl.UserError("Invalid URL: missing host")
    return host


@allow_storage
@dataclass
class CarbonOrder:
    order_id: str
    buyer: Address
    seller: Address
    project_standard: str      # e.g., "VERRA", "GOLD_STANDARD", "PURO"
    serial_number: str         # Authoritative registry credit serial number
    tonnes_co2: bigint         # Number of metric tonnes of CO2
    beneficiary_name: str      # Corporate or individual legal entity retiring the credits
    retirement_url: str        # Canonical public registry view URL
    escrow_amount: bigint      # Total purchase escrow locked
    seller_bond: bigint        # Security deposit staked by seller
    status: str                # "CREATED", "SUBMITTED", "SETTLED", "CANCELLED"
    verdict: str               # "PENDING", "VERIFIED_RETIRED", "FRAUD_OR_ACTIVE", "INSUFFICIENT_DATA"
    reason: str                # AI consensus evaluation rationale
    deadline: bigint           # Deadline timestamp for retirement proof submission
    created_at: bigint
    resolved_at: bigint


class Contract(gl.Contract):
    """
    CarbonOffsetOracleX: Autonomous Satellite & Registry Verified Carbon Credit Retirement Protocol
    Track: Real-World Settlement / Regenerative Finance
    """
    owner: Address
    order_count: bigint
    orders: TreeMap[str, CarbonOrder]
    consumed_serials: TreeMap[str, bool]
    custom_allowed_registries: TreeMap[str, bool]

    def __init__(self):
        # GenVM automatically initializes TreeMap storage fields to empty.
        self.owner = _get_sender()
        self.order_count = bigint(0)

    def _get_current_timestamp(self) -> bigint:
        """Derive trusted deterministic execution timestamp from GenLayer transaction context."""
        try:
            from datetime import datetime
            dt_raw = getattr(gl.message, "datetime", None)
            if dt_raw is None and hasattr(gl, "message_raw") and isinstance(gl.message_raw, dict):
                dt_raw = gl.message_raw.get("datetime")
            if dt_raw:
                dt_str = str(dt_raw).strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                ts = int(dt.timestamp())
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        try:
            if hasattr(gl, "block") and hasattr(gl.block, "timestamp"):
                ts = int(gl.block.timestamp)
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        return bigint(0)

    def _parse_llm_json(self, text: str) -> dict:
        """Safely parse LLM responses, stripping markdown wrappers if present."""
        try:
            cleaned = str(text).strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception as e:
            return {
                "verdict": "INSUFFICIENT_DATA",
                "confidence": 0,
                "reason": f"Failed to parse LLM JSON: {str(e)[:100]}"
            }

    @gl.public.write
    def add_allowed_registry(self, domain: str) -> None:
        """Owner can add new certified carbon registries."""
        if _addr_str(_get_sender()) != _addr_str(self.owner):
            raise gl.UserError("Only owner can add allowed registry domains.")
        clean = domain.strip().lower()
        if len(clean) < 3:
            raise gl.UserError("Invalid registry domain name.")
        self.custom_allowed_registries[clean] = True

    @gl.public.view
    def is_registry_allowed(self, domain: str) -> bool:
        """Check if registry host is authorized."""
        clean = domain.strip().lower()
        if clean in DEFAULT_CARBON_REGISTRIES:
            return True
        return clean in self.custom_allowed_registries and self.custom_allowed_registries[clean]

    @gl.public.write.payable
    def create_order(
        self,
        seller: Address,
        project_standard: str,
        serial_number: str,
        tonnes_co2: int,
        beneficiary_name: str,
        deadline_timestamp: int
    ) -> str:
        """
        Buyer locks purchase funds into escrow for specific carbon credits with defined beneficiary.
        """
        deposit = bigint(gl.message.value)
        if deposit <= bigint(0):
            raise gl.UserError("Escrow payment must be greater than 0 GEN.")

        clean_std = project_standard.strip().upper()
        clean_serial = serial_number.strip().upper()
        clean_bene = beneficiary_name.strip()

        if len(clean_serial) < 5:
            raise gl.UserError("serial_number must be a valid unique credit identifier.")
        if tonnes_co2 <= 0:
            raise gl.UserError("tonnes_co2 must be greater than zero.")
        if len(clean_bene) < 3:
            raise gl.UserError("beneficiary_name must be a valid legal or individual entity.")

        if _addr_str(_get_sender()) == _addr_str(seller):
            raise gl.UserError("Buyer and seller cannot be identical.")

        # Prevent double-spending across the entire protocol
        serial_key = f"{clean_std}:{clean_serial}"
        if serial_key in self.consumed_serials and self.consumed_serials[serial_key]:
            raise gl.UserError("This carbon credit serial number has already been retired and settled on-chain.")

        dl = bigint(deadline_timestamp)
        if dl <= bigint(0):
            raise gl.UserError("deadline_timestamp must be positive.")

        now_ts = self._get_current_timestamp()
        if now_ts > bigint(0) and dl <= now_ts:
            raise gl.UserError("deadline_timestamp must be in the future.")

        self.order_count += bigint(1)
        oid = str(self.order_count)

        self.orders[oid] = CarbonOrder(
            order_id=oid,
            buyer=_get_sender(),
            seller=seller,
            project_standard=clean_std,
            serial_number=clean_serial,
            tonnes_co2=bigint(tonnes_co2),
            beneficiary_name=clean_bene,
            retirement_url="",
            escrow_amount=deposit,
            seller_bond=bigint(0),
            status="CREATED",
            verdict="PENDING",
            reason="Order created. Awaiting seller bond and official retirement registry URL.",
            deadline=dl,
            created_at=self.order_count,
            resolved_at=bigint(0)
        )

        return oid

    @gl.public.write.payable
    def deposit_seller_bond(self, order_id: str) -> None:
        """
        Seller stakes an authenticity/performance bond into the order escrow.
        """
        if order_id not in self.orders:
            raise gl.UserError("Order not found.")

        order = self.orders[order_id]
        if _addr_str(_get_sender()) != _addr_str(order.seller):
            raise gl.UserError("Only designated seller can deposit seller bond.")

        if order.status != "CREATED":
            raise gl.UserError("Cannot deposit bond to non-active order.")

        bond = bigint(gl.message.value)
        if bond <= bigint(0):
            raise gl.UserError("Bond must be greater than 0 GEN.")

        order.seller_bond += bond
        self.orders[order_id] = order

    @gl.public.write
    def submit_retirement_proof(self, order_id: str, retirement_url: str) -> None:
        """
        Seller submits the authoritative registry URL proving permanent retirement.
        """
        if order_id not in self.orders:
            raise gl.UserError("Order not found.")

        order = self.orders[order_id]
        if _addr_str(_get_sender()) != _addr_str(order.seller):
            raise gl.UserError("Only designated seller can submit retirement proof.")

        if order.status != "CREATED":
            raise gl.UserError("Order is not in CREATED state.")

        now_ts = self._get_current_timestamp()
        if now_ts > bigint(0) and now_ts > order.deadline:
            raise gl.UserError("Submission deadline has expired.")

        clean_url = retirement_url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.UserError("retirement_url must start with http:// or https://")

        # Canonical Registry Host Validation
        host = _parse_url_host(clean_url)
        is_allowed = (host in DEFAULT_CARBON_REGISTRIES) or (
            host in self.custom_allowed_registries and self.custom_allowed_registries[host]
        )
        if not is_allowed:
            raise gl.UserError(f"Registry domain '{host}' is not in the allowed registry whitelist.")

        # Canonical Serial Binding (Must contain serial number to prevent URL spoofing)
        if order.serial_number.lower() not in clean_url.lower():
            raise gl.UserError(f"Retirement URL must contain the assigned serial number '{order.serial_number}'.")

        order.retirement_url = clean_url
        order.status = "SUBMITTED"
        order.reason = "Retirement proof submitted. Ready for autonomous AI adjudication."
        self.orders[order_id] = order

    @gl.public.write
    def cancel_expired_order(self, order_id: str) -> None:
        """
        Safe Buyer Recovery Path:
        If seller fails to submit retirement proof before the deadline, buyer recovers 100% refund.
        """
        if order_id not in self.orders:
            raise gl.UserError("Order not found.")

        order = self.orders[order_id]
        if _addr_str(_get_sender()) != _addr_str(order.buyer):
            raise gl.UserError("Only buyer can cancel expired order.")

        if order.status == "SETTLED":
            raise gl.UserError("Order is already settled.")
        if order.status == "CANCELLED":
            raise gl.UserError("Order is already cancelled.")
        if order.status == "SUBMITTED":
            raise gl.UserError("Cannot cancel order once proof has been submitted.")

        now_ts = self._get_current_timestamp()
        if now_ts > bigint(0) and now_ts <= order.deadline:
            raise gl.UserError("Order deadline has not passed yet.")

        refund_val = order.escrow_amount
        seller_bond_val = order.seller_bond

        order.status = "CANCELLED"
        order.verdict = "INSUFFICIENT_DATA"
        order.reason = "Order cancelled by buyer after seller missed retirement deadline."
        order.resolved_at = self.order_count
        self.orders[order_id] = order

        # Refund buyer their full payment
        if refund_val > bigint(0):
            _safe_transfer(order.buyer, refund_val)
        # Return seller's deposit back to seller if any was posted
        if seller_bond_val > bigint(0):
            _safe_transfer(order.seller, seller_bond_val)

    @gl.public.write
    def adjudicate_retirement(self, order_id: str) -> None:
        """
        Validators inspect the official registry webpage on-chain,
        verify retirement status, volume, and beneficiary, and execute settlement deterministically.
        """
        if order_id not in self.orders:
            raise gl.UserError("Order not found.")

        order = self.orders[order_id]
        if order.status != "SUBMITTED":
            raise gl.UserError("Order must be in SUBMITTED state to adjudicate.")

        serial_local = str(order.serial_number)
        standard_local = str(order.project_standard)
        tonnes_local = int(order.tonnes_co2)
        beneficiary_local = str(order.beneficiary_name)
        url_local = str(order.retirement_url)

        def leader_fn():
            web_content = ""
            try:
                res = gl.nondet.web.render(url_local, mode="text")
                if hasattr(res, "content"):
                    web_content = res.content
                elif isinstance(res, dict) and "body" in res:
                    web_content = res["body"]
                else:
                    web_content = str(res)
            except Exception:
                web_content = ""

            lower_web = web_content[:500].lower() if web_content else ""
            if len(web_content.strip()) < 15 or "404 not found" in lower_web or "access denied" in lower_web:
                return {
                    "verdict": "INSUFFICIENT_DATA",
                    "confidence": 100,
                    "reason": "Registry URL is offline, blank, or returned 404/Access Denied."
                }

            snippet = web_content[:4000]

            prompt = f"""You are the Autonomous International Carbon Credit Retirement Auditor on GenLayer.
Verify whether the following carbon registry page proves that the credits have been PERMANENTLY RETIRED for the specified beneficiary.

REQUIRED ORDER PARAMETERS:
- STANDARD: {standard_local}
- SERIAL NUMBER: {serial_local}
- REQUIRED TONNES: {tonnes_local}
- DESIGNATED BENEFICIARY: {beneficiary_local}

OFFICIAL REGISTRY WEBPAGE CONTENT:
\"\"\"
{snippet}
\"\"\"

AUDIT VERIFICATION RULES:
Classify into strictly ONE of the following outcomes:
- "VERIFIED_RETIRED": The webpage explicitly confirms status is "RETIRED", "CANCELLED", or "CONSUMED", specifies at least {tonnes_local} tonnes, and names '{beneficiary_local}' as the beneficiary or reason for retirement.
- "FRAUD_OR_ACTIVE": The credits are still active/tradable, the serial number does not match, tonnes are significantly deficient, or the beneficiary is listed as a completely different unrelated entity.
- "INSUFFICIENT_DATA": The page is ambiguous, broken, lacks clear certificate metadata, or cannot confirm retirement state.

OUTPUT FORMAT:
Respond ONLY with a VALID JSON object (no markdown, no backticks):
{{
  "verdict": "VERIFIED_RETIRED" | "FRAUD_OR_ACTIVE" | "INSUFFICIENT_DATA",
  "confidence": <integer from 0 to 100>,
  "reason": "<concise explanation max 220 characters>"
}}"""

            try:
                raw_res = gl.nondet.exec_prompt(prompt, response_format="json")
                parsed = None
                if isinstance(raw_res, dict):
                    parsed = raw_res
                elif hasattr(raw_res, "content") and isinstance(raw_res.content, dict):
                    parsed = raw_res.content
                else:
                    text = raw_res.content if hasattr(raw_res, "content") else str(raw_res)
                    cleaned = str(text).strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    elif cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    parsed = json.loads(cleaned.strip())

                verdict_candidate = str(parsed.get("verdict", "INSUFFICIENT_DATA")).strip().upper()
                valid_verdicts = ("VERIFIED_RETIRED", "FRAUD_OR_ACTIVE", "INSUFFICIENT_DATA")
                if verdict_candidate not in valid_verdicts:
                    verdict_candidate = "INSUFFICIENT_DATA"

                try:
                    conf = int(parsed.get("confidence", 0))
                    conf = max(0, min(100, conf))
                except Exception:
                    conf = 50

                if conf < 65 and verdict_candidate != "INSUFFICIENT_DATA":
                    verdict_candidate = "INSUFFICIENT_DATA"

                reason_str = str(parsed.get("reason", "Audited by autonomous carbon jury."))[:220]

                return {
                    "verdict": verdict_candidate,
                    "confidence": conf,
                    "reason": reason_str
                }
            except Exception as e:
                return {
                    "verdict": "INSUFFICIENT_DATA",
                    "confidence": 0,
                    "reason": f"Evaluation error: {str(e)[:100]}"
                }

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            leader = leader_res.calldata
            if not isinstance(leader, dict) or "verdict" not in leader:
                return False

            valid_verdicts = ("VERIFIED_RETIRED", "FRAUD_OR_ACTIVE", "INSUFFICIENT_DATA")
            l_verdict = str(leader.get("verdict", "")).strip().upper()
            if l_verdict not in valid_verdicts:
                return False

            mine = leader_fn()
            m_verdict = str(mine.get("verdict", "")).strip().upper()

            # DISCRETE EQUIVALENCE: 100% agreement on exact retirement verdict
            return l_verdict == m_verdict

        adjudication_res = gl.vm.run_nondet(leader_fn, validator_fn)
        if isinstance(adjudication_res, dict):
            final_res = adjudication_res
        else:
            final_res = self._parse_llm_json(str(adjudication_res))

        verdict = str(final_res.get("verdict", "INSUFFICIENT_DATA")).strip().upper()
        valid_verdicts = ("VERIFIED_RETIRED", "FRAUD_OR_ACTIVE", "INSUFFICIENT_DATA")
        if verdict not in valid_verdicts:
            verdict = "INSUFFICIENT_DATA"

        reason = str(final_res.get("reason", "Consensus concluded."))

        order.verdict = verdict
        order.reason = reason
        order.resolved_at = self.order_count

        serial_key = f"{order.project_standard}:{order.serial_number}"

        if verdict == "VERIFIED_RETIRED":
            # Consume serial number permanently against any future reuse
            self.consumed_serials[serial_key] = True

            order.status = "SETTLED"
            self.orders[order_id] = order

            # Release full escrow amount + seller bond to seller
            total_seller = order.escrow_amount + order.seller_bond
            _safe_transfer(order.seller, total_seller)

        elif verdict == "FRAUD_OR_ACTIVE":
            # Fraudulent or unretired: 100% refund to buyer + seller bond forfeited to buyer
            order.status = "CANCELLED"
            self.orders[order_id] = order

            compensation = order.escrow_amount + order.seller_bond
            _safe_transfer(order.buyer, compensation)

        else:
            # INSUFFICIENT_DATA: Keep order in SUBMITTED state so seller can update link or retry
            self.orders[order_id] = order

    @gl.public.view
    def is_serial_consumed(self, project_standard: str, serial_number: str) -> bool:
        """Check if a specific carbon credit serial has already been settled and consumed on-chain."""
        serial_key = f"{project_standard.strip().upper()}:{serial_number.strip().upper()}"
        return serial_key in self.consumed_serials and self.consumed_serials[serial_key]

    @gl.public.view
    def get_order(self, order_id: str) -> str:
        """Retrieve details of a carbon credit order as a JSON string."""
        if order_id not in self.orders:
            raise gl.UserError("Order not found.")
        o = self.orders[order_id]
        return json.dumps({
            "order_id": o.order_id,
            "buyer": _addr_str(o.buyer),
            "seller": _addr_str(o.seller),
            "project_standard": o.project_standard,
            "serial_number": o.serial_number,
            "tonnes_co2": int(o.tonnes_co2),
            "beneficiary_name": o.beneficiary_name,
            "retirement_url": o.retirement_url,
            "escrow_amount": str(o.escrow_amount),
            "seller_bond": str(o.seller_bond),
            "status": o.status,
            "verdict": o.verdict,
            "reason": o.reason,
            "deadline": str(o.deadline),
            "created_at": str(o.created_at),
            "resolved_at": str(o.resolved_at)
        })

    @gl.public.view
    def get_current_time(self) -> int:
        """Retrieve current contract execution timestamp."""
        return int(str(self._get_current_timestamp()))

    @gl.public.view
    def get_order_count(self) -> int:
        return int(self.order_count)

    @gl.public.view
    def get_owner(self) -> str:
        return _addr_str(self.owner)
