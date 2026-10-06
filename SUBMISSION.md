# Submission Checklist and Demo Script

## Before submitting

- [ ] Replace the synthetic dataset/KB with Dataeko-provided files if they are available, then rerun training/evaluation.
- [ ] Run `pytest` and confirm all tests pass.
- [ ] Run `python scripts/evaluate.py` and copy the final metrics into the README if desired.
- [ ] Push to a **public** GitHub repository with multiple meaningful commits.
- [ ] Deploy to Streamlit Community Cloud, or record a 5–10 minute local demo if hosting the preferred model is too heavy.
- [ ] Submit the GitHub repo link, live demo/recording link, and `REFLECTION.md`.

## Recommended commit history

1. `chore: scaffold triage app and synthetic fixtures`
2. `feat: add baseline ticket classifier and evaluation`
3. `feat: protect security fraud routing with safety gate`
4. `feat: add hybrid KB retrieval and abstention`
5. `feat: add grounded cited response generation`
6. `test: cover security routing retrieval and no-answer path`
7. `docs: add architecture evaluation and reflection`

Do not squash these into one final commit; the brief explicitly values evolution of the solution.

## 6–8 minute demo flow

**0:00–0:45 — Problem and design**  
Explain the asymmetric cost: Security/Fraud is <1%, so raw accuracy can be misleading. Show the architecture diagram.

**0:45–2:00 — Normal classification**  
Run a Billing or Technical sample. Show category, confidence, probabilities, and retrieved KB evidence.

**2:00–3:30 — Security/Fraud protection**  
Run: `I see an unknown login and a charge I did not make.` Show that it is escalated and human review is required. Mention the low review floor prevents silent General Inquiry routing.

**3:30–4:45 — Grounded RAG**  
Show a duplicate-charge ticket. Point out inline `[KB-xxx]` citations and the retrieved evidence panel.

**4:45–5:30 — No-answer behavior**  
Run: `Tell me the cafeteria lunch menu for next Tuesday.` Show that the app refuses to invent an answer.

**5:30–6:30 — Evaluation**  
Open `artifacts/metrics.json` and `artifacts/retrieval_metrics.json`. Focus on macro F1, protected-class safe handling, zero silent security→general misroutes, and retrieval Hit@3/MRR@3.

**6:30–7:30 — Limitations and next steps**  
Acknowledge synthetic data, tiny Security/Fraud sample, and lack of calibrated probabilities. Explain that better labels and a larger security challenge set are the first real-budget improvements.
