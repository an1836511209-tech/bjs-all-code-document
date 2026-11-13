from pathlib import Path
import re, textwrap, json
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parent.parent
FONT='Microsoft YaHei'

def font(run,size=None,bold=None):
    run.font.name=FONT
    if size: run.font.size=Pt(size)
    if bold is not None: run.bold=bold
    run.font.color.rgb=RGBColor(0,0,0)
    rpr=run._element.get_or_add_rPr()
    rf=rpr.find(qn('w:rFonts'))
    if rf is None:
        rf=OxmlElement('w:rFonts'); rpr.insert(0,rf)
    for k in ['ascii','hAnsi','eastAsia','cs']: rf.set(qn('w:'+k),FONT)

def clean(s):
    return re.sub(r'`([^`]+)`',r'\1',s).replace('**','')

def add_text(p,s,size=None):
    font(p.add_run(clean(s)),size)

def table(doc,lines):
    data=[[clean(v.strip()) for v in l.strip().strip('|').split('|')] for l in lines]
    data=[r for r in data if not all(re.fullmatch(r':?-+:?',c) for c in r)]
    n=len(data[0]); t=doc.add_table(rows=1,cols=n); t.autofit=False
    compact=data[0][0].startswith('需求标识')
    widths={2:[4.1,12.9],3:[4.1,6.4,6.5],4:[3.7,4.3,5.2,3.8],5:[2.8,3.6,3.6,3.6,3.4]}.get(n,[17/n]*n)
    for c,w in zip(t.columns,widths): c.width=Cm(w)
    pr=t._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for side in ['top','left','bottom','right','insideH','insideV']:
        b=OxmlElement('w:'+side); b.set(qn('w:val'),'single'); b.set(qn('w:sz'),'4'); b.set(qn('w:color'),'D9D9D9'); borders.append(b)
    pr.append(borders)
    for i,row in enumerate(data):
        cells=t.rows[0].cells if i==0 else t.add_row().cells
        trpr=cells[0]._tc.getparent().get_or_add_trPr()
        cant=OxmlElement('w:cantSplit'); trpr.append(cant)
        if i==0:
            repeat=OxmlElement('w:tblHeader'); trpr.append(repeat)
        for j,(cell,value) in enumerate(zip(cells,row)):
            cell.width=Cm(widths[j]); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr=cell._tc.get_or_add_tcPr()
            shading=OxmlElement('w:shd'); shading.set(qn('w:fill'),'DFE8F0' if i==0 else ('F5F7F9' if i%2==0 else 'FFFFFF')); tcpr.append(shading)
            margins=OxmlElement('w:tcMar')
            for side in ['top','left','bottom','right']:
                x=OxmlElement('w:'+side); x.set(qn('w:w'),'50' if compact and side in ['top','bottom'] else '85'); x.set(qn('w:type'),'dxa'); margins.append(x)
            tcpr.append(margins)
            p=cell.paragraphs[0]
            p.paragraph_format.space_after=Pt(1); p.paragraph_format.space_before=Pt(1); p.paragraph_format.line_spacing=1.13
            if compact:
                p.paragraph_format.space_after=Pt(0); p.paragraph_format.space_before=Pt(0)
            if i==0: p.paragraph_format.keep_with_next=True
            if len(value)<18 and j==0 and not '/' in value: p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            value=value.replace('/','/\u200b').replace('_','_\u200b')
            r=p.add_run(value); font(r,9.1,i==0)
    p=doc.add_paragraph(); p.paragraph_format.space_after=Pt(1); p.paragraph_format.space_before=Pt(0); p.paragraph_format.line_spacing=0.35
    p.add_run().font.size=Pt(3)

