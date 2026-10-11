"""Parse a human-reviewed data_v0 claims_markup listing (<ins>added</ins>, <del>deleted</del>) into
claim records: {claim_id: (status, pre_text, post_text)}. pre = deleted text kept, added text removed;
post = added text kept, deleted text removed. Ranges like '1.-10. (Canceled)' are expanded."""
import re
HEAD = re.compile(r"(?m)^\s*(?:Claims?\s+)?(\d{1,3})\s*\.?\s*(?:-\s*(\d{1,3})\s*\.?)?\s*\(\s*([A-Za-z][A-Za-z ]*?)\s*\)")
def status(s):
    s = s.lower().replace("cancelled", "canceled")
    for k in ("currently amended", "previously presented", "original", "new", "canceled", "withdrawn"):
        if k in s: return k.replace(" ", "_")
    return s
def strip(t): return re.sub(r"\s+", " ", re.sub(r"</?(ins|del)>", "", t)).strip()
HEADER = re.compile(r"(?i)^\s*(?:application\s+no\.?|appl\.?\s*no|u\.s\.\s+patent\s+application|united\s+states\s+patent\s+application|"
                    r"attorney\s+docket|atty\.?\s*dkt|docket\s+no|amendment\s+dated|reply\s+to\s+office\s+action|response\s+to\s+office\s+action|"
                    r"-\s*\d{1,3}\s*-\s*$|\d{4}-\d{4}-\d{4}\.\d+\s*$|page\s+\d+\s+of\s+\d+)")
INLINE = re.compile(r"(?i)\s*(?:U\.S\.\s+Patent\s+Application\s+Serial\s+No\.\s*[\d/,]+\s*)?Reply\s+to\s+Office\s+Action\s+of\s+\w+\s+\d{1,2},\s+\d{4}|"
                    r"\s*U\.S\.\s+Patent\s+Application\s+Serial\s+No\.\s*[\d/,]+")
def drop_headers(text):
    """remove page header/footer lines (application/docket numbers, dates, page numbers) of the listing"""
    return INLINE.sub(" ", "\n".join(l for l in text.splitlines() if not HEADER.match(re.sub(r"</?(ins|del)>", "", l))))
def parse(text):
    text = drop_headers(text)
    out = {}; hs = list(HEAD.finditer(text))
    for i, m in enumerate(hs):
        body = text[m.end(): hs[i + 1].start() if i + 1 < len(hs) else len(text)]
        pre = strip(re.sub(r"<ins>.*?</ins>", " ", body, flags=re.S))
        post = strip(re.sub(r"<del>.*?</del>", " ", body, flags=re.S))
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        for n in range(a, b + 1): out.setdefault(n, (status(m.group(3)), pre, post, "<ins>" in body or "<del>" in body))
    return out
