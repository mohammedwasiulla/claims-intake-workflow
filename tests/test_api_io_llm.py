import io, json, pathlib
from fastapi.testclient import TestClient
from claims_intake.api import app
from claims_intake.io_utils import load_notes, write_csv, write_json, parse_txt_export
from claims_intake.pipeline import process_inputs
from claims_intake.llm_assist import grounded, refine
from claims_intake.schema import CSV_COLUMNS

ROOT = pathlib.Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"

def test_api_single():
    r = client.post("/process", json={"claim_note_id": "A1", "intake_note_text": "Car bumper damaged in Pune on 10-Jun-2026. Policy POL-6001, claimant CLMNT-7001.", "received_date": "2026-06-14"})
    assert r.status_code == 200 and r.json()["assessment"]["detected_claim_category"] == "Motor Accident"

def test_api_rejects_empty_note():
    assert client.post("/process", json={"intake_note_text": ""}).status_code == 422

def test_api_file_csv_in_csv_out():
    data = (ROOT / "data" / "claim_intake_notes.csv").read_bytes()
    r = client.post("/process/file?format=csv", files={"file": ("n.csv", data, "text/csv")})
    assert r.status_code == 200 and r.text.count("CI-2026-") >= 85

def test_api_bad_extension():
    assert client.post("/process/file", files={"file": ("n.pdf", b"x", "application/pdf")}).status_code == 415

def test_loaders_agree_on_ids():
    a = [n.claim_note_id for n in load_notes(ROOT / "data" / "claim_intake_notes.csv")]
    b = [n.claim_note_id for n in load_notes(ROOT / "data" / "claim_intake_notes.jsonl")]
    c = [n.claim_note_id for n in load_notes(ROOT / "data" / "raw_note_exports")]
    assert a == b == c and len(a) == 85

def test_txt_export_parse():
    n = parse_txt_export(ROOT / "data" / "raw_note_exports" / "CI-2026-0084.txt")
    assert n.claim_note_id == "CI-2026-0084" and n.source_channel == "Partner Portal" and n.received_date == "2026-05-25"

def test_raw_exports_match_csv_results():
    csv_r = {r.claim_note_id: r for r in process_inputs(load_notes(ROOT / "data" / "claim_intake_notes.csv"))}
    txt_r = {r.claim_note_id: r for r in process_inputs(load_notes(ROOT / "data" / "raw_note_exports"))}
    for k in csv_r:
        assert csv_r[k].assessment.model_dump() == txt_r[k].assessment.model_dump()

def test_outputs_written(tmp_path):
    res = process_inputs(load_notes(ROOT / "data" / "claim_intake_notes.csv")[:5])
    j, c = write_json(res, tmp_path / "o.json"), write_csv(res, tmp_path / "o.csv")
    assert len(json.loads(j.read_text())) == 5
    assert c.read_text(encoding="utf-8-sig").splitlines()[0].split(",") == CSV_COLUMNS

# ---- optional LLM step (tested with a fake client; no network)
class _Fake:
    def __init__(self, summary): self.summary = summary; self.calls = 0
    class _C:
        def __init__(s, outer): s.outer = outer
        def create(s, **kw):
            s.outer.calls += 1
            class M: content = json.dumps({"summary": s.outer.summary})
            class Ch: message = M
            class R: choices = [Ch]
            return R
    @property
    def chat(self):
        o = self
        class X: completions = _Fake._C(o)
        return X

def test_grounding_check():
    note = "Car bumper damaged in Pune. Policy POL-6001."
    assert grounded("Bumper damage reported in Pune.", note)[0]
    assert not grounded("Claim should be approved.", note)[0]
    assert not grounded("Damage of 50000 reported.", note)[0]
    assert not grounded("Policy POL-9999 mentioned.", note)[0]

def test_llm_respects_cap_and_validation():
    items = load_notes(ROOT / "data" / "claim_intake_notes.csv")
    res = process_inputs(items)
    raw = {n.claim_note_id: n.intake_note_text for n in items}
    facts_before = [r.extracted_facts.model_dump() for r in res]
    fake = _Fake("Claim should be approved for sure.")
    stats = refine(res, raw, fake, max_calls=2)
    assert fake.calls <= 2 and stats["accepted"] == 0 and stats["rejected"] == fake.calls
    assert facts_before == [r.extracted_facts.model_dump() for r in res]       # facts never touched

def test_ui_page_served():
    r = client.get("/")
    assert r.status_code == 200 and "Claims intake" in r.text and "/process/file" in r.text

def test_export_csv_roundtrip():
    one = client.post("/process", json={"claim_note_id": "U1", "intake_note_text": "Car bumper damaged in Pune. Policy POL-1234."}).json()
    r = client.post("/export/csv", json=[one])
    assert r.status_code == 200 and "U1" in r.text and r.text.startswith("claim_note_id")
