from pathlib import Path
import subprocess,json
from pypdf import PdfReader
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parent
poppler=Path(r'C:\Users\an183\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe')
report=[]
for folder in root.glob('render_北交所*'):
    pdf=next(folder.glob('*.pdf'))
    reader=PdfReader(pdf)
    for stale in folder.glob('page-*.png'):
        if int(stale.stem.split('-')[-1])>len(reader.pages): stale.unlink()
    subprocess.run([str(poppler),'-r','110','-png',str(pdf),str(folder/'page')],check=True,capture_output=True)
    texts=[p.extract_text() for p in reader.pages]
    (folder/'extracted.txt').write_text('\n\n'.join(f'PAGE {i+1}\n{t}' for i,t in enumerate(texts)),'utf-8')
    report.append({'file':pdf.name,'pages':len(texts),'text_chars_by_page':[len(t) for t in texts]})
    pages=sorted(folder.glob('page-*.png'))
    for first in range(0,len(pages),6):
        group=pages[first:first+6]
        sheet=Image.new('RGB',(900,470*((len(group)+2)//3)), 'white'); draw=ImageDraw.Draw(sheet)
        for i,path in enumerate(group):
            im=Image.open(path).convert('RGB'); im.thumbnail((290,435))
            x=(i%3)*300; y=(i//3)*470
            sheet.paste(im,(x,y+20)); draw.text((x+5,y+3),path.stem,fill='black')
        sheet.save(folder/f'contact-{first//6+1}.jpg')
(root/'render_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(report,ensure_ascii=False))
