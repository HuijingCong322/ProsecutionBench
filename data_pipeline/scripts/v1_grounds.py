"""Parse rejection/objection grounds from examiner-action text.
grounds(text) -> sorted list of (claim_number, ground) with ground in
  101, 102, 103, 112a, 112b, 112c, 112d, 112f, 112 (paragraph not stated), dp (double patenting),
  objection (claim objected to). Only present-tense statements ('is/are rejected', 'stand rejected')."""
import re

LIST = r"(\d{1,3}(?:(?:\s*(?:-|–|—|through|thru|to|,|and|&|or)\s*)+\d{1,3})*)"
STMT = re.compile(r"\b[Cc]laims?\s*\(?s?\)?\s*" + LIST + r"\s*(?:,\s*)?(?:as amended,?\s*)?"
                  r"(?:(?:is|are|stands?|remains?)\s+)?(?:also\s+|again\s+|now\s+|hereby\s+|further\s+|still\s+|provisionally\s+)?"
                  r"(rejected|objected\s+to)")
WITHDRAWN = re.compile(r"\b[Cc]laims?\s*\(?s?\)?\s*" + LIST + r"\s*(?:is|are)?\s*withdrawn\s+from\s+(?:further\s+)?consideration")


def withdrawn_claims(text):
    t = re.sub(r"\s+", " ", text)
    out = set()
    for m in WITHDRAWN.finditer(t):
        out |= claim_numbers(m.group(1))
    return sorted(out)
PARA = {"first": "a", "second": "b", "third": "c", "fourth": "d", "sixth": "f",
        "1st": "a", "2nd": "b", "3rd": "c", "4th": "d", "6th": "f"}


def claim_numbers(s):
    out = set()
    s = re.sub(r"\s+", " ", s)
    for a, sep, b in re.findall(r"(\d{1,3})\s*(-|–|—|through|thru|to)\s*(\d{1,3})", s):
        a, b = int(a), int(b)
        if a <= b <= a + 400:
            out.update(range(a, b + 1))
    s2 = re.sub(r"\d{1,3}\s*(?:-|–|—|through|thru|to)\s*\d{1,3}", " ", s)
    out.update(int(x) for x in re.findall(r"\d{1,3}", s2))
    return out


def ground_of(window):
    """All grounds stated in the sentence that follows 'rejected' (e.g. '102(b) ... or, in the
    alternative, under 35 U.S.C. 103(a)' gives both)."""
    end = re.search(r"\.\s+[A-Z]", window)
    w = (window[: end.start()] if end else window).lower()
    if "double patenting" in w:
        return ["dp"]
    found = []
    for m in re.finditer(r"(?:35\s*u\.?\s*s\.?\s*c\.?|§)\s*§?\s*(101|102|103|112)\s*(\(\s*([a-f])\s*\)|(?:\s*\(pre-aia\))?,?\s*(first|second|third|fourth|sixth|1st|2nd|3rd|4th|6th)\s+paragraph)?", w):
        st = m.group(1)
        if st == "112":
            st += m.group(3) or PARA.get(m.group(4) or "", "")
        found.append(st)
    if found:
        found = set(found)
        if any(f.startswith("112") and len(f) == 4 for f in found):
            found.discard("112")                     # '112(b) or pre-AIA 112, second paragraph'
        return sorted(found)
    g = ground_one(w)
    return [g] if g else []


def ground_one(w):
    m = re.search(r"(?:35\s*u\.?\s*s\.?\s*c\.?|§)\s*§?\s*(101|102|103|112)\s*(\(\s*([a-f])\s*\)|,?\s*(first|second|third|fourth|sixth)\s+paragraph)?", w)
    if not m:
        m2 = re.search(r"\b(101|102|103|112)\b", w[:120])
        return m2.group(1) if m2 else None
    st = m.group(1)
    if st == "112":
        sub = m.group(3) or PARA.get(m.group(4) or "")
        if not sub:
            m3 = re.search(r"112\s*(?:,\s*)?(first|second|third|fourth|sixth)\s+paragraph|112\s*\(\s*([a-f])\s*\)|pre-aia\s+35\s+u\.s\.c\.\s+112,\s*(first|second|fourth|sixth)", w)
            if m3:
                sub = m3.group(2) or PARA.get(m3.group(1) or m3.group(3) or "")
        return "112" + (sub or "")
    return st


def grounds(text):
    t = re.sub(r"\s+", " ", text)
    out = set()
    for m in STMT.finditer(t):
        nums = claim_numbers(m.group(1))
        if not nums or max(nums) > 500:
            continue
        if m.group(2).startswith("objected"):
            g = "objection"
        else:
            gs = ground_of(t[m.end(): m.end() + 300])
            out.update((n, g) for n in nums for g in gs)
            continue
        out.update((n, g) for n in nums)
    return sorted(out)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        g = grounds(open(p).read())
        from collections import defaultdict
        by = defaultdict(list)
        for c, gr in g:
            by[gr].append(c)
        print(p.split("/")[-1], {k: f"{min(v)}-{max(v)} ({len(v)})" for k, v in by.items()})
