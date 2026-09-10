"""Convert LimeSurvey rich text to the plain text stored by SurveyStructure."""

from html.parser import HTMLParser
import re
from typing import Any


class _PlainTextParser(HTMLParser):
    """Collect visible text without executing or preserving HTML markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def plain_text_from_html(value: Any) -> str:
    """Return readable text while dropping markup, scripts, and styles."""
    parser = _PlainTextParser()
    parser.feed("" if value is None else str(value))
    parser.close()
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)
