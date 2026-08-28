from pathlib import Path

from thoughtlab.reasoningEngineering import modernization_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dossier_is_compact_substantial_and_provenance_rich() -> None:
    documents = protocol.load_dossier(REPO_ROOT)

    assert len(documents) == 11
    assert [row["position"] for row in documents] == list(range(1, 12))
    assert all(row["chars"] >= 2250 for row in documents)
    assembled = protocol.assemble_task_text(documents)
    for phrase in (
        "**Author:**",
        "**From:**",
        "**Compiled by:**",
        "**Source:**",
    ):
        assert phrase in assembled
    assert "North River Benefits Network" in assembled
    assert "Tern Systems" in assembled
    assert "North River Treasury" in assembled


def test_model_facing_dossier_has_no_author_solution_menu_or_withheld_notes() -> None:
    task = protocol.assemble_task_text(protocol.load_dossier(REPO_ROOT))
    withheld = (REPO_ROOT / protocol.WITHHELD_CONSTRUCTION_NOTES).read_text(
        encoding="utf-8"
    )

    assert "Central stabilization followed by accelerated convergence" in withheld
    assert "Candidate localized interventions" in withheld
    assert "Central stabilization followed by accelerated convergence" not in task
    assert "Federated interface-first recovery" not in task
    assert "Pilot rollback and legacy re-baseline" not in task
    assert protocol.WITHHELD_CONSTRUCTION_NOTES not in task
    assert "the preferred architecture is" not in task.lower()


def test_dossier_preserves_realistic_provenance_instead_of_opaque_bookkeeping() -> None:
    task = protocol.assemble_task_text(protocol.load_dossier(REPO_ROOT))

    assert "ID_" not in task
    assert "Halden & Rowe Assurance" in task
    assert "County Services Cooperative" in task
    assert "Contractual context" in task
    assert "Boundary limitation" in task
    assert "Scope:" in task


def test_no_document_is_written_as_an_omniscient_answer_key() -> None:
    task = protocol.assemble_task_text(protocol.load_dossier(REPO_ROOT))

    assert "no evidence sufficient to assign" in task
    assert "does not certify replacement readiness" in task
    assert "does not recommend that the gateway become" in task
    assert "cannot assign one readiness date" in task
    assert "the preferred architecture is" not in task.lower()
