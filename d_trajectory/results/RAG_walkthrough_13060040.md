# How our examiner RAG works: one case from download to prediction

*D (Nancy), 2026-11-06, updated 2026-11-09. For the whole team. Every file name, text excerpt, number and score below is real, taken from
case **13060040** and from B's new package `B_shared_BGE_M3_dense_v1_2026_11_05`.*

The mentor asked us to be able to say, for every step: **what goes in, what comes out, where it lives, and why we do
it**. This document does that for one case.

---

## Part 1. Basic ideas first (read this even if you skip the rest)

### 1.1 What are we predicting?

We take one patent application and stop the clock on a fixed day, the **cutoff**. For us the cutoff is the day the
applicant filed the first reply to the examiner's first rejection. Then we ask what happens next:

| Task | Question | Answer for 13060040 (hidden from every method) |
|---|---|---|
| Disposition | Will it be allowed or abandoned, and when? (probabilities for months 1–24) | Abandoned on day 766, so **still pending at month 24** |
| Remaining Rounds | How many more rejections before it ends? | **4** |
| Time to Next Action | How many days until the examiner's next letter? | **73** (a final rejection on 2014-12-08) |

Anything dated after the cutoff is the answer. **It must never be used as input.** This is the "cutoff rule".

### 1.2 What is a "prompt"?

A prompt is **one long text message** sent to the LLM (GPT-5-mini). The LLM reads it and writes an answer back. That's
all. The LLM cannot open folders or search anything. It only sees what we paste into the message.

### 1.3 What is RAG?

RAG = **Retrieval-Augmented Generation**. In plain words:

> **Before** we ask the LLM, a separate program searches a library and picks the few documents most relevant to the
> question. We **paste those documents into the prompt**. Then the LLM answers, using them as extra reading.

Think of an open-book exam where a librarian hands you the 3 most relevant books first. The librarian is a normal
program (no LLM). The student is the LLM.

So RAG always has **two separate parts**:
1. **Retrieval (search):** a Python program, **no LLM**. Input: a question text and a library. Output: a short list of
   the most similar items.
2. **Generation (answer):** the LLM call. The items found in part 1 are pasted into the prompt.

For us:
- **The library** = the examiner's own past applications.
- **The question** = "what is this new case about?"
- **The idea:** an examiner may treat similar inventions in a similar way, so how their similar past cases went may
  hint at how this one will go. This is what "personalization" means here.

### 1.4 What is an "embedding" and a "similarity score"?

- An **embedding model** turns a piece of text into a fixed list of numbers. We use **BGE-M3**, which gives 1,024
  numbers per text. Texts about similar things get similar lists. The model only does this; it does not answer
  questions.
- The **similarity score** (cosine) compares two lists and gives one number. Higher means the two texts are about more
  similar things. Between our patents it lands roughly between 0.5 and 0.8.
- **TF-IDF** is an older method that compares which words two texts share. We used it before. The mentor said to
  replace it with embeddings, and B has now done that.

### 1.5 Words we use

| Word | Meaning |
|---|---|
| **Query** | The text that describes **the case we predict**. Used **only inside the search program**, to search with. It is **not** the prompt |
| **Library / candidates** | The examiner's past applications that the search program looks through |
| **Top-3** | The 3 past applications with the highest similarity scores |
| **Abstract** | The one-paragraph summary of an invention, as published |
| **Claims** | The numbered sentences that define exactly what is protected |
| **Prosecution letters** | The back-and-forth between examiner and applicant: rejection letters (codes CTNF = non-final, CTFR = final), the applicant's replies (REM = remarks, CLM = amended claims) |
| **Event list** (`transactions.csv`) | The USPTO's log of every event in an application, one line per event with a date and a code |
| **Patent family** | Applications that are versions of the same invention. We never use two from one family, and never the case's own family |
| **Pending / censored** | The application had not ended yet on the date we look. Its outcome is unknown, not "no" |

---

## Part 2. The whole pipeline in one picture

