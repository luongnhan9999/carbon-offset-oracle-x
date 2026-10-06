# CarbonOffsetOracleX — Satellite & Registry Verified Carbon Credit Retirement Protocol

> **Track:** Real-World Settlement / Regenerative Finance (ReFi)  
> **Network:** GenLayer studionet (Chain ID: `61999` / `0xF1EF`)  
> **Contract Address:** `0x36B11e29C97d8953E78f092fa7065421A700a9D2`  
> **Target Environment:** [GenLayer Studio](https://studio.genlayer.com)  
> **Execution Engine:** GenVM / Optimistic Democracy Subjective Consensus  
> **Package / SDK:** `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`  
> **Test Suite:** 14 unit tests passing (`gltest` / `pytest`)

---

## 1. Deployment & Live Network Evidence

The `CarbonOffsetOracleX` Intelligent Contract is successfully deployed on GenLayer studionet:

- **Contract Address:** `0x36B11e29C97d8953E78f092fa7065421A700a9D2`
- **Network:** `studionet` (Chain ID: `61999` / `0xF1EF`)
- **Explorer:** [https://explorer.genlayer.com/address/0x36B11e29C97d8953E78f092fa7065421A700a9D2](https://explorer.genlayer.com/address/0x36B11e29C97d8953E78f092fa7065421A700a9D2)
- **Studio Explorer:** [https://explorer-studio.genlayer.com/address/0x36B11e29C97d8953E78f092fa7065421A700a9D2](https://explorer-studio.genlayer.com/address/0x36B11e29C97d8953E78f092fa7065421A700a9D2)
- **Contract Source:** [`contracts/carbon_offset_oracle_x.py`](contracts/carbon_offset_oracle_x.py)

---

## 2. Executive Summary & Problem Statement

The voluntary carbon market (VCM) is currently projected to grow into a multi-billion-dollar global asset class. However, it is chronically plagued by **double counting**, **double spending**, and **greenwashing**:

1. **Unretired Credits Sold On-Chain**: Brokers sell on-chain carbon tokens backed by registry credits that remain active and tradable in off-chain registries (such as Verra VCS, Gold Standard, Puro.earth, or UNFCCC).
2. **Re-assignment to Multiple Buyers**: The same retired certificate serial number is presented to multiple corporate buyers or ESG audit funds, claiming the emissions offset for different entities.
3. **The Oracle Blindspot in Traditional Smart Contracts**: EVM and traditional blockchains cannot inspect dynamic web pages without centralized, custodial oracle nodes that represent single points of failure and extortion.

**CarbonOffsetOracleX** solves this fundamentally by deploying an **Intelligent Contract** on GenLayer. It unites decentralized escrow, canonical registry verification, real-time web scraping via `gl.nondet.web.render`, and LLM subjective validator consensus (`gl.vm.run_nondet`) to cryptographically guarantee that carbon credits are **permanently retired for the exact designated beneficiary** before purchase funds are released.

---

## 3. Core Architecture & GenLayer Primitive

```
+-------------------------------------------------------------------------------------------------------+
|                                        CarbonOffsetOracleX Flow                                       |
+-------------------------------------------------------------------------------------------------------+

   [Buyer / ESG Fund]                      [Seller / Offset Broker]               [GenLayer Validators]
           |                                          |                                     |
           | 1. create_order()                        |                                     |
           |    (Locks Escrow: Serial, Tonnes,        |                                     |
           |     Beneficiary, Deadline)               |                                     |
           +----------------------------------------->|                                     |
           |                                          |                                     |
           |                                          | 2. deposit_seller_bond()            |
           |                                          |    (Stakes performance deposit)     |
           |                                          +------------------------------------>|
           |                                          |                                     |
           |                                          | 3. submit_retirement_proof()        |
           |                                          |    (Authoritative Registry URL)     |
           |                                          +------------------------------------>|
           |                                                                                |
           |                                4. adjudicate_retirement()                      |
           |                                   - Scrapes registry page via web.render       |
           |                                   - LLM Jury evaluates Serial, Status,        |
           |                                     Volume, Beneficiary match                  |
           |                                   - Discrete Consensus on Verdict              |
           |<-------------------------------------------------------------------------------+
           |
   [Settlement Outcomes]
   * VERIFIED_RETIRED : 100% Escrow + Bond disbursed to Seller; Serial permanently consumed on-chain.
   * FRAUD_OR_ACTIVE  : 100% Escrow refund + Seller Bond forfeited to Buyer as compensation.
   * INSUFFICIENT_DATA: Order stays SUBMITTED for retry/update; funds remain safe in escrow.
   * EXPIRED DEADLINE : Buyer recovers 100% escrow via safe recovery path (cancel_expired_order).
```

### Why GenLayer is Mandatory ("Without GenLayer, the project fails")
- **Direct On-Chain Scraping**: GenLayer validators fetch dynamic web content directly (`gl.nondet.web.render`) without relying on centralized intermediaries or off-chain scripts.
- **Subjective Natural Language Analysis**: Validator LLMs parse heterogeneous certificates across different carbon registries (Verra, Gold Standard, Puro.earth, UNFCCC), extracting unstructured metadata (legal entity name, project serial, cancellation reason).
- **Consensus on Truth**: Independent validators verify both the web content and LLM verdict, converging through Optimistic Democracy on a discrete outcome.

---

## 4. Security Pillars & Economic Determinism

### A. Persistent On-Chain Double-Spending Prevention
Traditional contracts have no memory across transactions unless explicitly registered. CarbonOffsetOracleX maintains an immutable registry:
```python
self.consumed_serials[f"{clean_std}:{clean_serial}"] = True
```
Once an order settles with `VERIFIED_RETIRED`, that exact certificate serial number (`project_standard:serial_number`) is **permanently consumed**. Any subsequent attempt to create an order or claim retirement for that serial is immediately rejected by the contract.

### B. Canonical Registry Host Whitelist
To prevent phishing attacks, spoofed portals, or local mock servers from defrauding buyers, retirement URLs are strictly validated against an authoritative registry domain whitelist:
- `registry.verra.org`, `verra.org` (Verified Carbon Standard)
- `goldstandard.org`, `registry.goldstandard.org` (Gold Standard)
- `unfccc.int`, `cdm.unfccc.int` (United Nations Clean Development Mechanism)
- `puro.earth`, `registry.puro.earth` (Puro Standard CO2 Removal)
- `american-carbon-registry.org` (ACR)
- `climateactionreserve.org` (CAR)
- Whitelist is extensible by contract owner via `add_allowed_registry()`.

### C. URL Serial Binding Protection
The contract enforces that the assigned credit serial number must appear directly inside the canonical URL path. This prevents a dishonest seller from submitting a legitimate retirement certificate URL belonging to an unrelated transaction.

### D. 100% Discrete Consensus Engine
In compliance with GenLayer Architecture Axis 2, validators achieve consensus on **discrete semantic verdicts** rather than fragile textual comparisons:
```python
def validator_fn(leader_res) -> bool:
    if not isinstance(leader_res, gl.vm.Return):
        return False
    leader = leader_res.calldata
    ...
    # DISCRETE EQUIVALENCE: 100% agreement on exact retirement verdict
    return l_verdict == m_verdict
```

| Verdict | Condition | Economic Consequence | Serial State |
|---|---|---|---|
| **`VERIFIED_RETIRED`** | Certificate explicitly confirms `RETIRED` / `CANCELLED`, matching serial, required volume, and designated beneficiary | 100% purchase escrow + seller bond released to seller | **Consumed permanently** |
| **`FRAUD_OR_ACTIVE`** | Credits are still active/tradable, volume is deficient, or beneficiary is an unrelated entity | 100% escrow refunded to buyer + seller bond forfeited to buyer | Not consumed |
| **`INSUFFICIENT_DATA`** | Registry page is 404, offline, unparseable, or LLM confidence < 65% | Order remains in `SUBMITTED` state for seller to update or retry | Not consumed |

### E. Safe Buyer Recovery Path (`cancel_expired_order`)
If a seller accepts an order but fails to submit an official registry proof URL before the agreed deadline (`deadline_timestamp`), the buyer can unilaterally invoke `cancel_expired_order()`. The buyer is refunded 100% of their escrow deposit, and any posted seller bond is safely returned.

---

## 5. Worked Example: Order Lifecycle & Settlement

Below is an end-to-end worked example verified with local `gltest` test runs:

### Step 1: Order Creation (Buyer Escrow)
- **Buyer (Alice):** `0x2bd806c97F0e00aF1a1fC3328fA763a9269723C8`
- **Seller (Bob):** `0x81b637d8fCD2C6da6359E6963113a1170de795e4`
- **Standard:** `VERRA`
- **Serial Number:** `VCS-1844-2023-45678`
- **Volume:** `500` Tonnes CO2
- **Beneficiary:** `"Acme CleanTech Corp"`
- **Escrow Deposit:** `10,000 GEN`
- **Deadline:** `2000000000` (Unix timestamp)
- **Resulting Order State (`get_order("1")`):**
  ```json
  {
    "order_id": "1",
    "buyer": "0x2bd806c97f0e00af1a1fc3328fa763a9269723c8",
    "seller": "0x81b637d8fcd2c6da6359e6963113a1170de795e4",
    "project_standard": "VERRA",
    "serial_number": "VCS-1844-2023-45678",
    "tonnes_co2": 500,
    "beneficiary_name": "Acme CleanTech Corp",
    "retirement_url": "",
    "escrow_amount": "10000",
    "seller_bond": "0",
    "status": "CREATED",
    "verdict": "PENDING",
    "deadline": "2000000000"
  }
  ```

### Step 2: Seller Bond Deposit
- **Caller (Bob):** `deposit_seller_bond("1")` with `2,000 GEN` attached.
- Order `seller_bond` updates to `2000 GEN`.

### Step 3: Retirement Proof Submission
- **Caller (Bob):** `submit_retirement_proof("1", "https://registry.verra.org/ui/verify/VCS-1844-2023-45678")`
- Canonical hostname `registry.verra.org` is validated against the whitelist.
- Serial number `VCS-1844-2023-45678` is verified within the URL path.
- Order status transitions to `"SUBMITTED"`.

### Step 4: Autonomous Validator Adjudication
- **Method:** `adjudicate_retirement("1")`
- GenLayer validators fetch the registry page via `gl.nondet.web.render`.
- LLM Auditor evaluates the page against order parameters:
  - Confirms status: `RETIRED / PERMANENTLY CANCELLED`
  - Confirms volume: `500 tonnes CO2`
  - Confirms beneficiary: `Acme CleanTech Corp`
- Discrete consensus achieved: `VERIFIED_RETIRED` (Confidence: 98%).
- **Settlement Execution:**
  - `12,000 GEN` (10,000 escrow + 2,000 bond) disbursed to Seller (`0x81b637d8...`).
  - Serial `VERRA:VCS-1844-2023-45678` marked consumed.
  - Subsequent attempt to create another order with `VCS-1844-2023-45678` is rejected with:  
    `"This carbon credit serial number has already been retired and settled on-chain."`

---

## 6. Contract API Reference

### Storage Schema
```python
owner: Address
order_count: bigint
orders: TreeMap[str, CarbonOrder]
consumed_serials: TreeMap[str, bool]
custom_allowed_registries: TreeMap[str, bool]
```

### Public Write Methods
- `create_order(seller: Address, project_standard: str, serial_number: str, tonnes_co2: int, beneficiary_name: str, deadline_timestamp: int) -> str` (`@gl.public.write.payable`)  
  Buyer locks GEN into purchase escrow for specific carbon credits with defined beneficiary.
- `deposit_seller_bond(order_id: str) -> None` (`@gl.public.write.payable`)  
  Seller deposits authenticity/performance collateral into order escrow.
- `submit_retirement_proof(order_id: str, retirement_url: str) -> None` (`@gl.public.write`)  
  Seller submits the official registry URL proving permanent retirement. Enforces canonical whitelist and serial binding.
- `adjudicate_retirement(order_id: str) -> None` (`@gl.public.write`)  
  Triggers validator web inspection, LLM audit, discrete consensus, and final settlement.
- `cancel_expired_order(order_id: str) -> None` (`@gl.public.write`)  
  Safe buyer recovery path to cancel unsubmitted orders past deadline and recover 100% refund.
- `add_allowed_registry(domain: str) -> None` (`@gl.public.write`)  
  Owner method to whitelist newly certified carbon registry domains.

### Public View Methods
- `is_registry_allowed(domain: str) -> bool`  
  Check if a registry domain is in the default or custom whitelist.
- `is_serial_consumed(project_standard: str, serial_number: str) -> bool`  
  Check whether a specific carbon credit serial has been retired and settled on-chain.
- `get_order(order_id: str) -> str`  
  Returns full JSON representation of a carbon offset order.
- `get_order_count() -> int`  
  Returns total number of created orders.
- `get_owner() -> str`  
  Returns contract owner address.
- `get_current_time() -> int`  
  Returns current deterministic contract timestamp.

---

## 7. Testing & Quality Assurance

The test suite covers full happy path and adversarial edge cases using `gltest`:

```bash
# Run complete test suite
pytest tests/ -v
```

### Test Coverage Matrix (14 Passed)
- `test_initial_state`: Initial storage state and default whitelist verification.
- `test_order_creation_success`: Escrow deposit, parameter assignment, state transition.
- `test_order_creation_validations`: Zero deposit, short serial, zero tonnes, short beneficiary, self-order, invalid deadline.
- `test_seller_bond_deposit`: Seller collateral staking and unauthorized caller rejection.
- `test_submit_retirement_proof_success_and_validations`: Whitelist enforcement, serial URL binding, scheme validation, permission check.
- `test_registry_whitelist_management`: Owner registry addition and non-owner access rejection.
- `test_adjudicate_verified_retired_and_double_spend_prevention`: Full retirement settlement, 100% payout, and rejection of re-used serials.
- `test_adjudicate_fraud_or_active_punishes_seller`: Fraudulent/active credit detection, buyer compensation, seller bond slashing.
- `test_adjudicate_insufficient_data_retains_submitted_state`: Handling 404, offline, or unparseable registry pages.
- `test_adjudicate_low_confidence_downgrades_to_insufficient`: Automatic fallback when LLM confidence is below threshold (< 65%).
- `test_safe_buyer_recovery_cancel_expired_order`: Deadline expiry time-warp, full buyer refund, and bond return.
- `test_cannot_adjudicate_unsubmitted_or_settled_order`: Guard preventing adjudication on non-submitted orders.
- `test_cannot_deposit_bond_to_submitted_order`: State machine locking on bond deposits once proof is submitted.
- `test_cannot_cancel_submitted_order`: Protection preventing buyer cancellation once proof has been submitted.

---

## 8. Deployment Guide (GenLayer Studio)

1. Open [GenLayer Studio](https://studio.genlayer.com).
2. Connect your Web3 wallet (MetaMask) and ensure you are connected to **studionet** (Chain ID: `61999` / `0xF1EF`).
3. Create a new contract file: `carbon_offset_oracle_x.py`.
4. Copy the complete source code from [`contracts/carbon_offset_oracle_x.py`](contracts/carbon_offset_oracle_x.py).
5. Click **Deploy**. Ensure the transaction receipt displays `Result: SUCCESS`.
6. Contract is live on studionet at: `0x36B11e29C97d8953E78f092fa7065421A700a9D2`.

---

## 9. License

MIT License. Built for the GenLayer Ecosystem.
