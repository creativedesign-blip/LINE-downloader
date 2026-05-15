from pathlib import Path
from rapidocr_onnxruntime import RapidOCR
p = next(Path(r'C:\Users\user\Desktop\LINE-downloader-main\line-rpa\download\凱旋旅行社_巨匠旅遊').glob('*.png'))
print('image', p)
engine = RapidOCR()
result, _ = engine(str(p))
print('items', len(result or []))
print('\n'.join(str(x[1]) for x in (result or [])[:10] if len(x) >= 2))