```
             THE CASE WE PREDICT                         THE EXAMINER'S PAST APPLICATIONS (library)
             data_v1_share/apps/13060040/                profile_corpus/apps/<app_id>/   (30 applications)
                     │                                            │
                     │ Step 2: take its abstract + claims         │ Step 3: take each one's abstract + claims
                     ▼                                            ▼
               QUERY TEXT ─────────── Step 4: SEARCH PROGRAM (B, Python, BGE-M3, no LLM) ──────────┘
                                              │ output: table ranking_top3_links_before_review.csv
                                              │ "for 13060040 the top-3 are 11528154, 12110183, 12343838"
                                              ▼
                              Step 5: LOOKUP PROGRAM (D, Python, no LLM)
                              reads the 3 event lists → what happened to each
                                              │
                      ┌───────────────────────┴────────────────────────┐
                      ▼                                                ▼
     Step 6a: NO-LLM PREDICTION (D)                  Step 6b: BUILD THE PROMPT and call GPT (D / B)
     simple math on the 3 outcomes                   case's own documents + one examiner block
     ("top-3 average")                                             │
                      │                                            ▼
                      └──────────────► Step 7: SCORE against the hidden answer (D) ◄──┘
```

Steps 2–6a involve **no LLM at all**. The LLM appears only in step 6b.

---

## Part 3. Step by step, with case 13060040

### Step 1. Download the case (A, done)

**Purpose:** get everything the USPTO has about this application, as text a computer can read.

**What exists at the USPTO:** a list of **191 documents** (`catalog.csv`). At the USPTO each one is a **PDF**:
- fee worksheets, transmittal letters, forms;
- the abstract and claims;
- the examiner's rejection letters;
- the applicant's replies.

**What A downloaded** into `data_v1_share/apps/13060040/`:

| File | What it is | Example (real) |
|---|---|---|
| `transactions.csv` | The event log, a table | `2014-03-19,MCTNF,Mail Non-Final Rejection` / `2014-09-26,A...,Response after Non-Final Action` / `2016-10-31,MABN2,Mail Abandonment` |
| `text/pgpub_abstract.txt` | Abstract, from the **published application** (2011-09-22) | *"Described here are devices, systems, and kits for delivering substances to tissues. The devices generally include one or more chambers and a reservoir within each chamber. The reservoir may locally deliver a microdose amount of a substance to a target tissue…"* |
| `text/pgpub_claims.json` | Claims from the published application, one entry per claim | Claim 343: *"A microarray comprising: An array of reservoirs and means for administering a therapeutic or diagnostic agent in tissue…"* |
| `text/2014-03-19_CTNF_....txt` | The examiner's first rejection letter | *"DETAILED ACTION … Claims 343-372 are pending for examination … interpreted under 35 U.S.C. 112(f)…"* |
| `text/2014-09-26_REM_....txt` | The applicant's reply (remarks) | *"Remarks. The Interview. The undersigned and applicants greatly appreciate the telephone interview on May 7, 2014… Claims 357-366 and 372 were rejected under 35 U.S.C. § 112…"* |
| `text/2014-09-26_CLM_....txt` | The applicant's amended claims, filed with the reply | the claims list with changes |
| `text/grant_*.txt` | The 2018 patent | **after the cutoff: never used** |

**Text or PDF?** A did **not** download the 191 PDFs. For the ~20 documents that matter, the USPTO also publishes a
**text (XML) version** with the same words; A downloaded those. Three small scanned pages had no text version and were
read from the image (OCR). The ~170 others (fees, forms, transmittals) say nothing about the case and were skipped.

> **"Should we feed the raw PDF?"** The PDF and its text version contain the same words, and an LLM reads text anyway:
> a PDF is converted to text first. So feeding the document **text** is feeding the raw document. The mentor's real
> point was: **give the model the actual content of the past cases, not a summary we made.** Feeding whole files is
> not practical either: 3 past applications are hundreds of pages, and much of it is forms and boilerplate. The
> mentor's own criticism of C's task was exactly that boilerplate gets in.

### Step 2. The query: describe the case we predict (B; new version is right)

**Purpose:** one piece of text that says *what this case is about*, so the search program can look for similar past
applications.

**Where it lives:** a text variable **inside B's search program**. It is **not** sent to the LLM.

**Input → output:** the case's own files → one text.

