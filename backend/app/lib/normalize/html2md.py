"""HTML → Markdown。

只用 bs4，不引 markdownify：转换规则要自己可控，
尤其是表格与选项列表——题目里的 A/B/C/D 选项经常是 <ul> 或 <table>，
转错了后面提取全歪。
"""

from bs4 import BeautifulSoup, NavigableString, Tag

_DROP = {"script", "style", "noscript", "template", "iframe", "svg", "canvas"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def _inline(node: Tag) -> str:
    """把一个节点里的行内内容拉平成文本，保留强调与链接。"""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in _DROP:
            continue
        inner = _inline(child)
        if not inner.strip():
            continue
        if name in ("strong", "b"):
            parts.append(f"**{inner.strip()}**")
        elif name in ("em", "i"):
            parts.append(f"*{inner.strip()}*")
        elif name == "code":
            parts.append(f"`{inner.strip()}`")
        elif name == "a":
            href = child.get("href")
            parts.append(f"[{inner.strip()}]({href})" if href else inner.strip())
        elif name == "br":
            parts.append("\n")
        elif name == "img":
            alt = child.get("alt") or ""
            src = child.get("src")
            parts.append(f"![{alt}]({src})" if src else alt)
        else:
            parts.append(inner)
    return "".join(parts)


def _table(tag: Tag) -> str:
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = [
            " ".join(_inline(cell).split()) for cell in tr.find_all(["th", "td"], recursive=False)
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def _list(tag: Tag, ordered: bool, depth: int) -> list[str]:
    lines: list[str] = []
    index = 1
    for li in tag.find_all("li", recursive=False):
        block = _blocks(li, depth + 1)
        head = block[0] if block else ""
        tail = block[1:]
        marker = f"{index}. " if ordered else "- "
        pad = "  " * depth
        lines.append(f"{pad}{marker}{head.strip()}")
        lines.extend(tail)
        index += 1
    return lines


def _blocks(node: Tag, depth: int = 0) -> list[str]:
    out: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = " ".join(str(child).split())
            if text:
                out.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in _DROP:
            continue
        if name in _HEADINGS:
            out.append(f"{'#' * _HEADINGS[name]} {_inline(child).strip()}")
        elif name == "p":
            text = _inline(child).strip()
            if text:
                out.append(text)
        elif name == "table":
            table = _table(child)
            if table:
                out.append(table)
        elif name in ("ul", "ol"):
            out.extend(_list(child, ordered=name == "ol", depth=depth))
        elif name == "pre":
            out.append(f"```\n{child.get_text()}\n```")
        elif name == "blockquote":
            quoted = _blocks(child, depth)
            out.extend(f"> {line}" for line in quoted)
        elif name == "hr":
            out.append("---")
        elif name == "br":
            continue
        else:
            out.extend(_blocks(child, depth))
    return out


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    lines = _blocks(root)
    text = "\n\n".join(line for line in lines if line.strip())
    return _tidy(text)


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    kept: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            blank = 0
            kept.append(line)
        else:
            blank += 1
            if blank <= 1:
                kept.append("")
    return "\n".join(kept).strip()
