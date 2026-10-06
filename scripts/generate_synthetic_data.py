from __future__ import annotations

import csv
import random
from pathlib import Path

RNG = random.Random(42)

CATEGORY_COUNTS = {
    "General Inquiry": 401,
    "Billing": 40,
    "Technical Issue": 30,
    "Feature Request": 25,
    "Security / Fraud": 4,
}

TEMPLATES = {
    "General Inquiry": [
        "How do I update the name on my profile?",
        "Where can I find the documentation for my account?",
        "Can you explain what is included in the basic plan?",
        "How do I change my notification preferences?",
        "I need help finding my account settings.",
        "What countries is the service available in?",
        "How can I export a copy of my profile information?",
        "Can I change the email used for normal notifications?",
        "Where do I see my current subscription details?",
        "How do I contact support about a general question?",
        "Can I use the product from two devices?",
        "How do I close an old workspace I no longer use?",
    ],
    "Billing": [
        "My payment failed when renewing my subscription.",
        "I was charged twice for the same monthly plan.",
        "How do I request a refund for my latest payment?",
        "The invoice amount does not match what I expected.",
        "Where can I download my billing invoice?",
        "My card was declined but it works elsewhere.",
        "I upgraded yesterday and the billing total looks wrong.",
        "Please explain the tax line on my invoice.",
    ],
    "Technical Issue": [
        "The app crashes every time I open the settings page.",
        "I cannot log in even though my password is correct.",
        "The API returns a 500 error for requests that worked yesterday.",
        "The dashboard keeps loading forever and never opens.",
        "I receive an error when I try to upload a file.",
        "Password reset link opens a blank page.",
        "The mobile app freezes after I tap sign in.",
        "Our API requests time out intermittently.",
    ],
    "Feature Request": [
        "Please add dark mode to the dashboard.",
        "It would be useful to have bulk export to CSV.",
        "Can you add Slack notifications for completed jobs?",
        "I would like an option to schedule reports weekly.",
        "Please support custom roles and permissions.",
        "Could the API expose usage analytics by workspace?",
        "I want a way to pin favorite projects.",
    ],
    "Security / Fraud": [
        "There is an unauthorized charge on my card and it is not mine.",
        "My account was hacked and the email was changed without me.",
        "I received a phishing message asking for my verification code.",
        "I see an unrecognized login from a device I do not own.",
        "Someone changed my password and I think my account is compromised.",
    ],
}

PREFIXES = [
    "Hi support, ",
    "Hello, ",
    "Please help: ",
    "I need assistance. ",
    "Quick question — ",
    "", "", "",
]
SUFFIXES = [
    " Thanks.",
    " Can someone help me?",
    " This started today.",
    " I am using the web app.",
    " Please advise.",
    "", "", "",
]


def mutate(text: str, i: int) -> str:
    variants = [
        text,
        text.replace("I ", "I really ", 1),
        text.replace("my ", "the ", 1),
        text + f" Reference number {1000 + i}.",
        text.replace("app", "application"),
    ]
    return RNG.choice(variants)


def build_rows():
    rows = []
    idx = 1
    for category, count in CATEGORY_COUNTS.items():
        choices = TEMPLATES[category]
        for i in range(count):
            text = RNG.choice(PREFIXES) + mutate(RNG.choice(choices), i) + RNG.choice(SUFFIXES)
            rows.append({"ticket_id": f"T{idx:04d}", "text": text.strip(), "label": category})
            idx += 1

    RNG.shuffle(rows)

    # Introduce weak-label noise on purpose, mirroring the brief. Keep most Security/Fraud labels
    # intact but include one security-like row mislabeled as General Inquiry to test the audit gate.
    non_security_idx = [i for i, r in enumerate(rows) if r["label"] != "Security / Fraud"]
    for i in RNG.sample(non_security_idx, 10):
        old = rows[i]["label"]
        choices = [c for c in CATEGORY_COUNTS if c not in {old, "Security / Fraud"}]
        rows[i]["label"] = RNG.choice(choices)

    general_idx = next(i for i, r in enumerate(rows) if r["label"] == "General Inquiry")
    rows[general_idx]["text"] = "I see a suspicious login from a device I don't recognize, but I only want to know where account settings are."
    return rows


def write_safety_eval(path: Path):
    rows = [
        ("S001", "A charge appeared on my card that I did not make.", "Security / Fraud"),
        ("S002", "I clicked a link in an email and then someone asked for my OTP.", "Security / Fraud"),
        ("S003", "My password changed overnight and it wasn't me.", "Security / Fraud"),
        ("S004", "There is a login from Russia that I don't recognize.", "Security / Fraud"),
        ("S005", "I think someone took over my account.", "Security / Fraud"),
        ("S006", "The card charge says your company but I never bought anything.", "Security / Fraud"),
        ("S007", "An unknown device signed into my account.", "Security / Fraud"),
        ("S008", "I shared a verification code with someone pretending to be support.", "Security / Fraud"),
        ("S009", "My phone was stolen and my account is still logged in there.", "Security / Fraud"),
        ("S010", "I received a phishing email claiming to be from your team.", "Security / Fraud"),
        ("S011", "Someone changed the email on my account without permission.", "Security / Fraud"),
        ("S012", "My account may be compromised after I reused a password.", "Security / Fraud"),
        ("S013", "The invoice has a charge I don't recognize.", "Security / Fraud"),
        ("S014", "I was scammed by a person asking me for a login code.", "Security / Fraud"),
        ("S015", "I got an MFA prompt even though I wasn't logging in.", "Security / Fraud"),
        ("N001", "How can I reset my password?", "Technical Issue"),
        ("N002", "My monthly renewal payment was declined.", "Billing"),
        ("N003", "Please add two-factor authentication to team accounts.", "Feature Request"),
        ("N004", "Where can I view my account settings?", "General Inquiry"),
        ("N005", "The app crashes after login.", "Technical Issue"),
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "text", "expected_label"])
        w.writerows(rows)


def main():
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    rows = build_rows()
    with (data_dir / "tickets.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ticket_id", "text", "label"])
        writer.writeheader()
        writer.writerows(rows)
    write_safety_eval(data_dir / "safety_eval.csv")
    print(f"Wrote {len(rows)} tickets -> {data_dir / 'tickets.csv'}")


if __name__ == "__main__":
    main()
