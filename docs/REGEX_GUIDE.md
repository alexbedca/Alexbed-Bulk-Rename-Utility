# RegEx guide

A regular expression (RegEx) is a **pattern** that describes text. The **RegEx Replace** rule finds every part of a file name that matches the pattern and swaps it for **Replace with**. Only the name changes. The extension is left alone unless you change *Apply to*.

In the app, open a RegEx Replace rule and use:

- **Examples**: fills in a ready-made pattern. The preview shows the result immediately.
- **RegEx guide**: this cheat sheet, inside the app.

## How to work

1. Add **RegEx Replace** (Add rule → Text).
2. Type a pattern. In the *Original name* column, each match is highlighted and every captured group gets its own colour.
3. Type the replacement. The *New name* column shows the result:
   - **cyan**: text that will be added
   - **red, struck through**: text that will be removed (shown when another rule is selected)
4. Nothing changes on disk until you press **Rename files**, and every batch can be undone from **History**.

A red pattern box means the pattern has a mistake. The message below it says what's wrong.

## Cheat sheet

### Match characters

| Pattern | Matches |
|---|---|
| `abc` | the exact text abc |
| `.` | any one character |
| `\d` | a digit 0-9 |
| `\s` | a space (or tab) |
| `\w` | a letter, digit or `_` |
| `[abc]` | one of a, b or c |
| `[^abc]` | any character except a, b, c |
| `\.` `\(` `\[` `\-` | a literal `.` `(` `[` `-` (a backslash removes the special meaning) |

### How many

| Pattern | Meaning |
|---|---|
| `+` | one or more of the thing before it: `\d+` matches 7, 42, 2024 |
| `*` | zero or more |
| `?` | optional (zero or one) |
| `{4}` | exactly 4: `\d{4}` matches a year |
| `{2,}` | 2 or more |
| `+?` `*?` | as few as possible (stop at the first match) |

### Where

| Pattern | Meaning |
|---|---|
| `^` | start of the name |
| `$` | end of the name (before the extension) |
| `\b` | a word boundary |

### Capture and reuse

| Pattern | Meaning |
|---|---|
| `( ... )` | capture a part; reuse it as `\1`, `\2` … in Replace with |
| `(?: ... )` | group without capturing |
| `(?P<year>\d{4})` | a named capture; reuse it as `\g<year>` |
| `a\|b` | a or b |

## Worked example

| | |
|---|---|
| Name | `01 - Adele - Hello` |
| Pattern | `^(\d+) - (.+?) - (.+)$` |
| Replace with | `\3 (\2) \1` |
| Result | `Hello (Adele) 01` |

Read the pattern from left to right:

1. `^` is the start of the name.
2. `(\d+)` captures the digits as group 1.
3. ` - ` matches the first dash.
4. `(.+?)` captures as little as possible as group 2 (the artist).
5. ` - ` matches the second dash.
6. `(.+)` captures the rest as group 3 (the title).
7. `$` is the end of the name.

## Recipes

These are also in the **Examples** menu.

| What it does | Before → after | Pattern | Replace with |
|---|---|---|---|
| Remove leading track numbers | `01 - Song` → `Song` | `^\d+\s*[-._]?\s*` | *(nothing)* |
| Put "Track" before the number | `07 Song` → `Track 07 Song` | `^(\d+)` | `Track \1` |
| Swap "Artist - Title" | `Adele - Hello` → `Hello - Adele` | `^(.+?) - (.+)$` | `\2 - \1` |
| Remove text in ( ) or [ ] | `Song (Live) [HD]` → `Song` | `\s*[(\[][^)\]]*[)\]]` | *(nothing)* |
| Spaces to underscores | `My Holiday Photo` → `My_Holiday_Photo` | `\s+` | `_` |
| Squash repeated spaces/underscores | `My__file   name` → `My file name` | `[\s_]{2,}` | a single space |
| Remove " - Copy" and " (2)" endings | `Report - Copy (2)` → `Report` | `(\s*-\s*Copy)?(\s*\(\d+\))?$` | *(nothing)* |
| Date DD-MM-YYYY to YYYY-MM-DD | `Invoice 31-12-2024` → `Invoice 2024-12-31` | `(\d{2})[-.](\d{2})[-.](\d{4})` | `\3-\2-\1` |
| Phone photo name to a readable date | `IMG_20230601_142209` → `2023-06-01 14.22.09` | `^(?:IMG\|VID\|PXL)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\d*` | `\1-\2-\3 \4.\5.\6` |
| Keep only the part after the last " - " | `Artist - Album - Song` → `Song` | `^.* - ` | *(nothing)* |

## Tips

- **Ignore case** is on by default, so `copy` also matches *Copy*.
- You can mix tags into Replace with, for example `<year> \1`.
- `$1` works the same as `\1`, if you know RegEx from elsewhere.
- **Max replacements** limits how many matches are replaced (0 = all).
- If you just want to swap fixed text, plain **Find & Replace** is simpler.