| | What text was used as the query |
|---|---|
| **Old (B, TF-IDF; what our 11-03 and 11-05 runs used)** | The case's **prosecution letters**: the 2014 rejection letter + the replies + the amended claims. So the search found past applications whose **letters looked alike** (same rejection wording), even if the inventions were different |
| **New (B, BGE-M3, 11-05)** = **what the mentor asked** | The case's **abstract + claims** that existed before the cutoff (from the 2011-09-22 publication). Exactly this (B's `queries.jsonl`, 6,796 characters): *"Abstract: Described here are devices, systems, and kits for delivering substances to tissues … Claims: … 343. A microarray comprising: An array of reservoirs and means for administering a therapeutic or diagnostic agent … 372. A method for extracting tissue or cells…"* The title is not used, because no dated title was available |

In words: **the query is now "what the invention is", not "what the letters say".** That is the mentor's point 6,
and it is fixed.

### Step 3. The library: the examiner's past applications (A, done)

**Purpose:** the collection we search in. It must be this examiner's own work, so that what we find tells us about
this examiner.

**Where it lives:** a folder plus a table on disk, `profile_corpus/` from A. **Not** in the prompt.

**The table** `profile_index.csv` has one row per past application. This case's examiner (`ex_7657097da7`) has **30**.
One real row:
```
examiner_id    app_id    filing_date  cpc            title                                       pgpub_date
ex_7657097da7  12880303  2010-09-13   G06T11/26;...  Determination Of A Physiological Parameter  2011-03-24
```

**The folder** `profile_corpus/apps/12880303/` holds the same kinds of files as Step 1: `transactions.csv`,
`text/pgpub_abstract.txt`, `text/pgpub_claims.json` and the letters. Only things dated before our case's cutoff are
included, and no application shares a family with any of our 1,000 cases.

**What this examiner works on.** Some of the 30 titles: *Multi-wavelength physiological monitor*, *Pulse oximeter
probe-off detector*, *Noninvasive apparatus for measuring blood sugar*, *Tissue hydration estimation*… **All 30 are
optical body sensors. None is a drug-delivery device like our case.** Keep this in mind for Step 4.

**For each past application, B builds its text** the same way as the query: its abstract + claims, dated no later
than its first usable reply. B also fixes **one moment** in each past application: its earliest usable "reply →
examiner's next letter". This is chosen without looking at how the application ended. 19 of the 30 have such a
moment before the cutoff, so 19 can be searched.

### Step 4. The search: pick the 3 most similar (B, Python, no LLM)

**Purpose:** from the 19 searchable past applications, find the 3 whose inventions are most like our case.

**Where it happens:** B's Python program. It runs **once, before any LLM call**.

**Input:** the query text (Step 2) and the 19 past-application texts (Step 3).

**What it does:**
1. BGE-M3 turns each text into 1,024 numbers. A long text is cut into pieces that the model can read (up to 8,190
   tokens each), each piece is turned into numbers, and the pieces are averaged. Nothing is thrown away.
2. It computes the similarity score of each past application with the query.
3. It sorts by score, keeps at most one per patent family, and takes the top 3.

The core of it, in about 5 lines:
```python
model  = SentenceTransformer("BAAI/bge-m3")                         # fixed version 5617a9f6…
q      = model.encode(query_text, normalize_embeddings=True)        # our case → 1,024 numbers
P      = model.encode(past_texts,  normalize_embeddings=True)        # 19 past applications → 19 × 1,024
scores = P @ q                                                       # 19 similarity scores
top3   = pick_top(scores, k=3, one_per_family=True)
```

