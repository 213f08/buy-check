"""统计征文正文字数（不含代码块 / 图片行）。"""
import re
from pathlib import Path

text = Path(__file__).resolve().parents[1].joinpath("blog-draft.md").read_text(encoding="utf-8")

no_code = re.sub(r"```.*?```", "", text, flags=re.S)          # 代码块
no_code = re.sub(r"!\[.*?\]\(.*?\)", "", no_code)              # 图片
no_code = re.sub(r"^\|[\s\-|:]+\|$", "", no_code, flags=re.M)  # 表格分隔行
no_code = re.sub(r"^\|.+\|$", "", no_code, flags=re.M)         # 表格行（表格内容多为基础信息，不计入正文字数更保守）

cjk = len(re.findall(r"[\u4e00-\u9fff]", no_code))
print("全文行数:", len(text.splitlines()))
print("正文行数（不含代码/图片/表格）:", len(no_code.splitlines()))
print("正文中文字符数（不含代码/表格）:", cjk)
print("要求 >= 1500 字:", "PASS" if cjk >= 1500 else "FAIL")
