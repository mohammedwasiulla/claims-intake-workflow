"""Write the JSON Schema of the output to schema/output_schema.json."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from claims_intake.schema import ProcessedNote
out = pathlib.Path(__file__).resolve().parents[1] / "schema" / "output_schema.json"
out.write_text(json.dumps(ProcessedNote.model_json_schema(), indent=2), encoding="utf-8")
print("wrote", out)
