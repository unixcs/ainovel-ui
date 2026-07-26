from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class ChapterItem:
    id: str
    index: int
    title: str
    filename: str
    path: Path
    size: int
    updated_at: str
    character_count: int
    paragraph_count: int


HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
EM_RE = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?", re.MULTILINE)
LIST_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
ORDERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
HR_RE = re.compile(r"^\s*([-*_]\s*){3,}$", re.MULTILINE)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
FILENAME_RE = re.compile(r"^(\d+)[-_]?(.*)$")
TITLE_RE = re.compile(r"^\s*#\s+(.+)$", re.MULTILINE)
CHAPTER_TITLE_LINE_RE = re.compile(r"^(?:第[零〇一二三四五六七八九十百千万两0-9]+[章节回卷篇].*|chapter\s+\d+.*)$", re.IGNORECASE)
SUPPORTED_CHAPTER_SUFFIXES = {".md", ".markdown", ".txt"}


def clean_markdown_text(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    text = FENCE_RE.sub("\n", text)
    text = IMAGE_RE.sub(lambda m: m.group(1) or "", text)
    text = LINK_RE.sub(lambda m: m.group(1), text)
    text = INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = HEADING_RE.sub("", text)
    text = BLOCKQUOTE_RE.sub("", text)
    text = LIST_RE.sub("", text)
    text = ORDERED_LIST_RE.sub("", text)
    text = HR_RE.sub("", text)
    prev = None
    while prev != text:
        prev = text
        text = EM_RE.sub(lambda m: m.group(2), text)
    text = text.replace("\\*", "*").replace("\\_", "_")
    text = MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def chapter_title_from_markdown(markdown: str, fallback: str) -> str:
    match = TITLE_RE.search(markdown)
    if match:
        return clean_markdown_text(match.group(1)).strip() or fallback
    first_line = next((line.strip() for line in markdown.splitlines() if line.strip()), "")
    if first_line and len(first_line) <= 80 and CHAPTER_TITLE_LINE_RE.match(clean_markdown_text(first_line)):
        return clean_markdown_text(first_line) or fallback
    return fallback


def parse_chapter_filename(name: str) -> tuple[int, str]:
    stem = Path(name).stem
    match = FILENAME_RE.match(stem)
    if match:
        idx = int(match.group(1))
        tail = match.group(2).strip("-_ ") or f"第{idx}章"
        return idx, tail
    return 0, stem


def text_metrics(text: str) -> tuple[int, int]:
    compact = re.sub(r"\s+", "", text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return len(compact), len(paragraphs)


def list_chapters(output_root: Path) -> list[ChapterItem]:
    chapters_dir = output_root / "chapters"
    if not chapters_dir.exists():
        return []
    items: list[ChapterItem] = []
    for path in chapters_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_CHAPTER_SUFFIXES:
            continue
        try:
            stat = path.stat()
            markdown = path.read_text(encoding="utf-8", errors="ignore")
        except (FileNotFoundError, OSError):
            # The engine may replace a chapter atomically while the UI is polling.
            continue
        idx, fallback = parse_chapter_filename(path.name)
        title = chapter_title_from_markdown(markdown, fallback)
        characters, paragraphs = text_metrics(clean_markdown_text(markdown))
        items.append(
            ChapterItem(
                id=path.name,
                index=idx,
                title=title,
                filename=path.name,
                path=path,
                size=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                character_count=characters,
                paragraph_count=paragraphs,
            )
        )
    items.sort(key=lambda item: (item.index <= 0, item.index, item.filename))
    return items


def load_chapter_by_id(output_root: Path, chapter_id: str) -> ChapterItem | None:
    for item in list_chapters(output_root):
        if item.id == chapter_id:
            return item
    return None


def render_chapter_txt(item: ChapterItem) -> str:
    markdown = item.path.read_text(encoding="utf-8", errors="ignore")
    cleaned = clean_markdown_text(markdown)
    if cleaned.startswith(item.title):
        return cleaned
    return f"{item.title}\n\n{cleaned}".strip()


def render_all_chapters_txt(output_root: Path, book_title: str) -> str:
    chapters = list_chapters(output_root)
    sections = [book_title.strip()]
    for item in chapters:
        sections.append(render_chapter_txt(item))
    return "\n\n".join(section.strip() for section in sections if section and section.strip()).strip()
