"""Writes into the RUP test plan template (template.docx) with the template's own styles.

The cover, revision history, table of contents field, headers and footers stay the template's;
everything from the first chapter on is replaced. Technique and risk tables are cloned from the
template's own tables, so they keep its borders and shading.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Report:
    def __init__(self, template: Path, *, project: str, title: str, version: str, company: str) -> None:
        self.doc = docx.Document(str(template))
        body = self.doc.element.body
        kids = list(body.iterchildren())
        tables = self.doc.tables
        self._technique = copy.deepcopy(tables[1]._tbl)   # 6 x 2: label | content
        self._risk = copy.deepcopy(tables[-1]._tbl)       # header + rows, 3 columns
        self._revision = tables[0]
        cp = self.doc.core_properties
        cp.title, cp.subject, cp.author, cp.keywords = title, project, company, "test plan, test report"
        self.company = company

        paras = [Paragraph(k, self.doc) if k.tag == W + "p" else None for k in kids]
        # Cover: drop the template's guidance note, set the version line.
        for p in paras:
            if p is None:
                continue
            if p.style.name == "Title" and p.text.startswith("Version"):
                self._set_text(p, f"Version {version}")
            if p.style.name == "InfoBlue" and p.text.strip():
                self._set_text(p, "")
        # Table of contents: one real TOC field in place of the template's static lines; Word
        # fills it when the document is opened and fields are updated (export.ps1 does that).
        toc = [p for p in paras if p is not None and (p.style.name.startswith("toc") or p.text.strip().startswith("6.      References"))]
        first = toc[0]._p
        field = self._toc_field()
        first.addprevious(field)
        for p in toc:
            p._p.getparent().remove(p._p)
        # Body: everything from the first Heading 1 up to the final section properties goes.
        start = next(i for i, p in enumerate(paras) if p is not None and p.style.name == "Heading 1")
        for k in kids[start:]:
            if k.tag != W + "sectPr":
                body.remove(k)
        self._sect = body.find(W + "sectPr")

    # -- helpers ---------------------------------------------------------------------------------

    @staticmethod
    def _set_text(p: Paragraph, text: str) -> None:
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
        if p.runs:
            p.runs[0].text = text
        else:
            p.add_run(text)

    @staticmethod
    def _toc_field():
        p = OxmlElement("w:p")
        for kind, text in (("begin", None), (None, ' TOC \\o "1-3" \\h \\z \\u '), ("separate", None),
                           ("text", "Right-click and choose Update Field to build the table of contents."), ("end", None)):
            r = OxmlElement("w:r")
            if kind in ("begin", "separate", "end"):
                f = OxmlElement("w:fldChar")
                f.set(qn("w:fldCharType"), kind)
                r.append(f)
            elif kind == "text":
                t = OxmlElement("w:t")
                t.text = text
                r.append(t)
            else:
                t = OxmlElement("w:instrText")
                t.set(qn("xml:space"), "preserve")
                t.text = text
                r.append(t)
            p.append(r)
        return p

    def _append(self, el) -> None:
        self._sect.addprevious(el)

    def _para(self, style: str) -> Paragraph:
        p = OxmlElement("w:p")
        self._append(p)
        para = Paragraph(p, self.doc)
        para.style = self.doc.styles[style]
        return para

    def revision(self, rows: list[tuple[str, str, str, str]]) -> None:
        t = self._revision
        for i, row in enumerate(rows, start=1):
            for j, v in enumerate(row):
                cell = t.rows[i].cells[j]
                cell.paragraphs[0].text = v
        for r in list(t.rows)[len(rows) + 1:]:
            r._tr.getparent().remove(r._tr)

    # -- content -------------------------------------------------------------------------------

    def h1(self, text: str) -> None:
        self._para("Heading 1").add_run(text)

    def h2(self, text: str) -> None:
        self._para("Heading 2").add_run(text)

    def h3(self, text: str) -> None:
        self._para("Heading 3").add_run(text)

    def page_break(self) -> None:
        self._para("Body Text").add_run().add_break(docx.enum.text.WD_BREAK.PAGE)

    def p(self, text: str, style: str = "Body Text") -> Paragraph:
        """A paragraph; **bold** and `code` spans are honoured."""
        para = self._para(style)
        self._runs(para, text)
        return para

    @staticmethod
    def _script_font(run) -> None:
        """Sinhala and Tamil need a font that has the glyphs, on the complex-script slot too."""
        if not any("඀" <= ch <= "෿" or "஀" <= ch <= "௿" for ch in run.text):
            return
        run.font.name = "Nirmala UI"
        rpr = run._r.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for slot in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(slot), "Nirmala UI")

    def _runs(self, para: Paragraph, text: str) -> None:
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
            if not part:
                continue
            if part.startswith("**"):
                para.add_run(part[2:-2]).bold = True
            elif part.startswith("`"):
                r = para.add_run(part[1:-1])
                r.font.name = "Consolas"
                r.font.size = Pt(9)
            else:
                self._script_font(para.add_run(part))

    def bullets(self, items: list[str], style: str = "Bullet1") -> None:
        """The template's bullet style carries no numbering definition, so the glyph is explicit."""
        for it in items:
            para = self._para(style)
            para.add_run("•  ")
            para.paragraph_format.left_indent = Inches(0.5)
            para.paragraph_format.first_line_indent = Inches(-0.2)
            self._runs(para, it)

    def technique(self, rows: dict[str, str | list[str]]) -> None:
        """The template's label | content table. A list value becomes bullet lines."""
        tbl = copy.deepcopy(self._technique)
        self._append(tbl)
        t = Table(tbl, self.doc)
        labels = list(rows)
        for i, row in enumerate(t.rows):
            if i >= len(labels):
                row._tr.getparent().remove(row._tr)
                continue
            left, right = row.cells[0], row.cells[1]
            self._fill(left, labels[i], bold=False)
            value = rows[labels[i]]
            self._fill(right, value)

    def _fill(self, cell, value, bold=False) -> None:
        for extra in cell.paragraphs[1:]:
            extra._p.getparent().remove(extra._p)
        # Nested tables in the template cell (none expected) are left alone.
        first = cell.paragraphs[0]
        for r in list(first.runs):
            r._r.getparent().remove(r._r)
        first.style = self.doc.styles["Tabletext"]
        lines = value if isinstance(value, list) else [value]
        for i, line in enumerate(lines):
            para = first if i == 0 else cell.add_paragraph(style="Tabletext")
            if isinstance(value, list):
                para.add_run("•  ")
                para.paragraph_format.left_indent = Inches(0.15)
                para.paragraph_format.first_line_indent = Inches(-0.15)
            self._runs(para, line)
            if bold:
                for r in para.runs:
                    r.bold = True
            para.paragraph_format.space_after = Pt(3)

    def table(self, header: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
        """A plain grid table, header shaded like the template's risk table."""
        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        self._sect.addprevious(t._tbl)
        t.style = self.doc.styles["Normal Table"]
        borders = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), "808080")
            borders.append(b)
        t._tbl.tblPr.append(borders)
        for j, h in enumerate(header):
            c = t.rows[0].cells[j]
            self._fill(c, h, bold=True)
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "F2F2F2")
            c._tc.get_or_add_tcPr().append(shd)
        for i, row in enumerate(rows, start=1):
            for j, v in enumerate(row):
                self._fill(t.rows[i].cells[j], v)
        if widths:
            for row in t.rows:
                for j, w in enumerate(widths):
                    row.cells[j].width = Inches(w)
        self._para("Body Text")  # breathing room after the table

    def risks(self, rows: list[tuple[str, list[str], list[str]]]) -> None:
        tbl = copy.deepcopy(self._risk)
        self._append(tbl)
        t = Table(tbl, self.doc)
        proto = copy.deepcopy(t.rows[1]._tr)
        for r in list(t.rows)[1:]:
            r._tr.getparent().remove(r._tr)
        for risk, mitigation, contingency in rows:
            tr = copy.deepcopy(proto)
            tbl.append(tr)
            row = t.rows[-1]
            self._fill(row.cells[0], risk)
            self._fill(row.cells[1], mitigation)
            self._fill(row.cells[2], contingency)
        self._para("Body Text")

    def image(self, path: Path, caption: str, width: float = 6.0) -> None:
        para = self._para("Body Text")
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(str(path), width=Inches(width))
        cap = self._para("Body Text")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cap.add_run(caption)
        r.italic = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    def save(self, out: Path) -> None:
        # Company name for the header and footer DOCPROPERTY fields.
        self.doc.save(str(out))
        import zipfile
        tmp = out.with_suffix(".tmp")
        with zipfile.ZipFile(out) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "docProps/app.xml":
                    data = data.replace(b"&lt;Company Name&gt;", self.company.encode())
                if item.filename.startswith("word/footer") or item.filename.startswith("word/header"):
                    data = data.replace(b"&lt;Company Name&gt;", self.company.encode())
                zout.writestr(item, data)
        tmp.replace(out)
