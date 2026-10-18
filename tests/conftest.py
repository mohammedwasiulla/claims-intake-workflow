import json, sys, pathlib
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claims_intake.io_utils import load_notes
from claims_intake.pipeline import process_inputs
from claims_intake.schema import NoteInput

@pytest.fixture(scope="session")
def dataset():
    return load_notes(ROOT / "data" / "claim_intake_notes.csv")

@pytest.fixture(scope="session")
def results(dataset):
    return {r.claim_note_id: r for r in process_inputs(dataset)}

@pytest.fixture(scope="session")
def raw(dataset):
    return {n.claim_note_id: n.intake_note_text for n in dataset}

@pytest.fixture(scope="session")
def custom():
    items = [NoteInput(**x) for x in json.load(open(ROOT / "tests" / "custom_notes.json"))]
    return {r.claim_note_id: r for r in process_inputs(items)}