def build(name):
    source=ROOT/f'{name}.md'; text=source.read_text('utf-8'); lines=text.splitlines()
    d=Document(); sec=d.sections[0]
    sec.page_width=Cm(21); sec.page_height=Cm(29.7)
    sec.top_margin=Cm(1.9); sec.bottom_margin=Cm(1.8); sec.left_margin=Cm(2); sec.right_margin=Cm(2)
    sec.footer_distance=Cm(.8)
    for sty in ['Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3']:
        s=d.styles[sty]; s.font.name=FONT; s.font.color.rgb=RGBColor(0,0,0)
        rpr=s.element.get_or_add_rPr(); rf=OxmlElement('w:rFonts')
        for k in ['ascii','hAnsi','eastAsia']: rf.set(qn('w:'+k),FONT)
        rpr.append(rf)
    normal=d.styles['Normal']; normal.font.size=Pt(10.3)
    normal.paragraph_format.line_spacing=1.2; normal.paragraph_format.space_after=Pt(5)
    for level,size in [(1,15),(2,12),(3,11)]:
        s=d.styles[f'Heading {level}']; s.font.size=Pt(size); s.font.bold=True
        s.paragraph_format.space_before=Pt(13 if level==1 else 9); s.paragraph_format.space_after=Pt(5)
        s.paragraph_format.keep_with_next=True
    d.styles['Title'].font.size=Pt(24); d.styles['Title'].font.bold=True
    for style in d.styles:
        for border in list(style.element.iter(qn('w:pBdr'))): border.getparent().remove(border)
    d.core_properties.title=clean(lines[0][2:]); d.core_properties.subject='产权转让 企业增资 机动车业务扩展'
    d.core_properties.author=''; d.core_properties.keywords='概要设计 详细设计 业务扩展'
    footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=footer.add_run(); font(r,9)
    f=OxmlElement('w:fldSimple'); f.set(qn('w:instr'),'PAGE'); r._r.addnext(f)
    firstheading=next(i for i,l in enumerate(lines) if l.startswith('## '))
    d.add_paragraph(clean(lines[0][2:]),'Title')
    pre=[l for l in lines[1:firstheading] if l.strip()]
    for i,l in enumerate(pre):
        p=d.add_paragraph(); add_text(p,l,12 if i==0 else (9.5 if i<3 else 10.3))
        if i==0: p.paragraph_format.space_after=Pt(14)
    p=d.add_paragraph(); font(p.add_run('文档导航'),11,True)
    for l in lines:
        if l.startswith('## '):
            p=d.add_paragraph(); p.paragraph_format.space_after=Pt(2); p.paragraph_format.line_spacing=1.05
            add_text(p,l[3:],9.5)
    d.add_page_break()
    i=firstheading
    while i<len(lines):
        l=lines[i]
        if not l.strip(): i+=1; continue
        if l.startswith('```'):
            language=l[3:]; code=[]; i+=1
            while i<len(lines) and not lines[i].startswith('```'): code.append(lines[i]); i+=1
            if language=='json': json.loads('\n'.join(code))
            for ci,line in enumerate(code):
                p=d.add_paragraph(); p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing=1.05
                if ci<len(code)-1: p.paragraph_format.keep_with_next=True
                r=p.add_run(line); font(r,8.5); r.font.name='Consolas'
            d.add_paragraph().paragraph_format.space_after=Pt(1)
        elif l.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'): rows.append(lines[i]); i+=1
            table(d,rows); continue
        elif re.match(r'^!\[',l):
            m=re.match(r'!\[(.*?)\]\((.*?)\)',l)
            p=d.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            pic=p.add_run().add_picture(str(ROOT/m.group(2)),width=Cm(16.7))
            # Accessibility metadata without adding a printed duplicate caption.
            pic._inline.docPr.set('descr',m.group(1))
        elif l.startswith('### '): d.add_paragraph(clean(l[4:]),'Heading 2')
        elif l.startswith('## '):
            p=d.add_paragraph(clean(l[3:]),'Heading 1')
            if name=='概要设计' and l.startswith('## 8 '): p.paragraph_format.page_break_before=True
        else:
            p=d.add_paragraph(); add_text(p,l)
        i+=1
    out=ROOT/f'北交所业务品类扩展{name}_V1.0.docx'; d.save(out)
    print(out.name, len(d.paragraphs),'paragraphs',len(d.tables),'tables')

for name in ['概要设计','详细设计']: build(name)
