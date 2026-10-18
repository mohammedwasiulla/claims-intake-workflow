"""All tunable rules and vocabularies live here so ops/analysts can review them in one place."""
from __future__ import annotations

# --------------------------------------------------------------------------- categories
CATEGORIES = [
    "Motor Accident",
    "Property Water Damage",
    "Property Fire/Smoke",
    "Health Reimbursement",
    "Travel Delay/Baggage",
    "Device/Personal Item Damage",
    "Commercial Equipment",
    "Third-Party Contact",
]
UNCLEAR_CATEGORY = "Unclear / Unclassified"

# category -> list of (regex, weight). Weights: 3-4 = strong incident wording, 1-2 = weak hint.
CATEGORY_RULES: dict[str, list[tuple[str, int]]] = {
    "Motor Accident": [
        (r"\b(?:parked\s+car|car|vehicle|two[- ]wheeler|bike|scooter|motorcycle)\b", 3),
        (r"\b(?:bumper|side\s+panel|front\s+grill|left\s+door|right\s+door|skid|collision|traffic\s+signal|dent|scratch)\b", 2),
        (r"\b(?:driver\s+statement|garage|police\s+intimation)\b", 1),
    ],
    "Property Water Damage": [
        (r"\b(?:leak(?:age)?|seepage|pipe\s+burst|rainwater|water\s+stains?|wall\s+bubbling|flooring|ceiling)\b", 3),
        (r"\b(?:building\s+maintenance|inspection\s+request|cause\s+of\s+leak|kitchen\s+cabinets?|balcony)\b", 1),
    ],
    "Property Fire/Smoke": [
        (r"\b(?:fire|smoke|short\s+circuit|spark|burnt)\b", 3),
        (r"\b(?:fire\s+service|appliance\s+invoice|electrical\s+panel)\b", 1),
    ],
    "Health Reimbursement": [
        (r"\b(?:hospital|outpatient|treatment|admission|emergency\s+visit|discharge|reimbursement|diagnos\w+)\b", 3),
        (r"\b(?:prescription|bill\s+breakup|payment\s+receipt|claim\s+form|diagnostic\s+report)\b", 1),
    ],
    "Travel Delay/Baggage": [
        (r"\b(?:baggage|luggage|suitcase|flight|airline|airport|onward\s+connection|international\s+trip|travel\s+delay|(?:checked\s+)?bag\s+(?:was\s+)?(?:lost|delayed|delivered))\b", 3),
        (r"\b(?:boarding\s+pass|delay\s+confirmation|baggage\s+(?:tag|report)|hotel\s+stay)\b", 1),
    ],
    "Device/Personal Item Damage": [
        (r"\b(?:laptop|tablet|smart\s?watch|mobile\s+phone|smartphone|handset|camera|earbuds?)\b", 5),
        (r"\bphone\b(?!\s*(?:number|call|line|no\b))", 4),
        (r"\b(?:screen\s+cracked|display\s+flickering|liquid\s+spill|service\s+cent(?:er|re)\s+note|serial\s+number)\b", 2),
    ],
    "Commercial Equipment": [
        (r"\b(?:warehouse\s+scanner|scanner|office\s+printer|printer|display\s+unit|ups\b|store\s+setup|forklift|pos\s+terminal|equipment)\b", 5),
        (r"\b(?:site\s+supervisor|asset\s+tag|equipment\s+invoice|warehouse|office|store)\b", 1),
    ],
    "Third-Party Contact": [
        (r"\b(?:neighbou?r|third\s+party|other\s+party)\s+(?:reported|called|complained|contacted)\b", 4),
        (r"\blinked\s+to\s+(?:the\s+)?claimant\b", 2),
    ],
}
# A top score must reach this to count as a category at all; it must beat the runner-up by the margin,
# otherwise the category is flagged ambiguous.
CATEGORY_MIN_SCORE = 3
CATEGORY_TIE_MARGIN = 2

CATEGORY_TO_QUEUE = {
    "Motor Accident": "Motor Claims Intake",
    "Property Water Damage": "Property Claims Intake",
    "Property Fire/Smoke": "Property Claims Intake",
    "Health Reimbursement": "Health Reimbursement Review",
    "Travel Delay/Baggage": "Travel Claims Intake",
    "Device/Personal Item Damage": "Asset and Device Claims",
    "Commercial Equipment": "Commercial Equipment Review",
    "Third-Party Contact": "Manual Clarification Queue",
}
MANUAL_QUEUE = "Manual Clarification Queue"

