from autonomous.contract_negotiation import ContractProposal, negotiate_contract


def test_contract_negotiation_agrees_with_stable_checksum_on_same_schema() -> None:
    result_a = negotiate_contract(
        [
            ContractProposal(role="frontend", schema={"paths": ["a.ts"], "mode": "strict"}),
            ContractProposal(role="backend", schema={"mode": "strict", "paths": ["a.ts"]}),
        ],
        contract_id="contract-demo",
    )
    result_b = negotiate_contract(
        [
            ContractProposal(role="frontend", schema={"mode": "strict", "paths": ["a.ts"]}),
            ContractProposal(role="backend", schema={"paths": ["a.ts"], "mode": "strict"}),
        ],
        contract_id="contract-demo",
    )

    assert result_a.agreed is True
    assert result_b.agreed is True
    assert result_a.contract_checksum == result_b.contract_checksum


def test_contract_negotiation_rejects_mismatch_before_execution() -> None:
    result = negotiate_contract(
        [
            ContractProposal(role="frontend", schema={"request": {"id": "string"}}),
            ContractProposal(role="backend", schema={"request": {"id": "number"}}),
        ],
        contract_id="contract-demo",
    )

    assert result.agreed is False
    assert result.reason == "contract_mismatch"
    assert "backend" in result.mismatch_roles