**Output:** a table on disk, `ranking_top3_links_before_review.csv` (B's package), B's top 3 for every case. (B also
hand-reviewed 10 cases into `historical_links.csv`; D uses the unreviewed list so all 100 cases follow one rule.) The
real rows for our case:

| rank | past application | title | score |
|---|---|---|---|
| 1 | 11528154 | Tissue hydration estimation by spectral absorption bandwidth measurement | 0.708 |
| 2 | 12110183 | Channeled tissue sample probe method and apparatus | 0.704 |
| 3 | 12343838 | System and method for estimating physiological parameters by deconvolving artifacts | 0.668 |

12109224 (*coupling a channeled sample probe to tissue*, 0.695) was skipped because it is the same family as rank 2.
The least similar of the 19 scored 0.552.

**Old vs new for this case:**

| | Searched on | Top-3 |
|---|---|---|
| Old (TF-IDF) | letters | 12109224, 12495545, 12345537 (scores 0.17, 0.15, 0.15 on TF-IDF's own scale) |
| New (BGE-M3) | abstract + claims | 11528154, 12110183, 12343838 |

None of the three is the same. The old and new scores use different scales and cannot be compared.

**What to notice: "most similar" here is not "similar".**
- All 19 past applications score between 0.55 and 0.71. They are all medical sensing devices, roughly as close to a
  drug-delivery device as each other.
- The **wrong examiner's** top-3 (another examiner of the same art unit) score 0.70, 0.70 and 0.69, as high as our own
  examiner's.
- So for this case the top-3 is only slightly better than any 3. Across all 100 cases, the best match has a median
  score of 0.75 and the worst a median of 0.58.

### Step 5. Look up what happened to those 3 (D, Python, no LLM)

**Purpose:** for each of the 3, find out how it went **after its first reply**, the same moment as our cutoff. That
is what the examiner's similar past cases can tell us about our three tasks.

**Where it happens:** D's Python program (`topk_math.py`, same rules as `history_math.py`). It reads `transactions.csv` of each of
the 3.

**Input,** for example the real event lines of 12343838 (only events before our cutoff):
```
2012-07-06  MCTNF  Mail Non-Final Rejection
2012-10-09  A...   Response after Non-Final Action        ← its first reply (start the clock)
2012-11-06  MCTFR  Mail Final Rejection                   ← next letter: 28 days later
2013-01-07  A.NE   Response after Final Action
2013-01-18  MN/=.  Mail Notice of Allowance               ← ended: allowed, 101 days after the first reply
```

**Output:** a small table:

| past application | first reply | days to next letter | rejections after | how it ended | days to end |
|---|---|---|---|---|---|
| 11528154 | 2011-07-13 | 64 | 1 | allowed | 183 |
| 12110183 | 2012-12-21 | 40 | 4 so far | **still pending** on our cutoff | ≥ 644 (unknown) |
| 12343838 | 2012-10-09 | 28 | 1 | allowed | 101 |

### Step 6a. Predict without an LLM: the "top-3 average" (D)

**Purpose:** the mentor's first baseline. If the examiner's similar past cases are informative, this simple math
should already do well. Any LLM then has to beat it.

**Where it happens:** the same Python program, as simple arithmetic.

| Task | Math | Prediction | Truth |
|---|---|---|---|
| Time to Next Action | middle value of 64, 40, 28 | **40 days** | 73 |
| Remaining Rounds | middle value of 1, 4, 1 | **1** | 4 |
| Disposition (month 24) | 2 of 3 allowed within 24 months; none abandoned; 1 unknown | **67% allowed, 0% abandoned** | still pending |

All the other baselines, on the same case:

| Method (no LLM) | Which past cases | Allowed by month 24 | Abandoned by month 24 |
|---|---|---|---|
| Everyone average (Kaplan–Meier) | all 478 training cases, all examiners | 64% | 15% |
| This examiner's statistics card ("full-history numbers") | all of this examiner's past applications (30) | 64% | 25% |
| Top-3, old search (letters) | 12109224, 12495545, 12345537 | 67% | 33% |
| **Top-3, new search (invention)** | 11528154, 12110183, 12343838 | **67%** | **0%** |

One case proves nothing: every method thought it would be over by month 24, and it wasn't. The comparison is made on
all 100 cases.

### Step 6b. Predict with the LLM: build the prompt (D for our tasks; B for B's tasks)

**Purpose:** see whether an LLM that reads the case **and** the examiner's similar past cases does better than the
simple math.

**Where it happens:** a Python program fills a fixed template and sends it to GPT. Our template
(`prompts/trajectory_forecast_profile.txt`), shortened:

```
### SYSTEM
You forecast how U.S. patent prosecution will continue. ... return calibrated probabilities as a json object only.

### USER
Estimate how the prosecution of this U.S. utility application will continue after the cutoff date 2014-09-26.
Inputs
- Filing date ... Art unit ...
- Prosecution state at the cutoff: {A's predicted state}
- Prosecution record through the cutoff, oldest first.
{history}      ← PART 1: THE CASE WE PREDICT. Its own documents, full text (the 2014 rejection letter, the replies,
                  the claims from Step 1). This part is the same with or without RAG.
- Examiner history reference ... built only from the examiner's other applications ...
{profile}      ← PART 2: THE EXAMINER. This is where the retrieved past applications go (the "RAG" part).
Task
For each month m = 1..24, the probability that by the end of month m the application is allowed / abandoned ...
Output
{"F_allowance": [24 numbers], "F_abandonment": [24 numbers], "rationale": "..."}
```

**What goes into `{profile}`:** three examiner blocks. Each is run with this case's own examiner and, as a control,
with a wrong examiner of the same art unit (same wording, so the model cannot tell). This week's run is called
**profile_with_embedding**.

**(a) card: statistics only, from the examiner's full history.**
```
Examiner history reference available before 2014-09-26

Historical statistics
Statistics for this examiner, other applications, events before 2014-09-26:
- 30 applications; 26 replies to a non-final rejection.
- Next letter after such a reply (25 seen, 1 still waiting): allowance 32%, final rejection 64%, ...
- Days from a reply to the next letter: median 33 (allowances 59, rejections 31).
- After the first reply (20 applications): 11 allowed, 4 abandoned, 5 still pending; ... within 24 months 65%; abandoned within 24 months 26%.
- Further rejections after the first reply: 0: 26%, 1: 43%, 2: 8%, 3+: 23%; RCE filed in 25%.
- Grounds in 54 rejections ...: 103 in 93%, 102 in 54%, 112 in 50%, 101 in 24%.

Reading convention: (how each number is defined) ...
```
Numbers from **all 30** of the examiner's past applications before the cutoff. It does not use the search and holds no
past-application examples. (The 11-03 version also carried 3 short "reply → next letter" excerpts picked by the old
TF-IDF search. They are dropped: the past applications are now picked by B's search and shown in full in (b) and (c),
and the 11-04 test showed the excerpts added nothing.)

**(b) paths: the 3 most similar past applications, dated events only.**
```
Past application 3: 12343838
- 2012-07-06 examiner mailed a non-final rejection
- 2012-10-09 applicant filed a reply to a non-final rejection
- 2012-11-06 examiner mailed a final rejection
- 2013-01-07 applicant filed a reply to a final rejection
- 2013-01-18 examiner mailed a notice of allowance
Status on 2014-09-26: allowed (notice of allowance mailed 2013-01-18).
```
The same 3 applications as Step 4 (11528154, 12110183, 12343838). No statistics.

**(c) fulldoc: the same 3 past applications in full (the standard RAG).**
```
=== Past application 3: 12343838 ===
Documents:
[FP4AB5CEPPOPPY4 | CLM | 2008-12-24 | applicant | uspto_xml]        (the claims as filed, full text)
[pgpub_abstract | ABST | 2009-07-23 | pre_grant_publication | pgpub_xml]
There is disclosed a system and methods to estimate physiological parameters ...
[pgpub_claims | CLM | 2009-07-23 | pre_grant_publication | pgpub_xml]
[H46Z41BJPXXIFW4 | CTNF | 2012-07-06 | examiner | uspto_xml]       (non-final rejection, full text)
[H83HWKC5PXXIFW3 | CLM | 2012-10-09 | applicant | uspto_xml]       (amended claims, full text)
[H91EWNUXPXXIFW4 | CTFR | 2012-11-06 | examiner | uspto_xml]       (final rejection, full text)
[HBO4BXWBPXXIFW3 | CLM | 2013-01-07 | applicant | uspto_xml]
[HC0RDOUUPXXIFW4 | NOA | 2013-01-18 | examiner | uspto_xml]       (notice of allowance, full text)
Dated events:
- 2012-07-06 examiner mailed a non-final rejection
...
Status on 2014-09-26: allowed (notice of allowance mailed 2013-01-18).
```
Every document A downloaded for each past application, dated before the cutoff, in raw USPTO text with the same header
line as the case's own record. Nothing summarized or shortened, and no statistics. The LLM can see **what each past
invention was** (and judge whether it is really comparable to a drug-delivery device) **and what happened to it**. The
whole prompt is at most about 240k tokens, under GPT-5-mini's 272k limit.

### Step 7. Score (D, Python, no LLM)

GPT returns, for example, `{"F_allowance": [0.01, …, 0.30], "F_abandonment": [0.00, …, 0.20], "rationale": "…"}`.
This is the real answer from our 11-05 history run: 30% allowed and 20% abandoned by month 24. A scoring program
compares the predictions with the hidden answers on **the same 100 cases for every method**. It reports C-index and
IBS for Disposition, MAE and accuracy for Rounds, and C-index and MAE in days for Next Action.

---

## Part 4. Summary: what lives where, who does it, and status

| Step | What it physically is | LLM? | Who | Status |
|---|---|---|---|---|
| 1 Case files | Text files + CSV tables in `data_v1_share/apps/<id>/` | No | A | Done |
| 2 Query | A text variable in B's search program: the case's abstract + claims before the cutoff | No | B | **Fixed on 11-05** (was: letters) |
| 3 Library | Folder `profile_corpus/apps/` + table `profile_index.csv`; each past application's abstract + claims | No | A (files), B (texts) | Done |
| 4 Search | B's Python + BGE-M3 → table `ranking_top3_links_before_review.csv` (top-3 + scores) | No | B | **Fixed on 11-05** (was: TF-IDF on letters) |
| 5 Lookup | D's Python reads the 3 event logs → small outcome table | No | D | Done (`topk_math.py`) |
| 6a Top-3 average | Arithmetic in D's program | No | D | Done; set against the full-history numbers |
| 6b Prompt | Template text: `{history}` = this case's documents, `{profile}` = card, paths or fulldoc | **Yes** | D (trajectory), B (B's tasks) | **Ready to run** (D: run profile_with_embedding) |
| 7 Scoring | Python | No | D | Done |

## Part 5. What D runs this week (profile_with_embedding), and why

All runs use the same 100 cases and the same scoring.

1. **No LLM first** (free):
   - the **top-3 average** (Step 6a) against the examiner's **full-history numbers** (the statistics card): are the 3
     most similar past applications better than the examiner's whole history? This is the mentor's hypothesis;
   - the same top-3 average with the wrong examiner: is it about this examiner?
2. **Then the LLM,** with the three blocks of Step 6b (card, paths, fulldoc), each for the own and the wrong examiner.
   The main question: does the LLM given the 3 applications in full beat the top-3 average of the same 3? It must, to
   show that it reads the cases rather than repeating numbers.
3. **For the next meeting:** this document, the code, and this one case run live.

**If similar cases do not help, we will say why.** For example, case 13060040 is a drug-delivery device and its
examiner's history holds only optical sensors. The mentor asked for exactly this kind of explanation: "if it doesn't
work, explain why it doesn't".

## Part 6. Where the files are

| What | Where |
|---|---|
| Case files | `data_v1_share/apps/13060040/` (A's data zip) |
| Examiner library | `profile_corpus_v2.zip` → `profile_corpus/` (A) |
| B's new search: query texts, scores, top-3 | `B_shared_BGE_M3_dense_v1_2026_11_05_TEAM_ONLY.zip` → `queries.jsonl`, `full_ranking.csv` (all scores), `ranking_top3_links_before_review.csv` (top-3, used by D), `old_vs_new_topk.csv` (old vs new), `embedding_contract.json` (exact model and rules), `code/` |
| The statistics card text | same zip → `candidate_profiles/own/13060040.json`, field `statistics_text` (the team's frozen card) |
| D's blocks, baselines, prompts, scoring | `D_trajectory/code/` (`build_examiner_blocks_emb.py`, `topk_math.py`, `run_trajectory_llm.py`, `run_rounds_next_llm.py`, `compare_profile_with_embedding.py`, notebook `D_profile_with_embedding_run.ipynb`), `D_trajectory/prompts/` |
