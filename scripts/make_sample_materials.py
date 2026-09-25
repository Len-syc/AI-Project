# -*- coding: utf-8 -*-
"""生成演示样本材料图片 + mock 识别结果（.meta.json sidecar）。
样本全部为合成图，仅用于演示；故意让申请表姓名与身份证不一致，用于演示跨材料冲突检查。"""
import os
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "data", "sample_materials")
os.makedirs(OUT, exist_ok=True)


def font(size, index=0):
    return ImageFont.truetype(FONT, size, index=index)


def canvas(w, h, bg="#f5f7fa"):
    img = Image.new("RGB", (w, h), bg)
    return img, ImageDraw.Draw(img)


def watermark(d, w, h):
    d.text((w // 2, h // 2), "演 示 样 本", font=font(110), fill=(255, 120, 120, 30), anchor="mm")


def save(img, name, doc_type, fields):
    path = os.path.join(OUT, name)
    img.save(path)
    with open(os.path.join(OUT, name.replace(".png", ".meta.json")), "w", encoding="utf-8") as f:
        f.write('{"doc_type": "%s", "fields": %s}' % (doc_type, _fields_json(fields)))
    print("saved:", name, "->", doc_type)


def _fields_json(fields):
    import json
    return json.dumps(fields, ensure_ascii=False)


# ---------- 1. 身份证（正面示意） ----------
img, d = canvas(860, 540, "#2f6fb3")
d.rounded_rectangle((20, 20, 840, 520), 24, outline="#ffffff", width=3)
d.text((50, 60), "中华人民共和国居民身份证（演示样本）", font=font(34), fill="white")
rows = [("姓    名", "张三"), ("性    别", "男"), ("民    族", "汉"),
        ("出    生", "1999 年 1 月 1 日"), ("住    址", "江苏省苏州市工业园区某路 88 号"),
        ("公民身份号码", "3205 1999 0101 0011（演示占位）")]
y = 150
for k, v in rows:
    d.text((70, y), k, font=font(30), fill="#dce9f8")
    d.text((300, y), v, font=font(30), fill="white")
    y += 58
watermark(d, 860, 540)
save(img, "身份证_张三.png", "身份证明",
     {"姓名": "张三", "证件号码": "3205199901010011", "住址": "江苏省苏州市工业园区"})

# ---------- 2. 营业执照 ----------
img, d = canvas(900, 620, "#fdf6ec")
d.rectangle((20, 20, 880, 600), outline="#c9a063", width=4)
d.text((450, 70), "营 业 执 照", font=font(48), fill="#8a5a2b", anchor="mm")
d.text((450, 130), "（演示样本）", font=font(26), fill="#8a5a2b", anchor="mm")
rows = [("统一社会信用代码", "91320594MADEMO000X"),
        ("名        称", "苏州星辉科技有限公司"),
        ("类        型", "有限责任公司（自然人独资）"),
        ("法定代表人", "张三"),
        ("注册资本", "人民币 10 万元"),
        ("成立日期", "2026 年 3 月 15 日"),
        ("住        所", "苏州工业园区某创意产业园 3 幢")]
y = 180
for k, v in rows:
    d.text((80, y), k, font=font(28), fill="#6b4a22")
    d.text((400, y), v, font=font(28), fill="#3a2a12")
    y += 56
d.text((760, 560), "登记机关（演示章）", font=font(24), fill="#b03a2e")
watermark(d, 900, 620)
save(img, "营业执照_星辉科技.png", "营业执照",
     {"企业名称": "苏州星辉科技有限公司", "法定代表人": "张三", "成立日期": "2026-03"})

# ---------- 3. 创业补贴申请表（故意填错姓名 → 李四） ----------
img, d = canvas(860, 1080, "#ffffff")
d.text((430, 70), "高校毕业生一次性创业补贴申请表", font=font(40), fill="#333333", anchor="mm")
d.text((430, 130), "（演示样本）", font=font(24), fill="#999999", anchor="mm")
rows = [("申 请 人", "李四"), ("性    别", "男"), ("学    历", "本科"),
        ("毕业院校", "某某大学"), ("毕业时间", "2026 年 6 月"),
        ("拟（已）注册企业名称", "苏州星辉科技有限公司"),
        ("注册地", "苏州工业园区"), ("是否首次创业", "是"),
        ("申请补贴类型", "一次性创业补贴"), ("联系电话", "138****0000")]
y = 190
for k, v in rows:
    d.rectangle((80, y, 780, y + 70), outline="#bbbbbb", width=2)
    d.text((100, y + 18), k, font=font(28), fill="#555555")
    d.text((420, y + 18), v, font=font(28), fill="#222222")
    y += 78
d.text((80, y + 20), "申请人签字：李四          日期：2026 年 9 月 1 日", font=font(26), fill="#333333")
watermark(d, 860, 1080)
save(img, "创业补贴申请表_李四.png", "创业补贴申请表",
     {"姓名": "李四", "学历": "本科", "毕业时间": "2026-06", "企业名称": "苏州星辉科技有限公司"})

print("all sample materials generated at:", OUT)