# --------------------------------------------------------------------------- documents / info items
# surface regex -> canonical group (used only for duplicate / conflict detection). Longest-first matching.
DOC_TERMS: dict[str, str] = {
    r"damage\s+photos?": "photos", r"vehicle\s+photos?": "photos", r"item\s+photos?": "photos",
    r"photos?": "photos",
    r"repair\s+estimate": "estimate", r"garage\s+estimate": "estimate", r"repair\s+quot(?:e|ation)": "estimate",
    r"quotation": "estimate", r"estimate": "estimate",
    r"purchase\s+invoice": "purchase invoice", r"travel\s+invoice": "travel invoice",
    r"garage\s+invoice": "garage invoice", r"appliance\s+invoice": "appliance invoice",
    r"equipment\s+invoice": "equipment invoice", r"invoice": "invoice",
    r"driver\s+statement": "driver statement", r"incident\s+statement": "incident statement",
    r"police\s+intimation": "police intimation", r"fire\s+service\s+note": "fire service note",
    r"building\s+maintenance\s+note": "building maintenance note", r"inspection\s+request": "inspection request",
    r"service\s+cent(?:er|re)\s+note": "service center note", r"site\s+supervisor\s+note": "site supervisor note",
    r"baggage\s+report": "baggage report", r"boarding\s+pass": "boarding pass", r"airline\s+letter": "airline letter",
    r"airline\s+confirmation": "airline confirmation", r"delay\s+confirmation": "delay confirmation",
    r"hospital\s+bill": "hospital bill", r"bill\s+breakup": "bill breakup", r"payment\s+receipt": "payment receipt",
    r"expense\s+receipts?": "expense receipts", r"receipts?": "payment receipt",
    r"discharge\s+(?:summary|paper)": "discharge summary", r"prescription": "prescription",
    r"diagnostic\s+report": "diagnostic report", r"claim\s+form": "claim form",
    r"diagnosis\s+(?:note|section)": "diagnosis note",
}
# information items (not documents) that notes commonly flag as unclear/missing
INFO_TERMS: dict[str, str] = {
    r"baggage\s+tag": "baggage tag", r"asset\s+tag": "asset tag", r"serial\s+number": "serial number",
    r"third[- ]party\s+(?:details|info(?:rmation)?)": "third-party details", r"property\s+address": "property address",
    r"incident\s+time": "incident time", r"travel\s+dates": "travel dates", r"cause\s+of\s+leak": "cause of leak",
    r"incident\s+sequence": "incident sequence",
}
# cue -> normalised wording used in flags
AVAILABILITY_CUES: dict[str, str] = {
    r"not\s+attached": "not attached",
    r"not\s+available": "not available",
    r"not\s+provided": "not provided",
    r"not\s+visible(?:\s+in\s+[\w\s]+?folder)?": "not visible/accessible",
    r"not\s+received": "not received",
    r"not\s+ready": "not ready",
    r"not\s+found": "not found",
    r"missing": "missing",
    r"pending": "pending",
    r"to\s+be\s+sent(?:\s+\w+)?": "pending (to be sent later)",
}
QUALITY_CUES: dict[str, str] = {
    r"unclear": "unclear",
    r"incomplete": "incomplete",
    r"too\s+short": "too short",
    r"difficult\s+to\s+read": "difficult to read",
    r"unreadable": "unreadable",
    r"illegible": "illegible",
    r"blurry": "blurry",
}
# information items for which any gap cue is a "closer check" signal (mirrors the queue mapping guidance)
HARD_INFO_ITEMS = {"incident sequence"}

# --------------------------------------------------------------------------- places (fallback gazetteer only)
KNOWN_CITIES = [
    "Delhi NCR", "Mumbai", "Pune", "Hyderabad", "Kolkata", "Chennai", "Ahmedabad", "Bengaluru", "Bangalore",
    "Delhi", "Gurgaon", "Gurugram", "Noida", "Jaipur", "Kochi", "Lucknow", "Surat", "Nagpur", "Indore",
]

# --------------------------------------------------------------------------- scoring / thresholds
CORE_FIELDS = ["policy_reference", "claimant_reference", "incident_date", "location"]
MANUAL_IF_CORE_ISSUES_AT_LEAST = 3
VERY_SHORT_NOTE_CHARS = 60
CONFIDENCE_HIGH = 80
CONFIDENCE_MEDIUM = 55

# Words the generated text must never contain (the workflow does not decide claims).
BANNED_DECISION_TERMS = [
    "approve", "approved", "reject", "rejected", "deny", "denied", "payable", "will be paid",
    "liable", "liability is", "at fault", "not covered", "is covered", "eligible", "ineligible", "fraud", "settle",
]
