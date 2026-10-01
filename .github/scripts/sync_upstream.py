#!/usr/bin/env python3
"""Copy entries whose primary link is missing from README.md out of the
upstream README, re-rendered in the format of the matching local section
(table columns or list). Entries that can't be placed are listed in the PR body."""
import pathlib
import re
import urllib.request
from collections import defaultdict

UPSTREAM = "https://raw.githubusercontent.com/meshcore-ita/awesome-meshcore/main/README.md"
README = pathlib.Path("README.md")
IGNORE = pathlib.Path(".upstream-ignore")  # one URL per line

LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^)\s]+)\)")
IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
GH = re.compile(r"^https?://github\.com/([^/\s]+/[^/\s#?]+?)/?$", re.I)
HEAD = re.compile(r"^#{2,4}\s+(.*?)\s*$")


def norm(url):
    return url.strip().rstrip("/").lower()


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "readme-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def sections(lines):
    """heading text -> list of (start, end) ranges (end exclusive)."""
    heads = [(i, HEAD.match(l).group(1)) for i, l in enumerate(lines) if HEAD.match(l)]
    out = defaultdict(list)
    for n, (i, text) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out[text].append((i, end))
    return out


def table_header(lines, start, end):
    for i in range(start + 1, end):
        if lines[i].startswith("|"):
            return cells(lines[i])
    return None


def parse(line, header):
    """Return dict(name, url, desc, closed) or None."""
    if line.startswith("|"):
        cs = cells(line)
        m = LINK.search(cs[0])
        if not m:
            return None
        di = next((i for i, h in enumerate(header or []) if h.lower().startswith("desc")), 1)
        desc = cs[di] if di < len(cs) else ""
        closed = "🔒" in cs[0]
    elif line.startswith("- "):
        m = LINK.search(line)
        if not m:
            return None
        desc = re.sub(r"^\s*[-–—:]\s*", "", IMG.sub("", line[m.end():]).replace("🔒", "").strip())
        closed = "🔒" in line
    else:
        return None
    return {
        "name": m.group(1),
        "url": m.group(2),
        "desc": IMG.sub("", desc).strip(),
        "closed": closed,
    }


def local_format(lines, start, end):
    """Return (kind, header, last_entry_index) or None for a local section."""
    tbl = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if tbl:
        return ("table", cells(lines[tbl[0]]), tbl[-1], len(tbl))
    lst = [i for i in range(start + 1, end) if lines[i].startswith("- ") and LINK.search(lines[i])]
    if lst:
        return ("list", None, lst[-1], len(lst))
    return None


def render(e, kind, header):
    lock = " 🔒" if e["closed"] else ""
    if kind == "list":
        return f"- [{e['name']}]({e['url']}){lock} - {e['desc']}"

    gh = GH.match(e["url"])
    repo = gh.group(1) if gh else None
    out = []
    for i, h in enumerate(header):
        hl = h.lower()
        if i == 0:
            c = f"[{e['name']}]({e['url']})"
            if repo and hl in ("project name", "project"):
                c += f" ![GitHub Repo stars](https://img.shields.io/github/stars/{repo}?style=social)"
            c += lock
        elif hl.startswith("desc"):
            c = e["desc"]
        elif hl.startswith("last"):
            c = f"![GitHub last commit](https://img.shields.io/github/last-commit/{repo})" if repo else ""
        elif hl.startswith("conn"):
            c = "—"
        else:
            c = ""
        out.append(c)
    return "|" + "".join(f" {c} |" if c else " |" for c in out)


def main():
    mine = README.read_text(encoding="utf-8").split("\n")
    theirs = fetch(UPSTREAM).split("\n")

    known = {norm(u) for l in mine for _, u in LINK.findall(l)}
    if IGNORE.exists():
        known |= {norm(l) for l in IGNORE.read_text().splitlines() if l.strip()}

    my_secs = sections(mine)
    their_secs = sections(theirs)

    inserts = defaultdict(list)
    unplaced = []

    for heading, ranges in their_secs.items():
        for start, end in ranges:
            their_header = table_header(theirs, start, end)
            for line in theirs[start + 1:end]:
                e = parse(line, their_header)
                if not e or norm(e["url"]) in known:
                    continue
                known.add(norm(e["url"]))

                best = None
                for s, t in my_secs.get(heading, []):
                    f = local_format(mine, s, t)
                    if f and (best is None or f[3] > best[3]):
                        best = f
                if best is None:
                    unplaced.append((heading, line, "no matching section with entries"))
                    continue
                kind, header, last, _ = best
                inserts[last].append(render(e, kind, header))

    out = []
    for i, l in enumerate(mine):
        out.append(l)
        out.extend(inserts.get(i, []))
    README.write_text("\n".join(out), encoding="utf-8")

    added = sum(len(v) for v in inserts.values())
    body = [f"Added {added} entr{'y' if added == 1 else 'ies'} from {UPSTREAM}.", "",
            "Appended to the end of each section; sort before merging."]
    if unplaced:
        body += ["", "### Not placed", ""]
        body += [f"- **{h}** ({why}): `{l}`" for h, l, why in unplaced]
    pathlib.Path("/tmp/pr_body.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"added={added} unplaced={len(unplaced)}")


if __name__ == "__main__":
    main()
