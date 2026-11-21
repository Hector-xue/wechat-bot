import time
from rapidocr_onnxruntime import RapidOCR
from PIL import Image
eng = RapidOCR()
img = Image.open("cn-test.png")
for name, box in [("全聊天区 590x620", (560,170,1150,790)),
                  ("下部 590x320", (560,470,1150,790)),
                  ("下部 590x220", (560,570,1150,790))]:
    crop = img.crop(box); crop.save("/tmp/c.png")
    for cls in (True, False):
        t0 = time.time()
        res, _ = eng("/tmp/c.png", use_det=True, use_cls=cls, use_rec=True)
        print(f"{name:20s} cls={cls!s:5s} {time.time()-t0:5.2f}s  行数={len(res or [])}")
