"""The evaluation question set for the sample document (NIST AI 100-1, AI RMF 1.0).

Pages are the PDF's page numbers (what a PDF viewer shows), not the numbers printed in the
footer: the document's printed "Page 1" is PDF page 6. ``must`` lists the facts a correct
answer contains; each is a tuple of acceptable phrasings, matched case-insensitively.
Unanswerable questions are about things the document does not cover, including two close
to its topic (a numeric threshold it never sets, incident counts it never gives); the
correct response is to abstain.

The set is split in halves, alternating within each kind. Abstention thresholds were tuned
on ``dev`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    id: str
    question: str
    kind: Literal["answerable", "unanswerable"]
    split: Literal["dev", "held_out"]
    pages: tuple[int, ...] = ()
    # Each entry is one required fact, given as alternative phrasings (any one counts).
    must: tuple[tuple[str, ...], ...] = ()


def _a(
    qid: str, question: str, pages: tuple[int, ...], *must: tuple[str, ...]
) -> tuple[str, str, tuple[int, ...], tuple[tuple[str, ...], ...]]:
    return qid, question, pages, must


_ANSWERABLE = [
    _a("core-functions", "What are the four functions of the AI RMF core?", (8, 25),
       ("govern",), ("map",), ("measure",), ("manage",)),
    _a("trustworthy", "Which characteristics make an AI system trustworthy?", (7, 8, 17),
       ("valid and reliable",), ("secure and resilient",), ("privacy",)),
    _a("risk-definition", "How does the framework define risk?", (9,),
       ("probability",), ("magnitude",)),
    _a("residual-risk", "What is residual risk?", (13,), ("remaining after risk treatment",)),
    _a("risk-tolerance", "Does the AI RMF prescribe a level of risk tolerance?", (12,),
       ("not prescribe risk tolerance",)),
    _a("unacceptable-risk",
       "What should happen when an AI system presents unacceptable negative risk levels?",
       (13,), ("cease",)),
    _a("reliability", "How is reliability defined?", (18,), ("without failure",)),
    _a("accuracy", "How does the framework define accuracy?", (19,),
       ("closeness of results",)),
    _a("robustness", "What is robustness or generalizability?", (19,),
       ("maintain its level of performance",)),
    _a("safe", "When is an AI system considered safe?", (19,), ("endangered",)),
    _a("resilience", "What is the difference between security and resilience?", (20,),
       ("return to normal function", "unexpected adverse event")),
    _a("transparency", "What does transparency reflect?", (20,),
       ("information about an ai system",)),
    _a("explain-vs-interpret",
       "What is the difference between explainability and interpretability?", (21,),
       ("mechanisms",), ("meaning",)),
    _a("why-question", "Which question can interpretability answer?", (22,), ("why",)),
    _a("bias-categories", "What are the three major categories of AI bias?", (23,),
       ("systemic",), ("computational",), ("human-cognitive", "human cognitive")),
    _a("privacy-values", "Which privacy values should guide AI system design?", (22,),
       ("anonymity",), ("confidentiality",)),
    _a("ai-actors", "Who are AI actors?", (7,), ("active role",)),
    _a("voluntary", "Is use of the AI RMF mandatory?", (7, 47), ("voluntary",)),
    _a("law", "Which law directed NIST to develop the AI RMF?", (7, 8),
       ("initiative act of 2020",)),
    _a("govern", "What does the GOVERN function do?", (26, 27),
       ("culture of risk management", "cross-cutting")),
    _a("map", "What does the MAP function establish?", (29, 30), ("context",)),
    _a("measure", "What kinds of tools does the MEASURE function employ?", (33,),
       ("quantitative",)),
    _a("manage", "What does the MANAGE function entail?", (36,),
       ("allocating risk resources",)),
    _a("go-no-go", "Which decision should the MAP function inform?", (30,), ("go/no-go",)),
    _a("use-case-profile", "What is an AI RMF use-case profile?", (38,),
       ("specific setting or application",)),
    _a("review-2028",
       "When will NIST review the framework with formal input from the AI community?", (3,),
       ("2028",)),
    _a("versioning", "What versioning system does the framework use?", (3,), ("two-number",)),
    _a("governance-actors", "Who is responsible for AI governance in an organization?", (42,),
       ("senior leadership",), ("board of directors",)),
    _a("govern-1-1", "What does GOVERN 1.1 require?", (27,),
       ("legal and regulatory requirements",)),
    _a("law-agnostic", "Should the AI RMF be specific to particular laws or regulations?",
       (47,), ("agnostic",)),
]  # fmt: skip

_UNANSWERABLE = [
    ("crypto", "What does the framework say about cryptocurrency mining?"),
    ("fpr-threshold", "What is the maximum acceptable false positive rate for an AI system?"),
    ("world-cup", "Who won the 2022 FIFA World Cup?"),
    ("incidents-2022", "How many AI incidents were reported to NIST in 2022?"),
    ("gpu", "Which GPU should I buy to train large language models?"),
    ("language", "Which programming language does NIST recommend for building AI systems?"),
    ("capital", "What is the capital of Pakistan?"),
    ("headcount", "How many employees does NIST have?"),
    ("recipe", "How do I bake a chocolate cake?"),
    ("stock", "What was the share price of a major chip maker at the end of 2023?"),
]


def _build() -> tuple[EvalQuestion, ...]:
    out: list[EvalQuestion] = []
    for i, (qid, question, pages, must) in enumerate(_ANSWERABLE):
        split: Literal["dev", "held_out"] = "dev" if i % 2 == 0 else "held_out"
        out.append(EvalQuestion(qid, question, "answerable", split, pages, must))
    for i, (qid, question) in enumerate(_UNANSWERABLE):
        split = "dev" if i % 2 == 0 else "held_out"
        out.append(EvalQuestion(qid, question, "unanswerable", split))
    return tuple(out)


QUESTIONS: tuple[EvalQuestion, ...] = _build()
