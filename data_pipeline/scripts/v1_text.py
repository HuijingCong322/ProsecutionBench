"""Text extraction for data_v1 (offline). Usage: python3 scripts/v1_text.py [--ocr] [--jobs N] [app ...]
For every application in data_v1/apps (or the ones given):
  pub/pgpub.*  -> text/pgpub_abstract.txt, text/pgpub_description.txt, text/pgpub_claims.json
  pub/grant.*  -> text/grant_claims.json (+ grant_abstract/description)
  xml/<stem>.xml.bin -> text/<stem>.txt (claim documents also text/<stem>.claims.json)
  pdf/<stem>.pdf (only documents without USPTO text) -> text/<stem>.txt by OCR, only with --ocr
Claims JSON: [{"number", "status", "type", "depends_on", "text"}] (status/type empty for publications).
Writes text/sources.json: {stem: "pgpub_xml" | "grant_xml" | "uspto_xml" | "ocr"}."""
import io, json, re, subprocess, sys, tarfile, tempfile, zipfile
from multiprocessing import Pool
from pathlib import Path
from lxml import etree

D = Path(__file__).resolve().parent.parent / "data_v1"
PARSER = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
BLOCK = {"p", "heading", "headertext", "li", "formparagraph", "claimtext", "claim-text",
         "paragraph", "paragraphtext", "tableheadercell", "tablecell", "entry", "row", "title",
         "abstracttext", "td", "th", "tr"}
SKIP = {"boundarydata", "documentmetadata", "claimstatuscategory", "claimtypecategory", "claimnumber",
        "spannedboundarydata", "boundarydatareference", "formparagraphnumber"}


def local(tag):
    return tag.split("}")[-1].lower() if isinstance(tag, str) else ""


def blocks(el, substantive=False):
    """Document-order text with one line per block element; nested blocks are not repeated.
    substantive=True drops the standardized text of examiner form paragraphs (uscom:FormParagraph) and
    keeps only what the examiner typed into their data fields, plus all free text outside them."""
    out, buf = [], []

    def flush():
        t = re.sub(r"\s+", " ", "".join(buf)).strip()
        if t:
            out.append(t)
        buf.clear()

    def walk(e):
        name = local(e.tag)
        if name in SKIP:
            if e.tail:
                buf.append(e.tail)
            return
        if substantive and name == "formparagraph":
            flush()
            for df in e.iter():
                if local(df.tag) == "datafield":
                    t = re.sub(r"\s+", " ", "".join(df.itertext())).strip()
                    if t:
                        out.append(t)
            if e.tail:
                buf.append(e.tail)
            return
        is_block = name in BLOCK
        if is_block:
            flush()
        if e.text and isinstance(e.tag, str):
            buf.append(e.text)
        for c in e:
            walk(c)
        if is_block:
            flush()
        if e.tail:
            buf.append(e.tail)

    walk(el)
    flush()
    return "\n".join(out)


def read_archive(p):
    """Return the main XML bytes from a .xml / .zip / .tar / .xml.bin file."""
    b = p.read_bytes()
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b))
        n = max((n for n in z.namelist() if n.lower().endswith(".xml")), key=lambda n: z.getinfo(n).file_size)
        return z.read(n)
    if len(b) > 262 and b[257:262] == b"ustar":
        t = tarfile.open(fileobj=io.BytesIO(b))
        m = max((m for m in t.getmembers() if m.name.lower().endswith(".xml")), key=lambda m: m.size)
        return t.extractfile(m).read()
    return b


def first(root, names):
    for e in root.iter():
        if local(e.tag) in names:
            return e
    return None


def claims_st96(root):
    out = []
    for c in root.iter():
        if local(c.tag) != "claim":
            continue
        g = lambda n: next((x for x in c if local(x.tag) == n), None)
        num, st, ty = g("claimnumber"), g("claimstatuscategory"), g("claimtypecategory")
        refs = [r.text.strip() for r in c.iter() if local(r.tag) == "claimreference" and r.text]
        txt = " ".join(blocks(t).replace("\n", " ") for t in c if local(t.tag) == "claimtext")
        out.append({"number": num.text.strip() if num is not None and num.text else None,
                    "status": st.text.strip() if st is not None and st.text else "",
                    "type": ty.text.strip() if ty is not None and ty.text else "",
                    "depends_on": refs, "text": re.sub(r"\s+", " ", txt).strip()})
    return out


