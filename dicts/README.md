# ё dictionaries

Taken from [eyo-kernel](https://github.com/hcodes/eyo-kernel) (MIT), which in
turn inherits the dictionary of [php-yoficator](https://github.com/rin-nas/php-yoficator).
The files are unchanged, only renamed.

- `yo_safe.txt`: words where the spelling with «е» does not exist as another
  word, so the replacement is unambiguous. 14,645 lines → 106,654 word forms.
- `yo_not_safe.txt`: homographs (`все/всё`, `лет/лёт`, `небо/нёбо`).
  These are never replaced; `adapt_text.py` only flags them.

The two lists do not overlap on their «е» spelling (checked on import).

## Format

One word form per line, spelled with ё. Parentheses list alternative endings:
`Аксён(|а|ам|ами|ах|е|ом|у|ы)` expands to nine forms. `#` starts a comment that
runs to the end of the line. A leading `_` marks a disabled entry, which the
reader skips.

Case matters: a lowercase first letter in the dictionary replaces both `еж` and
`Еж`; an uppercase one replaces only `Еж`.

## Licence

The dictionary files come from eyo-kernel, which is distributed under the MIT
licence. Its notice, as the licence requires:

```
The MIT License (MIT)

Copyright (c) 2026 Denis Seleznev

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
