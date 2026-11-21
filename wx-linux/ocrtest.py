import time, sys
from rapidocr_onnxruntime import RapidOCR
from PIL import Image
eng = RapidOCR()
img = Image.open(sys.argv[1]).crop(tuple(map(int, sys.argv[2:6])))
p = "/tmp/_crop.png"; img.save(p)
t0 = time.time()
res, _ = eng(p)
print(f"耗时 {time.time()-t0:.2f}s，识别 {len(res or [])} 行")
for box, text, score in (res or []):
    x = sum(pt[0] for pt in box)/4; y = sum(pt[1] for pt in box)/4
    print(f"  x={x:6.0f} y={y:6.0f} {score:.2f}  {text}")