def claims_redbook(root):
    out = []
    for c in root.iter():
        if local(c.tag) != "claim":
            continue
        num = (c.get("num") or "").lstrip("0") or None
        refs = []
        for r in c.iter():
            if local(r.tag) == "claim-ref":
                m = re.search(r"\d+", r.get("idref") or "")
                if m:
                    refs.append(m.group(0).lstrip("0"))
        txt = re.sub(r"\s+", " ", "".join(c.itertext())).strip()
        out.append({"number": num, "status": "", "type": "dependent" if refs else "independent",
                    "depends_on": refs, "text": txt})
    return out


def do_pub(app_dir, name, sources):
    files = [p for p in (app_dir / "pub").glob(f"{name}.*") if not p.name.endswith(".download")] \
        if (app_dir / "pub").exists() else []
    if not files:
        return
    root = etree.fromstring(read_archive(files[0]), PARSER)
    if root is None:
        return
    tx = app_dir / "text"
    for part in ("abstract", "description"):
        e = first(root, {part})
        if e is not None:
            (tx / f"{name}_{part}.txt").write_text(blocks(e))
            sources[f"{name}_{part}"] = f"{name}_xml"
    cl = claims_redbook(root)
    (tx / f"{name}_claims.json").write_text(json.dumps(cl, indent=1))
    sources[f"{name}_claims"] = f"{name}_xml"


def ocr_pdf(pdf):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(pdf), f"{td}/p"], check=True)
        pages = []
        for i, img in enumerate(sorted(Path(td).glob("p*.png")), 1):
            r = subprocess.run(["tesseract", str(img), "-", "--psm", "6"], capture_output=True, text=True)
            pages.append(r.stdout.strip())
    return "\n".join(pages)


def ocr_job(args):
    pdf, out = args
    try:
        out.write_text(ocr_pdf(pdf))
        return str(pdf), "ok"
    except Exception as e:
        return str(pdf), f"error {e}"


def process(app_dir, do_ocr):
    tx = app_dir / "text"
    tx.mkdir(exist_ok=True)
    sp = tx / "sources.json"
    sources = json.loads(sp.read_text()) if sp.exists() else {}
    for name in ("pgpub", "grant"):
        try:
            do_pub(app_dir, name, sources)
        except Exception as e:
            print(app_dir.name, name, "parse error", e)
    for f in sorted((app_dir / "xml").glob("*.xml.bin")) if (app_dir / "xml").exists() else []:
        stem = f.name[:-len(".xml.bin")]
        try:
            root = etree.fromstring(read_archive(f), PARSER)
        except Exception as e:
            print(app_dir.name, stem, "xml error", e)
            continue
        if root is None:
            continue
        if "_CLM_" in f.name:
            (tx / f"{stem}.claims.json").write_text(json.dumps(claims_st96(root), indent=1))
        (tx / f"{stem}.txt").write_text(blocks(root))
        if any(local(e.tag) == "formparagraph" for e in root.iter()):
            (tx / f"{stem}.substantive.txt").write_text(blocks(root, substantive=True))
        sources[stem] = "uspto_xml"
    jobs = []
    for f in sorted((app_dir / "pdf").glob("*.pdf")) if (app_dir / "pdf").exists() else []:
        if f.stem in sources and sources[f.stem] != "ocr":
            continue
        out = tx / f"{f.stem}.txt"
        v0 = D.parent / "data_v0" / "apps" / app_dir.name / "text_clean" / f"{f.stem}.txt"
        if not out.exists() and v0.exists():          # same document already OCRed for data_v0: reuse
            out.write_text(v0.read_text())
        if out.exists():
            sources[f.stem] = "ocr"
        elif do_ocr:
            jobs.append((f, out))
    sp.write_text(json.dumps(sources, indent=1))
    return jobs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_ocr = "--ocr" in sys.argv
    jobs_n = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--jobs=")), "4"))
    apps = [D / "apps" / a for a in args] if args else sorted(p for p in (D / "apps").iterdir() if p.is_dir())
    jobs = []
    for a in apps:
        jobs += process(a, do_ocr)
    print(f"text extracted for {len(apps)} apps; OCR jobs: {len(jobs)}", flush=True)
    if jobs:
        with Pool(jobs_n) as pool:
            for i, (pdf, st) in enumerate(pool.imap_unordered(ocr_job, jobs), 1):
                print(f"OCR [{i}/{len(jobs)}] {Path(pdf).name} {st}", flush=True)
        for a in apps:
            process(a, False)


if __name__ == "__main__":
    main()
