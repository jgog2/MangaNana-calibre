"""Untrusted provider descriptions → readable plaintext, without metadata edits."""
from html import unescape
from html.parser import HTMLParser
import re


class _Description(HTMLParser):
    blocks={'p','div','section','article','h1','h2','h3','h4','blockquote','ul','ol','table','tr'}
    hidden={'script','style','noscript','iframe','object'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.suppressed=[]

    def handle_starttag(self,tag,attrs):
        if tag in self.hidden:self.suppressed.append(tag)
        if self.suppressed:return
        if tag=='br':self.parts.append('\n')
        elif tag=='li':self.parts.append('\n• ')
        elif tag in self.blocks:self.parts.append('\n\n')

    def handle_endtag(self,tag):
        if self.suppressed:
            if tag in self.suppressed:
                self.suppressed=self.suppressed[:self.suppressed.index(tag)]
            return
        if tag in self.blocks:self.parts.append('\n\n')

    def handle_data(self,text):
        if not self.suppressed:self.parts.append(text)


def normalize_description(value):
    """Keep Unicode, paragraphs and punctuation; never evaluate HTML/Markdown."""
    text=unescape(str(value or '')).replace('\r\n','\n').replace('\r','\n')
    parser=_Description()
    try:
        parser.feed(text);parser.close();text=''.join(parser.parts)
    except (ValueError,AssertionError):
        text=re.sub(r'<[^>]*>','',text)
    text=re.sub(r'(?m)^\s*```[^\n]*\n?|```\s*$','',text)
    text=re.sub(r'!?\[([^\]\n]+)\]\([^\n)]*\)',r'\1',text)
    text=re.sub(r'(?m)^[ \t]{0,3}#{1,6}[ \t]+','',text)
    text=re.sub(r'(?m)^[ \t]*>[ \t]?','',text)
    text=re.sub(r'(\*\*|__|~~)(?=\S)(.+?)(?<=\S)\1',r'\2',text)
    text=re.sub(r'(?<!\w)([*_`])(?=\S)([^\n]+?)(?<=\S)\1(?!\w)',r'\2',text)
    lines=[re.sub(r'[^\S\n]+',' ',line).strip() for line in text.split('\n')]
    return re.sub(r'\n{3,}','\n\n','\n'.join(lines)).strip()
