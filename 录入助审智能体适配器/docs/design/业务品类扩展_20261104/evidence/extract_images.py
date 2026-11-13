from pathlib import Path
import re
from PIL import Image

root=Path(__file__).parent
data=Path(r'C:\Users\an183\Desktop\文件资料\北交所相关资料\北交所二期\需规\产权转让、企业增资、机动车.rtf').read_text('latin1')
for i,m in enumerate(re.finditer(r'\\(pngblip|jpegblip)\b',data),1):
    tail=data[m.end():]
    tail=re.sub(r'^\s*\{\\\*\\blipuid [0-9a-fA-F]+\}', '',tail)
    tail=tail[:tail.index('}')]
    # RTF picture metadata controls precede the hexadecimal byte stream.
    tail=re.sub(r'\\[a-zA-Z]+-?\d* ?', '',tail)
    hexdata=''.join(re.findall(r'[0-9a-fA-F]+',tail))
    out=root/f'requirements_flow_{i}.{ "png" if m.group(1)=="pngblip" else "jpg" }'
    out.write_bytes(bytes.fromhex(hexdata))
    im=Image.open(out)
    print(out.name, im.size)
