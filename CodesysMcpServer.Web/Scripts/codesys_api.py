# -*- coding: utf-8 -*-
"""
Facade over the official CODESYS V3 Scripting Engine.

The MCP scripts are written against the API surface requested by the project spec:

    app      = Application()
    project  = app.OpenProject(path)
    project.Pous / project.GVLs / project.DUTs / project.Enums
    pou.GetText() / pou.SetText(...)
    gvl.Variables
    dut.Elements
    enum.Values
    compiler = project.Compiler(); compiler.Compile()
    project.Save()

Those names do not exist in the engine itself. The engine injects the globals
`system`, `projects`, `device_repository`, ... into the script namespace and works with
`projects.open()`, `object.get_children()`, `object.textual_declaration.replace()`,
`create_pou()`, `create_dut()`, `create_gvl()` and so on. This module is the adapter:
the requested surface on the outside, the official API on the inside.

Everything here targets IronPython 2.7 (the interpreter hosted by CODESYS).
"""

from __future__ import print_function

import bisect
import fnmatch
import os
import re
import time

import mcp_io
from mcp_io import log

# Subtrees of the project tree slower than this are logged while scanning.
SLOW_SUBTREE_SECONDS = 2.0


# ===========================================================================
# Engine access
# ===========================================================================

def _builtin_modules():
    modules = []
    try:
        import __builtin__ as b  # IronPython 2.7 / CPython 2
        modules.append(b)
    except ImportError:
        pass
    try:
        import builtins as b3  # CPython 3
        modules.append(b3)
    except ImportError:
        pass
    try:
        import __main__ as m
        modules.append(m)
    except ImportError:
        pass
    try:
        import ScriptEngine as se  # exposed by some CODESYS versions
        modules.append(se)
    except ImportError:
        pass
    return modules


def resolve(name, required=True):
    """Resolve a name injected by the CODESYS Scripting Engine."""
    for module in _builtin_modules():
        value = getattr(module, name, None)
        if value is not None:
            return value

    if required:
        raise RuntimeError(
            "'" + name + "' is not available. This script must be executed by CODESYS "
            "(CODESYS.exe --runscript=...), not by a stand-alone Python interpreter.")
    return None


def _system():
    return resolve("system", required=False)


# ===========================================================================
# Structured Text parsing helpers
# ===========================================================================

class StText(object):
    """
    A block of ST source with a comment-masked twin.

    `masked` has the same length as `raw`, with comments and pragmas replaced by
    spaces and string literals preserved. Structural searches run against `masked`
    so that keywords inside comments never confuse the parser, while offsets stay
    valid for slicing `raw`.
    """

    def __init__(self, raw):
        self.raw = raw or u""
        self.masked, self.comments = _mask(self.raw)
        self._comment_starts = [c[0] for c in self.comments]

    def comment_near(self, start, end):
        """
        Comments belonging to the span [start, end): those written inside it, the
        trailing comment on its last line, and full-line comments directly above it.

        A span begins right after the previous separator, so the trailing comment of
        the *previous* statement also falls inside it. It is excluded by ignoring
        anything still on that first, shared line.
        """
        content_start = start
        while content_start < end and self.masked[content_start].isspace():
            content_start += 1

        shared_line_end = self.raw.find(u"\n", start)
        if shared_line_end < 0:
            shared_line_end = len(self.raw)

        line_end = self.raw.find(u"\n", end)
        if line_end < 0:
            line_end = len(self.raw)

        # Only comments starting in [min(shared_line_end, content_start), line_end]
        # can qualify; comments are sorted by start, so bisect to that window instead
        # of scanning them all (quadratic on large GVLs).
        found = []
        index = bisect.bisect_left(self._comment_starts, min(shared_line_end, content_start))
        while index < len(self.comments):
            c_start, _c_end, text = self.comments[index]
            if c_start > line_end:
                break
            index += 1
            if not text:
                continue
            above = shared_line_end <= c_start < content_start
            inside = content_start <= c_start <= line_end
            if above or inside:
                found.append(text)
        return u" ".join(found).strip()


# Next character that can open a comment, pragma or string literal.
_MASK_SPECIAL_RE = re.compile(r"\(\*|//|[{'\"]")
_BLOCK_COMMENT_TOKEN_RE = re.compile(r"\(\*|\*\)")
_STRING_TOKEN_RE = re.compile(r"[$'\"]")
_NOT_NEWLINE_RE = re.compile(r"[^\r\n]")


def _mask(text):
    """
    Return (masked_text, [(start, end, comment_text), ...]).

    Jumps between special characters with regex searches and copies plain runs
    in one slice. Walking character by character with str.startswith(x, index)
    was quadratic under IronPython (it copies the remaining string on every call)
    and took minutes on large generated GVLs.
    """
    out = []
    comments = []
    index = 0
    length = len(text)

    while index < length:
        match = _MASK_SPECIAL_RE.search(text, index)
        if match is None:
            out.append(text[index:])
            break

        start = match.start()
        if start > index:
            out.append(text[index:start])

        token = match.group(0)

        # Block comment, possibly nested.
        if token == u"(*":
            depth = 1
            index = start + 2
            while depth > 0:
                inner = _BLOCK_COMMENT_TOKEN_RE.search(text, index)
                if inner is None:
                    index = length
                    break
                depth += 1 if inner.group(0) == u"(*" else -1
                index = inner.end()
            comments.append((start, index, text[start + 2:max(start + 2, index - 2)].strip()))
            out.append(_blank(text[start:index]))
            continue

        # Line comment.
        if token == u"//":
            index = text.find(u"\n", start)
            if index < 0:
                index = length
            comments.append((start, index, text[start + 2:index].strip()))
            out.append(_blank(text[start:index]))
            continue

        # Pragma / attribute.
        if token == u"{":
            index = text.find(u"}", start)
            index = length if index < 0 else index + 1
            out.append(_blank(text[start:index]))
            continue

        # String literal - kept verbatim so initial values survive.
        index = start + 1
        while index < length:
            inner = _STRING_TOKEN_RE.search(text, index)
            if inner is None:
                index = length
                break
            if inner.group(0) == u"$":       # ST escape character
                index = inner.start() + 2
                continue
            index = inner.end()
            if inner.group(0) == token:
                break
        index = min(index, length)
        out.append(text[start:index])

    return u"".join(out), comments


def _blank(chunk):
    """Replace a chunk with spaces, preserving newlines and total length."""
    return _NOT_NEWLINE_RE.sub(u" ", chunk)


def _split_statements(st, start, end):
    """Split a masked region into ';'-terminated statements as (text, start, end)."""
    masked = st.masked
    statements = []
    index = start
    current = start

    while index < end:
        char = masked[index]

        # String literals survive masking, so step over them: a ';' inside
        # an initial value such as 'a;b' must not terminate the statement.
        if char == u"'" or char == u'"':
            index += 1
            while index < end:
                if masked[index] == u"$":
                    index += 2
                    continue
                if masked[index] == char:
                    break
                index += 1
            index += 1
            continue

        if char == u";":
            chunk = masked[current:index].strip()
            if chunk:
                statements.append((chunk, current, index))
            current = index + 1
        index += 1

    tail = masked[current:end].strip()
    if tail:
        statements.append((tail, current, end))

    return statements


_VARIABLE_RE = re.compile(
    r"^\s*(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"(?:\s+AT\s+(?P<address>%[^\s:]+))?"
    r"\s*:\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL)


def parse_variables(st, start, end):
    """Parse a VAR-block body into variable dictionaries."""
    variables = []

    for text, span_start, span_end in _split_statements(st, start, end):
        match = _VARIABLE_RE.match(text)
        if not match:
            continue

        rest = match.group("rest").strip()
        initial = None
        assign = rest.find(u":=")
        if assign >= 0:
            initial = rest[assign + 2:].strip() or None
            rest = rest[:assign].strip()

        comment = st.comment_near(span_start, span_end)

        for name in [n.strip() for n in match.group("names").split(u",")]:
            if not name:
                continue
            variables.append({
                "name": name,
                "type": _squash(rest),
                "initialValue": initial,
                "address": match.group("address"),
                "comment": comment or None,
            })

    return variables


_VAR_BLOCK_RE = re.compile(
    r"\bVAR(_GLOBAL|_INPUT|_OUTPUT|_IN_OUT|_TEMP|_STAT|_EXTERNAL|_INST)?\b(?P<qualifiers>[^\n]*)",
    re.IGNORECASE)

_END_VAR_RE = re.compile(r"\bEND_VAR\b", re.IGNORECASE)


def find_var_blocks(st, kinds=None):
    """
    Locate VAR blocks. Returns [(kind, qualifiers, body_start, body_end), ...].
    `kinds` filters on the block keyword, e.g. ["VAR_GLOBAL"].
    """
    blocks = []
    masked = st.masked
    position = 0

    while True:
        match = _VAR_BLOCK_RE.search(masked, position)
        if not match:
            break

        kind = (u"VAR" + (match.group(1) or u"")).upper()
        end_match = _END_VAR_RE.search(masked, match.end())
        if not end_match:
            break

        if kinds is None or kind in kinds:
            blocks.append((
                kind,
                match.group("qualifiers").strip(),
                match.end(),
                end_match.start(),
            ))

        position = end_match.end()

    return blocks


_TYPE_HEADER_RE = re.compile(
    r"\bTYPE\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s+EXTENDS\s+(?P<base>[A-Za-z_][\w.]*))?"
    r"\s*:",
    re.IGNORECASE)

_STRUCT_RE = re.compile(r"\bSTRUCT\b", re.IGNORECASE)
_END_STRUCT_RE = re.compile(r"\bEND_STRUCT\b", re.IGNORECASE)
_UNION_RE = re.compile(r"\bUNION\b", re.IGNORECASE)
_END_UNION_RE = re.compile(r"\bEND_UNION\b", re.IGNORECASE)


def parse_type_declaration(declaration):
    """
    Classify and parse a DUT declaration.

    Returns a dict with: kind (struct|union|enum|alias|unknown), name, baseType,
    elements (struct/union) and values (enum).
    """
    st = StText(declaration)
    header = _TYPE_HEADER_RE.search(st.masked)

    result = {
        "kind": "unknown",
        "name": header.group("name") if header else None,
        "baseType": header.group("base") if header else None,
        "elements": [],
        "values": [],
    }

    body_start = header.end() if header else 0

    struct = _STRUCT_RE.search(st.masked, body_start)
    if struct:
        end = _END_STRUCT_RE.search(st.masked, struct.end())
        result["kind"] = "struct"
        result["elements"] = parse_variables(
            st, struct.end(), end.start() if end else len(st.masked))
        return result

    union = _UNION_RE.search(st.masked, body_start)
    if union:
        end = _END_UNION_RE.search(st.masked, union.end())
        result["kind"] = "union"
        result["elements"] = parse_variables(
            st, union.end(), end.start() if end else len(st.masked))
        return result

    # An enumeration opens its value list directly after the colon. A parenthesis
    # preceded by anything else belongs to an alias such as "TYPE T : STRING(80);".
    open_paren = st.masked.find(u"(", body_start)
    if open_paren >= 0 and not st.masked[body_start:open_paren].strip():
        close_paren = _match_paren(st.masked, open_paren)
        result["kind"] = "enum"
        result["values"] = _parse_enum_values(st, open_paren + 1, close_paren)

        trailer = st.masked[close_paren + 1:]
        base = re.match(r"\s*([A-Za-z_]\w*)", trailer)
        if base and not result["baseType"]:
            result["baseType"] = base.group(1)
        return result

    alias = st.masked[body_start:]
    alias = re.split(r"\bEND_TYPE\b", alias, flags=re.IGNORECASE)[0]
    alias = alias.replace(u";", u" ").strip()
    if alias:
        result["kind"] = "alias"
        result["baseType"] = _squash(alias)

    return result


def _match_paren(text, open_index):
    depth = 0
    index = open_index
    while index < len(text):
        if text[index] == u"(":
            depth += 1
        elif text[index] == u")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text) - 1


def _parse_enum_values(st, start, end):
    values = []
    masked = st.masked
    depth = 0
    current = start
    index = start
    ordinal = 0

    pieces = []
    while index < end:
        char = masked[index]
        if char in u"([":
            depth += 1
        elif char in u")]":
            depth -= 1
        elif char == u"," and depth == 0:
            pieces.append((current, index))
            current = index + 1
        index += 1
    pieces.append((current, end))

    for span_start, span_end in pieces:
        text = masked[span_start:span_end].strip()
        if not text:
            continue

        value = None
        assign = text.find(u":=")
        if assign >= 0:
            value = text[assign + 2:].strip() or None
            text = text[:assign].strip()

        name = text.strip()
        if not re.match(r"^[A-Za-z_]\w*$", name):
            continue

        if value is not None:
            parsed = _try_int(value)
            if parsed is not None:
                ordinal = parsed
        values.append({
            "name": name,
            "value": value,
            "ordinal": ordinal,
            "comment": st.comment_near(span_start, span_end) or None,
        })
        ordinal += 1

    return values


_POU_KIND_RE = re.compile(
    r"\b(FUNCTION_BLOCK|FUNCTION|PROGRAM|INTERFACE|METHOD|PROPERTY|ACTION)\b",
    re.IGNORECASE)


def detect_pou_kind(declaration):
    """PRG / FB / FUN / ... derived from the declaration header."""
    if not declaration:
        return "UNKNOWN"

    match = _POU_KIND_RE.search(_mask(declaration)[0])
    if not match:
        return "UNKNOWN"

    keyword = match.group(1).upper()
    return {
        "PROGRAM": "PRG",
        "FUNCTION_BLOCK": "FB",
        "FUNCTION": "FUN",
        "INTERFACE": "ITF",
        "METHOD": "METHOD",
        "PROPERTY": "PROPERTY",
        "ACTION": "ACTION",
    }.get(keyword, keyword)


def _squash(text):
    return re.sub(r"\s+", u" ", (text or u"")).strip()


def _try_int(text):
    try:
        cleaned = text.strip()
        if cleaned.lower().startswith(u"16#"):
            return int(cleaned[3:], 16)
        return int(cleaned)
    except Exception:
        return None


# ===========================================================================
# Low-level object helpers
# ===========================================================================

def _flag(obj, *names):
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if value is None:
            continue
        try:
            if callable(value):
                value = value()
        except Exception:
            continue
        if isinstance(value, bool):
            return value
    return False


def object_name(obj):
    try:
        return obj.get_name()
    except Exception:
        pass
    try:
        return obj.get_name(False)
    except Exception:
        pass
    return str(getattr(obj, "name", u"<unnamed>"))


def _textual(obj, attribute):
    try:
        part = getattr(obj, attribute)
    except Exception:
        return None
    if part is None:
        return None
    try:
        return part.text
    except Exception:
        return None


def _set_textual(obj, attribute, text):
    part = getattr(obj, attribute, None)
    if part is None:
        raise RuntimeError("Object has no '" + attribute + "' part.")
    part.replace(text if text is not None else u"")


def _children(obj):
    for getter in (lambda: obj.get_children(False), lambda: obj.get_children()):
        try:
            return list(getter())
        except Exception:
            continue
    return []


# Object type GUIDs (ScriptObject.type). The first group was confirmed against
# CODESYS V3.5 SP21; property/transition GUIDs are the documented CODESYS values.
TYPE_FOLDER = u"738bea1e-99bb-4f04-90bb-a7a567e74e3a"
TYPE_ACTION = u"8ac092e5-3128-4e26-9e7e-11016c6684f2"
TYPE_METHOD = u"f8a58466-d7f6-439f-bbb8-d4600e41d099"
TYPE_TASK_CONFIGURATION = u"ae1de277-a207-4a28-9efb-456c06bd52f3"
TYPE_TASK = u"98a2708a-9b18-4f31-82ed-a1465b24fa2d"
TYPE_PROPERTY = u"5a3b8626-d3e9-4f37-98b5-66420063d91e"
TYPE_PROPERTY_ACCESSOR = u"792f2eb6-721e-4e64-ba20-bc98351056db"
TYPE_TRANSITION = u"a10c6218-cb94-436f-91c6-e1652575253d"
# Recipe management (CODESYS Recipes 4.6, confirmed against V3.5 SP21 Patch 3).
TYPE_RECIPE_MANAGER = u"09ecc42e-586d-4a08-932f-5bdcac20bb55"
TYPE_RECIPE_DEFINITION = u"6b3dfb6a-1865-4356-a39b-1fe0ef89651c"

_MEMBER_KINDS = {
    TYPE_ACTION: "ACTION",
    TYPE_METHOD: "METHOD",
    TYPE_PROPERTY: "PROPERTY",
    TYPE_PROPERTY_ACCESSOR: "ACCESSOR",
    TYPE_TRANSITION: "TRANSITION",
}


def object_type(obj):
    """The object's type GUID as a lower-case string, or None when unavailable."""
    try:
        return str(obj.type).lower()
    except Exception:
        return None


def _member_kind(obj, declaration):
    kind = _MEMBER_KINDS.get(object_type(obj))
    if kind:
        return kind
    kind = detect_pou_kind(declaration)
    if kind == "UNKNOWN" and declaration is None and _textual(obj, "textual_implementation") is not None:
        # Actions carry an implementation but no declaration of their own.
        return "ACTION"
    return kind


# ===========================================================================
# Object wrappers
# ===========================================================================

class ScriptObjectWrapper(object):
    """Common behaviour for every project object wrapper."""

    def __init__(self, obj, path):
        self.Object = obj
        self.Name = object_name(obj)
        self.Path = path              # e.g. "Application/Logic/Main"
        self.ParentPath = path.rsplit(u"/", 1)[0] if u"/" in path else u""

    # -- text ------------------------------------------------------------
    def GetDeclaration(self):
        return _textual(self.Object, "textual_declaration")

    def GetImplementation(self):
        return _textual(self.Object, "textual_implementation")

    def GetText(self):
        """Full source of the object: declaration, implementation and both combined."""
        declaration = self.GetDeclaration()
        implementation = self.GetImplementation()

        combined = u""
        if declaration:
            combined += declaration
        if implementation:
            if combined and not combined.endswith(u"\n"):
                combined += u"\n"
            combined += implementation

        return {
            "declaration": declaration,
            "implementation": implementation,
            "text": combined or None,
        }

    def SetText(self, implementation=None, declaration=None):
        """Replace the implementation and, when supplied, the declaration."""
        changed = []
        if declaration is not None:
            _set_textual(self.Object, "textual_declaration", declaration)
            changed.append("declaration")
        if implementation is not None:
            _set_textual(self.Object, "textual_implementation", implementation)
            changed.append("implementation")
        return changed

    def Summary(self):
        return {"name": self.Name, "path": self.Path}


class Pou(ScriptObjectWrapper):
    """A POU (PRG / FB / FUN) plus its methods, actions and properties."""

    def __init__(self, obj, path):
        ScriptObjectWrapper.__init__(self, obj, path)
        self._declaration = self.GetDeclaration()
        self.Type = detect_pou_kind(self._declaration)
        self.Language = self._language()
        self._members = None

    def _language(self):
        for attribute in ("language", "implementation_language"):
            try:
                value = getattr(self.Object, attribute)
            except Exception:
                continue
            if value is None:
                continue
            text = _squash(str(value))
            if text:
                return _normalize_language_name(text)

        # No language property in this engine version: infer from the object shape.
        if self.GetImplementation() is not None:
            return "ST"
        return "UNKNOWN"

    def MemberObjects(self):
        """Methods, actions, properties, ... - including those kept in sub-folders."""
        if self._members is None:
            self._members = []
            self._collect_members(self.Object, None)
        return self._members

    def _collect_members(self, parent, folder):
        for child in _children(parent):
            if object_type(child) == TYPE_FOLDER or _flag(child, "is_folder"):
                name = object_name(child)
                self._collect_members(child, name if not folder else folder + u"/" + name)
                continue
            self._members.append(PouMember(child, self, folder))

    def Members(self):
        return [m.Summary() for m in self.MemberObjects()]

    def FindMember(self, chain):
        """Resolve "Member" or "Member.Nested" (e.g. "Prop.Get") below this POU."""
        head, _, rest = chain.partition(u".")
        lowered = head.strip().lower()
        members = self.MemberObjects()

        found = None
        for member in members:
            if member.Name == head:
                found = member
                break
        if found is None:
            for member in members:
                if member.Name.lower() == lowered:
                    found = member
                    break
        if found is None:
            available = u", ".join(sorted([m.Name for m in members])) or u"<none>"
            raise LookupError(
                "'" + self.Name + "' has no member '" + head + "'. Available: " + available)

        return found.FindMember(rest) if rest else found

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "type": self.Type,
            "language": self.Language,
            "members": self.Members(),
        }

    def Content(self):
        content = self.GetText()
        content.update({
            "name": self.Name,
            "path": self.Path,
            "type": self.Type,
            "language": self.Language,
            "members": self.Members(),
        })
        return content


class PouMember(Pou):
    """A method / action / property / transition of a POU, addressed as "Parent.Member"."""

    def __init__(self, obj, owner, folder=None):
        Pou.__init__(self, obj, owner.Path + u"." + object_name(obj))
        self.Owner = owner
        self.Folder = folder
        self.Type = _member_kind(obj, self._declaration)

    def Summary(self):
        summary = {"name": self.Name, "kind": self.Type}
        if self.Folder:
            summary["folder"] = self.Folder
        return summary

    def Content(self):
        content = Pou.Content(self)
        content["kind"] = self.Type
        content["parent"] = self.Owner.Path
        content["folder"] = self.Folder
        return content


class Gvl(ScriptObjectWrapper):
    """A global variable list."""

    @property
    def Variables(self):
        st = StText(self.GetDeclaration() or u"")
        variables = []
        for kind, qualifiers, start, end in find_var_blocks(st):
            for variable in parse_variables(st, start, end):
                variable["block"] = kind
                variable["qualifiers"] = qualifiers or None
                variables.append(variable)
        return variables

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "variableCount": len(self.Variables),
        }

    def Content(self, name_filter=None):
        if not name_filter:
            return {
                "name": self.Name,
                "path": self.Path,
                "declaration": self.GetDeclaration(),
                "variables": self.Variables,
            }

        # Filtered reads exist for very large lists, so the full declaration is left out.
        variables = self.Variables
        matches = name_matcher(name_filter)
        selected = [v for v in variables if matches(v["name"])]
        return {
            "name": self.Name,
            "path": self.Path,
            "filter": name_filter,
            "totalVariableCount": len(variables),
            "matchedVariableCount": len(selected),
            "variables": selected,
        }


def name_matcher(pattern):
    """
    Case-insensitive name predicate: a wildcard pattern ("*Fault*", "x?Run") when the
    pattern contains * or ?, otherwise a plain substring match.
    """
    text = (pattern or u"").strip().lower()
    if u"*" in text or u"?" in text:
        regex = re.compile(fnmatch.translate(text))
        return lambda name: regex.match((name or u"").lower()) is not None
    return lambda name: text in (name or u"").lower()


class Dut(ScriptObjectWrapper):
    """A structure / union / alias data type."""

    def __init__(self, obj, path, parsed=None):
        ScriptObjectWrapper.__init__(self, obj, path)
        self._parsed = parsed if parsed is not None else parse_type_declaration(self.GetDeclaration())

    @property
    def Kind(self):
        return self._parsed.get("kind")

    @property
    def BaseType(self):
        return self._parsed.get("baseType")

    @property
    def Elements(self):
        return self._parsed.get("elements") or []

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "kind": self.Kind,
            "baseType": self.BaseType,
            "fieldCount": len(self.Elements),
            "fields": self.Elements,
        }

    def Content(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "kind": self.Kind,
            "baseType": self.BaseType,
            "declaration": self.GetDeclaration(),
            "fields": self.Elements,
        }


class Enum(ScriptObjectWrapper):
    """An enumeration DUT."""

    def __init__(self, obj, path, parsed=None):
        ScriptObjectWrapper.__init__(self, obj, path)
        self._parsed = parsed if parsed is not None else parse_type_declaration(self.GetDeclaration())

    @property
    def BaseType(self):
        return self._parsed.get("baseType")

    @property
    def Values(self):
        return self._parsed.get("values") or []

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "baseType": self.BaseType,
            "valueCount": len(self.Values),
            "values": self.Values,
        }

    def Content(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "baseType": self.BaseType,
            "declaration": self.GetDeclaration(),
            "values": self.Values,
        }


# ===========================================================================
# Recipes
# ===========================================================================
#
# The engine's recipe driver (ScriptDriverRecipe) extends ScriptObjects:
#   application.has_recipemanager / application.get_recipemanager()
#   manager.is_recipemanager, its settings, manager.create_recipedefinition(name)
#   definition.is_recipedefinition, definition.variables (add / remove / [i] / len),
#   definition.recipes (create / remove / [i] / len)
#   variable.variablename / type (read-only), name / comment / min_value / max_value
#   recipe.recipename, get_value(variable) / set_value(variable, text), get_value_at(i)
# Values are always strings. The engine does not check them against min/max (the runtime
# limits or skips them on load, as the manager's write mode says), so that is only warned about.

DEFAULT_RECIPE_PAGE = 500
MAX_RECIPE_PAGE = 5000
_RECIPE_INVALID_TYPE = u"<Invalid Type>"


def _enum_name(value):
    """'...LoadRecipeMode.load_by_variablename' -> 'load_by_variablename'."""
    if value is None:
        return None
    return str(value).rsplit(u".", 1)[-1]


def _text_or_none(value):
    if value is None:
        return None
    text = u"%s" % value
    return text if text != u"" else None


def _to_float(text):
    try:
        return float((text or u"").strip())
    except (TypeError, ValueError):
        return None


def recipe_limit_warning(variable, value, min_value, max_value):
    """A warning when a numeric value lies outside the variable's numeric min/max, else None."""
    number = _to_float(value)
    if number is None:
        return None
    low, high = _to_float(min_value), _to_float(max_value)
    if low is not None and number < low:
        return u"%s = %s is below its minimum %s." % (variable, value, min_value)
    if high is not None and number > high:
        return u"%s = %s is above its maximum %s." % (variable, value, max_value)
    return None


def _same_name(left, right):
    return (left or u"").strip().lower() == (right or u"").strip().lower()


class RecipeManager(object):
    """A Recipe Manager object: its settings and the recipe definitions below it."""

    def __init__(self, obj, path):
        self.Object = obj
        self.Name = object_name(obj)
        self.Path = path
        self.Application = path.rsplit(u"/", 1)[0] if u"/" in path else u""
        self.Definitions = []

    def Settings(self):
        obj = self.Object

        def read(name, convert=None):
            try:
                value = getattr(obj, name)
            except Exception as ex:
                log("Recipe manager '%s': could not read %s: %s" % (self.Path, name, mcp_io._describe(ex)))
                return None
            return convert(value) if convert is not None else value

        return {
            "recipeManagementInPlc": read("recipe_mgmt_in_plc"),
            "saveToFileAutomatically": read("save_to_file_automatically"),
            "overwriteRecipesOnDownload": read("overwrite_recipes_on_download"),
            "saveChangedRecipesOnly": read("save_changed_recipes_only"),
            "loadRecipeMode": read("load_recipe_mode", _enum_name),
            "writeRecipeMode": read("write_recipe_mode", _enum_name),
            "storageType": read("storage_type", _enum_name),
            "storageFilePath": read("storage_file_path", _text_or_none),
            "storageFileExtension": read("storage_file_extension", _text_or_none),
            "storageSeparator": read("storage_separator", _enum_name),
            "storageColumns": read("storage_columns", lambda columns: [_enum_name(c) for c in columns]),
        }

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "application": self.Application,
            "settings": self.Settings(),
            "definitions": [d.Summary() for d in self.Definitions],
        }


class RecipeDefinition(object):
    """A recipe definition: a table of variables (rows) and recipes (value columns)."""

    def __init__(self, obj, path, manager):
        self.Object = obj
        self.Name = object_name(obj)
        self.Path = path
        self.Manager = manager

    # -- reading ---------------------------------------------------------
    def _variable_handles(self):
        return list(self.Object.variables)

    def _recipe_handles(self):
        return list(self.Object.recipes)

    def RecipeNames(self):
        return [r.recipename for r in self._recipe_handles()]

    def Summary(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "recipeManager": self.Manager.Path,
            "application": self.Manager.Application,
            "variableCount": len(self.Object.variables),
            "recipeCount": len(self.Object.recipes),
            "recipes": self.RecipeNames(),
        }

    @staticmethod
    def _variable_info(index, handle):
        return {
            "index": index,
            "variable": handle.variablename,
            "type": _text_or_none(handle.type),
            "name": _text_or_none(handle.name),
            "comment": _text_or_none(handle.comment),
            "minValue": _text_or_none(handle.min_value),
            "maxValue": _text_or_none(handle.max_value),
        }

    def _select_recipes(self, recipe):
        recipes = self._recipe_handles()
        if not recipe:
            return recipes
        for handle in recipes:
            if _same_name(handle.recipename, recipe):
                return [handle]
        raise LookupError(
            "Recipe '" + recipe + "' was not found in recipe definition '" + self.Path + "'. Available: "
            + (u", ".join(r.recipename for r in recipes) or u"<none>"))

    def Content(self, name_filter=None, recipe=None, offset=0, limit=DEFAULT_RECIPE_PAGE):
        """
        Variables (rows) of the definition with their value in each recipe, one page at a time:
        definitions can hold tens of thousands of variables. name_filter matches the variable
        expression or its display name; recipe limits the values to one recipe.
        """
        offset = max(0, int(offset or 0))
        limit = int(limit or DEFAULT_RECIPE_PAGE)
        recipes = self._select_recipes(recipe)
        handles = self._variable_handles()

        if name_filter:
            matches = name_matcher(name_filter)
            selected = []
            for index, handle in enumerate(handles):
                # The display name is only read when the expression does not match already.
                if matches(handle.variablename) or matches(handle.name):
                    selected.append(index)
        else:
            selected = list(range(len(handles)))

        page = selected[offset:offset + limit]
        variables = []
        for index in page:
            info = self._variable_info(index, handles[index])
            if recipes:
                info["values"] = dict((r.recipename, r.get_value_at(index)) for r in recipes)
            variables.append(info)

        next_offset = offset + len(page)
        return {
            "name": self.Name,
            "path": self.Path,
            "recipeManager": self.Manager.Path,
            "application": self.Manager.Application,
            "recipes": [r.recipename for r in recipes] if recipe else self.RecipeNames(),
            "filter": name_filter or None,
            "totalVariableCount": len(handles),
            "matchedVariableCount": len(selected),
            "offset": offset,
            "returnedVariableCount": len(variables),
            "truncated": next_offset < len(selected),
            "nextOffset": next_offset if next_offset < len(selected) else None,
            "variables": variables,
        }

    # -- writing ---------------------------------------------------------
    def Apply(self, variables=None, remove_variables=None, recipes=None, remove_recipes=None):
        """
        Applies one batch of changes, in this order: remove recipes, remove variables,
        add/update variables, create/update recipes. Every name is checked before anything
        changes, so a bad request leaves the definition untouched.
        """
        variables = variables or []
        remove_variables = remove_variables or []
        recipes = recipes or []
        remove_recipes = remove_recipes or []

        handles = self._variable_handles()
        by_name = {}
        for index, handle in enumerate(handles):
            by_name[handle.variablename.strip().lower()] = handle.variablename
        recipe_names = dict((r.recipename.strip().lower(), r.recipename) for r in self._recipe_handles())

        # -- validate everything up front --
        def key(text):
            return (text or u"").strip().lower()

        missing = [v for v in remove_variables if key(v) not in by_name]
        if missing:
            raise LookupError("Variable(s) to remove are not in recipe definition '%s': %s"
                              % (self.Path, u", ".join(missing)))
        missing = [r for r in remove_recipes if key(r) not in recipe_names]
        if missing:
            raise LookupError("Recipe(s) to remove are not in recipe definition '%s': %s. Available: %s"
                              % (self.Path, u", ".join(missing), u", ".join(recipe_names.values()) or u"<none>"))

        removed = set(key(v) for v in remove_variables)
        known = set(k for k in by_name if k not in removed)
        for change in variables:
            if not (change.get("variable") or u"").strip():
                raise ValueError("Every variable needs a 'variable' expression, e.g. 'GVL_Recipe.rSpeed'.")
            known.add(key(change["variable"]))
        for recipe in recipes:
            if not (recipe.get("name") or u"").strip():
                raise ValueError("Every recipe needs a name.")
            unknown = [v for v in (recipe.get("values") or {}) if key(v) not in known]
            if unknown:
                raise LookupError(
                    "Recipe '%s' sets values of variables that are not in recipe definition '%s': %s. "
                    "Add them under variables first." % (recipe["name"], self.Path, u", ".join(unknown)))

        changes = {
            "recipesRemoved": [], "variablesRemoved": [], "variablesAdded": [],
            "variablesUpdated": [], "recipesCreated": [], "recipesUpdated": [],
        }
        warnings = []
        recipe_list = self.Object.recipes
        variable_list = self.Object.variables

        # -- apply --
        for name in remove_recipes:
            actual = recipe_names.pop(key(name))
            recipe_list.remove(actual)
            changes["recipesRemoved"].append(actual)

        for name in remove_variables:
            actual = by_name.pop(key(name))
            variable_list.remove(actual)
            changes["variablesRemoved"].append(actual)

        if remove_variables:
            handles = self._variable_handles()
        index_of = dict((h.variablename.strip().lower(), i) for i, h in enumerate(handles))

        for change in variables:
            expression = change["variable"].strip()
            existing = index_of.get(key(expression))
            if existing is None:
                handle = variable_list.add(expression)
                index_of[key(expression)] = len(handles)
                handles.append(handle)
                changes["variablesAdded"].append(expression)
                if (handle.type or u"") == _RECIPE_INVALID_TYPE:
                    warnings.append(
                        u"The type of '%s' could not be resolved: check that it is a full path to a "
                        u"global variable (e.g. GVL.x or PLC_PRG.x) and compile." % expression)
            else:
                handle = handles[existing]
                expression = handle.variablename

            updated = False
            for field, attribute in (("name", "name"), ("comment", "comment"),
                                     ("minValue", "min_value"), ("maxValue", "max_value")):
                value = change.get(field)
                if value is not None:
                    setattr(handle, attribute, value)
                    updated = True
            if updated and existing is not None:
                changes["variablesUpdated"].append(expression)

        for recipe in recipes:
            name = recipe["name"].strip()
            values = recipe.get("values") or {}
            actual = recipe_names.get(key(name))
            if actual is None:
                handle = recipe_list.create(name)
                recipe_names[key(name)] = name
                changes["recipesCreated"].append({"name": name, "valuesSet": len(values)})
            else:
                handle = None
                for candidate in self._recipe_handles():
                    if candidate.recipename == actual:
                        handle = candidate
                        break
                name = actual
                changes["recipesUpdated"].append({"name": name, "valuesSet": len(values)})

            for variable, value in sorted(values.items()):
                variable_handle = handles[index_of[key(variable)]]
                expression = variable_handle.variablename
                text = u"" if value is None else (u"%s" % value)
                handle.set_value(expression, text)
                warning = recipe_limit_warning(
                    expression, text, variable_handle.min_value, variable_handle.max_value)
                if warning:
                    warnings.append(u"Recipe '%s': %s" % (name, warning))

        return changes, warnings


# ===========================================================================
# Compiler
# ===========================================================================

class Compiler(object):
    """Wraps code generation / build for every application in the project."""

    def __init__(self, project):
        self._project = project

    def Compile(self, clean=False):
        project = self._project.Object
        applications = self._project.Applications()

        results = []
        succeeded = True

        if clean:
            self._invoke(project, ("clean_all", "clean"), results, "clean", None)

        if not applications:
            log("No application object found; generating code at project level.")
            ok = self._invoke(
                project,
                ("generate_code", "build", "check_all_pool_objects"),
                results, "project", None)
            succeeded = succeeded and ok
        else:
            for application, path in applications:
                log("Generating code for application '" + path + "'")
                ok = self._invoke(
                    application,
                    ("generate_code", "build", "check"),
                    results, "application", path)
                succeeded = succeeded and ok

        messages, messages_available = _collect_messages()
        errors = [m for m in messages if m.get("severity") == "error"]
        warnings = [m for m in messages if m.get("severity") == "warning"]

        if errors:
            succeeded = False

        return {
            "success": succeeded,
            "steps": results,
            "errorCount": len(errors),
            "warningCount": len(warnings),
            "messages": messages,
            "messagesAvailable": messages_available,
        }

    def _invoke(self, target, candidates, results, scope, path):
        for name in candidates:
            method = getattr(target, name, None)
            if method is None or not callable(method):
                continue

            try:
                method()
                results.append({
                    "scope": scope,
                    "target": path,
                    "operation": name,
                    "success": True,
                    "message": None,
                })
                return True
            except Exception as ex:
                results.append({
                    "scope": scope,
                    "target": path,
                    "operation": name,
                    "success": False,
                    "message": type(ex).__name__ + ": " + str(ex),
                })
                return False

        results.append({
            "scope": scope,
            "target": path,
            "operation": "/".join(candidates),
            "success": False,
            "message": "None of these methods exist on this CODESYS version.",
        })
        return False


def _collect_messages():
    """
    Read the CODESYS message store.

    The accessor differs between engine versions (and is absent in some), so several
    candidates are tried. When none is available the caller still gets a verdict from
    the build call itself; `messagesAvailable` says whether the list is authoritative.
    """
    system = _system()
    if system is None:
        return [], False

    # Compiler output lives in its own message category ("Build"). The category-less
    # accessors only return the default (script output) category, i.e. our own
    # "[mcp]" log lines, so read every category explicitly when the engine allows it.
    by_category = _collect_messages_by_category(system)
    if by_category is not None:
        return by_category, True

    store = None
    for name in ("message_store", "messagestore", "messages"):
        store = getattr(system, name, None)
        if store is not None:
            break

    if store is None:
        for name in ("get_message_store", "get_messages", "get_message_objects"):
            getter = getattr(system, name, None)
            if callable(getter):
                try:
                    store = getter()
                    break
                except Exception:
                    store = None

    if store is None:
        return [], False

    raw = store
    for name in ("messages", "get_messages", "all_messages"):
        candidate = getattr(store, name, None)
        if candidate is None:
            continue
        try:
            raw = candidate() if callable(candidate) else candidate
            break
        except Exception:
            continue

    messages = []
    try:
        for item in raw:
            message = {
                "severity": _severity(item),
                "text": _squash(str(getattr(item, "text", item))),
                "object": _optional_str(item, "object_name", "objectname", "object"),
            }
            message.update(_message_location(item))
            messages.append(message)
    except Exception:
        return messages, len(messages) > 0

    return messages, True


def _collect_messages_by_category(system):
    """
    Messages of every category, read with get_message_objects(category) (or
    get_messages(category) on engines without message objects). Returns None when the
    engine cannot enumerate categories, so the caller falls back to the older accessors.
    Our own "[mcp]" progress lines are dropped: they are not compiler output.
    """
    lister = getattr(system, "get_message_categories", None)
    if not callable(lister):
        return None

    try:
        categories = list(lister())
    except Exception:
        try:
            categories = list(lister(False))
        except Exception:
            return None

    readers = [getattr(system, name, None) for name in ("get_message_objects", "get_messages")]
    readers = [reader for reader in readers if callable(reader)]
    if not readers:
        return None

    messages = []
    read_any = False
    for category in categories:
        items = None
        for reader in readers:
            try:
                items = list(reader(category))
                break
            except Exception:
                items = None
        if items is None:
            continue

        read_any = True
        for item in items:
            text = _squash(str(getattr(item, "text", item)))
            if text.startswith("[mcp]"):
                continue
            code = _message_code(item)
            message = {
                "severity": _severity(item),
                "text": (code + ": " + text) if code else text,
                "object": _message_object_name(item),
            }
            message.update(_message_location(item))
            messages.append(message)

    return messages if read_any else None


# "Line 2, Column 1 (Impl)" or "Line 8 (Decl)" - how a message object describes its position.
_POSITION_TEXT_RE = re.compile(r"Line\s+(\d+)(?:\s*,\s*Column\s+(\d+))?(?:\s*\((\w+)\))?", re.IGNORECASE)


def parse_message_position(position_text, position_offset=None):
    """
    Line, column and section from a message's position_text ("Line 2, Column 1 (Impl)", or
    "Line 8 (Decl)" without a column). CODESYS reports the column where the statement starts
    (1 when it gives none) and the character offset from there in position_offset, so the
    column of the flagged token is the sum. Line and column are 1-based; section is
    "implementation", "declaration" or null.
    """
    match = _POSITION_TEXT_RE.search(position_text or u"")
    if match is None:
        return None
    column = int(match.group(2) or 1) + (_try_int(position_offset) or 0)
    part = (match.group(3) or u"").lower()
    section = None
    if part.startswith("impl"):
        section = u"implementation"
    elif part.startswith("decl"):
        section = u"declaration"
    return {"line": int(match.group(1)), "column": column, "section": section}


def _message_location(item):
    """
    Where a message points: line, column, section and length when the engine provides
    a position text, plus the raw (engine-internal) position. Missing parts are null.
    """
    location = {
        "line": None,
        "column": None,
        "section": None,
        "length": _try_int(_optional_str(item, "length")),
        "position": _optional_str(item, "position", "line"),
    }
    parsed = parse_message_position(
        _optional_str(item, "position_text"), _optional_str(item, "position_offset"))
    if parsed is not None:
        location.update(parsed)
    return location


def _message_object_name(item):
    """Name of the object a message points at (message objects carry a ScriptObject)."""
    value = getattr(item, "object", None)
    if value is not None and not isinstance(value, (str, type(u""))):
        try:
            name = object_name(value)
            if name:
                return _squash(name)
        except Exception:
            pass
    return _optional_str(item, "object_name", "objectname", "object")


def _message_code(item):
    """Compiler message code such as "C0035", from the message's prefix and number."""
    prefix = getattr(item, "prefix", None)
    number = getattr(item, "number", None)
    if not prefix or number is None:
        return None
    try:
        return "%s%04d" % (prefix, int(number))
    except Exception:
        return None


def _severity(item):
    value = getattr(item, "severity", None)
    text = str(value).lower() if value is not None else u""
    if "error" in text or "exception" in text:
        return "error"
    if "warning" in text:
        return "warning"
    if text:
        return "information"
    return "information"


def _optional_str(item, *names):
    for name in names:
        value = getattr(item, name, None)
        if value is None:
            continue
        try:
            if callable(value):
                value = value()
        except Exception:
            continue
        text = _squash(str(value))
        if text:
            return text
    return None


# ===========================================================================
# Project
# ===========================================================================

class Project(object):
    """
    Wraps a ScriptProject and exposes the object collections requested by the spec.
    Collections are scanned lazily once and then cached for the lifetime of the script.
    """

    def __init__(self, script_project, path):
        self.Object = script_project
        self.Path = path
        self._scanned = False
        self._pous = []
        self._gvls = []
        self._duts = []
        self._enums = []
        self._applications = []
        self._folders = []
        self._task_configurations = []
        self._recipe_managers = []
        self._other = []

    # -- scanning --------------------------------------------------------
    def _scan(self):
        if self._scanned:
            return

        started = time.time()
        self._walk(self.Object, u"")
        self._scanned = True
        log("Scanned project in %.1fs: %d POU(s), %d GVL(s), %d DUT(s), %d ENUM(s)"
            % (time.time() - started, len(self._pous), len(self._gvls), len(self._duts), len(self._enums)))

    def _walk(self, parent, prefix):
        for child in _children(parent):
            started = time.time()
            self._visit(child, prefix)
            elapsed = time.time() - started
            if elapsed >= SLOW_SUBTREE_SECONDS:
                log("  slow subtree: %s (%.1fs)" % (
                    (prefix + u"/" if prefix else u"") + object_name(child), elapsed))

    def _visit(self, child, prefix):
        name = object_name(child)
        path = name if not prefix else prefix + u"/" + name

        if _flag(child, "is_folder"):
            self._folders.append(path)
            self._walk(child, path)
            return

        if _flag(child, "is_application"):
            self._applications.append((child, path))
            self._walk(child, path)
            return

        if object_type(child) == TYPE_TASK_CONFIGURATION:
            self._task_configurations.append((child, path))
            return

        if object_type(child) == TYPE_RECIPE_MANAGER or _flag(child, "is_recipemanager"):
            manager = RecipeManager(child, path)
            for definition in _children(child):
                if object_type(definition) == TYPE_RECIPE_DEFINITION or _flag(definition, "is_recipedefinition"):
                    manager.Definitions.append(
                        RecipeDefinition(definition, path + u"/" + object_name(definition), manager))
            self._recipe_managers.append(manager)
            return

        # This engine version exposes no is_pou / is_dut / is_gvl flags (confirmed:
        # every ScriptObject only has is_folder and is_application; everything else
        # comes back "<missing>"). The only reliable, version-tolerant signal left is
        # the textual declaration itself, so classify by parsing its header instead -
        # a "TYPE Name :" header means DUT/ENUM, a PROGRAM/FUNCTION_BLOCK/FUNCTION/
        # INTERFACE header means POU, and a bare VAR_GLOBAL block (no header at all,
        # constant/persistent/retain qualifiers included) means GVL.
        declaration = _textual(child, "textual_declaration")
        if declaration is not None:
            masked = _mask(declaration)[0]

            if _TYPE_HEADER_RE.search(masked):
                parsed = parse_type_declaration(declaration)
                if parsed.get("kind") == "enum":
                    self._enums.append(Enum(child, path, parsed))
                else:
                    self._duts.append(Dut(child, path, parsed))
                return

            if _POU_KIND_RE.search(masked):
                self._pous.append(Pou(child, path))
                return

            self._gvls.append(Gvl(child, path))
            return

        # Devices, task configurations, library managers, visualizations, ...
        self._other.append(path)
        self._walk(child, path)

    # -- collections -----------------------------------------------------
    @property
    def Pous(self):
        self._scan()
        return self._pous

    @property
    def GVLs(self):
        self._scan()
        return self._gvls

    @property
    def DUTs(self):
        self._scan()
        return self._duts

    @property
    def Enums(self):
        self._scan()
        return self._enums

    def Applications(self):
        self._scan()
        return self._applications

    def Folders(self):
        self._scan()
        return self._folders

    def RecipeManagers(self):
        self._scan()
        return self._recipe_managers

    def RecipeDefinitions(self):
        return [d for m in self.RecipeManagers() for d in m.Definitions]

    # -- lookup ----------------------------------------------------------
    def Find(self, collection, name):
        """Find by exact name, full path, or case-insensitive name."""
        lowered = (name or u"").strip().lower()

        for item in collection:
            if item.Name == name or item.Path == name:
                return item
        for item in collection:
            if item.Name.lower() == lowered or item.Path.lower() == lowered:
                return item
        return None

    def FindOrFail(self, collection, name, kind):
        found = self.Find(collection, name)
        if found is None:
            available = u", ".join(sorted([i.Name for i in collection])) or u"<none>"
            raise LookupError(
                kind + " '" + str(name) + "' was not found in the project. Available: " + available)
        return found

    def FindPou(self, name):
        """A POU, or one of its members addressed as "Parent.Member" (e.g. "FB_Motor.Reset")."""
        found = self.Find(self.Pous, name)
        if found is not None:
            return found

        # Folder names may contain dots, so try every dot as the POU/member boundary.
        text = (name or u"").strip()
        index = text.find(u".")
        while index > 0:
            owner = self.Find(self.Pous, text[:index])
            if owner is not None:
                return owner.FindMember(text[index + 1:])
            index = text.find(u".", index + 1)

        return self.FindOrFail(self.Pous, name, "POU")

    def FindGvl(self, name):
        return self.FindOrFail(self.GVLs, name, "GVL")

    def FindDut(self, name):
        return self.FindOrFail(self.DUTs, name, "DUT")

    def FindEnum(self, name):
        return self.FindOrFail(self.Enums, name, "ENUM")

    def ResolveParent(self, parent_path):
        """Resolve a project-relative folder path; returns the project itself when empty."""
        if not parent_path:
            return self.Object

        current = self.Object
        for part in [p for p in re.split(r"[\\/]+", parent_path) if p]:
            found = None
            for child in _children(current):
                if object_name(child).lower() == part.lower():
                    found = child
                    break
            if found is None:
                raise LookupError("Folder '" + parent_path + "' was not found (missing part: '" + part + "').")
            current = found
        return current

    # -- kind / library information -------------------------------------
    @property
    def IsLibrary(self):
        """True when the open file is a source library (.library) rather than a .project."""
        return is_library_path(self.Path)

    @property
    def Kind(self):
        return u"library" if self.IsLibrary else u"project"

    def LibraryInfo(self):
        """
        Title, version, company, namespace, ... from the library's Project Information, or None
        for a .project. Every field is read defensively: which ones exist depends on the engine
        version, and a missing one is reported as null.
        """
        if not self.IsLibrary:
            return None

        info = None
        for getter in ("get_project_info", "project_info"):
            candidate = getattr(self.Object, getter, None)
            try:
                info = candidate() if callable(candidate) else candidate
            except Exception as ex:
                log("Could not read the library's project information: " + mcp_io._describe(ex))
                info = None
            if info is not None:
                break

        def read(*names):
            if info is None:
                return None
            for name in names:
                try:
                    value = getattr(info, name, None)
                except Exception:
                    value = None
                if value is not None and not callable(value):
                    text = _text_or_none(value)
                    if text:
                        return text
            return None

        return {
            "title": read("title"),
            "version": read("version"),
            "company": read("company"),
            "defaultNamespace": read("default_namespace", "defaultnamespace"),
            "author": read("author"),
            "description": read("description"),
            "category": read("library_category", "library_categories"),
            "placeholder": read("placeholder"),
        }

    # -- structure -------------------------------------------------------
    def Structure(self):
        return {
            "projectPath": self.Path,
            "kind": self.Kind,
            "libraryInfo": self.LibraryInfo(),
            "pous": [p.Summary() for p in self.Pous],
            "gvls": [g.Summary() for g in self.GVLs],
            "duts": [d.Summary() for d in self.DUTs],
            "enums": [e.Summary() for e in self.Enums],
            "applications": [path for _, path in self.Applications()],
            "recipeDefinitions": [d.Path for d in self.RecipeDefinitions()],
            "folders": self.Folders(),
            "counts": {
                "pous": len(self.Pous),
                "gvls": len(self.GVLs),
                "duts": len(self.DUTs),
                "enums": len(self.Enums),
            },
        }

    # -- text search -----------------------------------------------------
    def SearchText(self, pattern, is_regex=False, case_sensitive=False,
                   ignore_comments=False, max_results=200):
        """
        Search declarations and implementations of every POU (members included),
        GVL, DUT and ENUM. One hit per matching line, reported with its 1-based
        line number within the section it was found in.
        """
        flags = re.MULTILINE | (0 if case_sensitive else re.IGNORECASE)
        try:
            regex = re.compile(pattern if is_regex else re.escape(pattern), flags)
        except re.error as ex:
            raise ValueError("Invalid regular expression '" + pattern + "': " + str(ex))

        matches = []
        not_textual = []
        searched = 0
        truncated = False

        for kind, pou, member, item in self._searchable():
            searched += 1
            implementation = item.GetImplementation()
            if implementation is None and kind in _KINDS_WITH_BODY:
                not_textual.append(item.Path)

            for section, text in (("declaration", item.GetDeclaration()),
                                  ("implementation", implementation)):
                if not text:
                    continue
                if not _search_section(regex, text, ignore_comments, max_results, matches, {
                        "pou": pou, "member": member, "path": item.Path,
                        "objectKind": kind, "section": section}):
                    truncated = True
                    break
            if truncated:
                break

        return {
            "pattern": pattern,
            "regex": bool(is_regex),
            "caseSensitive": bool(case_sensitive),
            "ignoreComments": bool(ignore_comments),
            "matchCount": len(matches),
            "truncated": truncated,
            "objectsSearched": searched,
            "implementationNotTextual": not_textual,
            "matches": matches,
        }

    def _searchable(self):
        """(objectKind, pouName, memberChain, wrapper) for everything with text."""
        for pou in self.Pous:
            yield pou.Type, pou.Name, None, pou
            for entry in _member_entries(pou, pou.Name, u""):
                yield entry
        for gvl in self.GVLs:
            yield "GVL", gvl.Name, None, gvl
        for dut in self.DUTs:
            yield "DUT", dut.Name, None, dut
        for enum in self.Enums:
            yield "ENUM", enum.Name, None, enum

    # -- tasks -----------------------------------------------------------
    def TaskConfiguration(self):
        self._scan()
        configurations = []
        for obj, path in self._task_configurations:
            tasks = []
            for child in _children(obj):
                if object_type(child) == TYPE_TASK or _flag(child, "is_task"):
                    tasks.append(_task_info(child, path + u"/" + object_name(child)))
            configurations.append({
                "path": path,
                "application": path.rsplit(u"/", 1)[0] if u"/" in path else u"",
                "taskCount": len(tasks),
                "tasks": tasks,
            })
        return {"projectPath": self.Path, "taskConfigurations": configurations}

    # -- libraries -------------------------------------------------------
    def LibraryManagers(self):
        """(scope path, library manager) for the project-level (POU pool) and every application's manager."""
        managers = []
        seen = set()

        def add(scope, owner):
            getter = getattr(owner, "get_library_manager", None)
            if getter is None:
                return
            try:
                manager = getter()
            except Exception as ex:
                log("No library manager in '%s': %s" % (scope or "<project>", mcp_io._describe(ex)))
                return
            if manager is None:
                return
            key = _object_key(manager)
            if key in seen:
                return
            seen.add(key)
            managers.append((scope, manager))

        add(u"", self.Object)
        for application, path in self.Applications():
            add(path, application)
        return managers

    def LibraryReferences(self):
        """
        Every library reference of every library manager, with the source file the library can
        be read from (a .library in a library repository or next to the project), if any.
        """
        project_dir = os.path.dirname(os.path.abspath(self.Path))
        references = []
        for scope, manager in self.LibraryManagers():
            try:
                items = list(manager.references)
            except Exception as ex:
                log("Could not read the references of '%s': %s" % (scope or "<project>", mcp_io._describe(ex)))
                continue
            for reference in items:
                info = _library_reference_info(reference)
                info["scope"] = scope or u"<project>"
                info["source"] = find_library_source(
                    info.get("title"), info.get("version"), info.get("company"), project_dir)
                references.append(info)
        return {"projectPath": self.Path, "count": len(references), "libraries": references}

    def FindLibrary(self, name):
        """The reference matching name (placeholder, title, namespace, reference name or resolution)."""
        listing = self.LibraryReferences()["libraries"]
        wanted = (name or u"").strip().lower()
        for info in listing:
            if wanted in _library_aliases(info):
                return info
        available = sorted(set(info.get("title") or info.get("name") or u"?" for info in listing))
        raise LookupError(
            "Library '" + str(name) + "' is not referenced by the project. Referenced: "
            + (u", ".join(available) or u"<none>"))

    # -- recipes ---------------------------------------------------------
    def Recipes(self):
        """Every Recipe Manager with its settings and the summary of each recipe definition."""
        managers = self.RecipeManagers()
        return {
            "projectPath": self.Path,
            "recipeManagers": [m.Summary() for m in managers],
            "applicationsWithoutRecipeManager": [
                path for _, path in self.Applications()
                if not any(m.Application == path for m in managers)],
        }

    def _managers_of(self, application):
        managers = self.RecipeManagers()
        if not application:
            return managers
        selected = [m for m in managers
                    if _same_name(m.Application, application)
                    or _same_name(m.Application.rsplit(u"/", 1)[-1], application)
                    or _same_name(m.Path, application)]
        if not selected:
            raise LookupError(
                "No Recipe Manager in application '" + application + "'. Recipe Managers: "
                + (u", ".join(m.Path for m in managers) or u"<none>"))
        return selected

    def FindRecipeDefinition(self, name, application=None):
        """A recipe definition by name or path, optionally only in the given application."""
        definitions = [d for m in self._managers_of(application) for d in m.Definitions]
        found = [d for d in definitions if _same_name(d.Path, name)]
        if not found:
            found = [d for d in definitions if _same_name(d.Name, name)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise ValueError(
                "Recipe definition '" + name + "' exists in more than one application: "
                + u", ".join(d.Path for d in found) + ". Pass its path or the application.")
        raise LookupError(
            "Recipe definition '" + str(name) + "' was not found. Available: "
            + (u", ".join(sorted(d.Path for d in definitions)) or u"<none>"))

    def CreateRecipeDefinition(self, name, application=None):
        """Adds a recipe definition to the Recipe Manager of the given (or the only) application."""
        managers = self._managers_of(application)
        if not managers:
            raise LookupError(
                "The project has no Recipe Manager. Add one to the application in CODESYS "
                "(Add Object > Recipe Manager) first; the scripting engine cannot create it.")
        if len(managers) > 1:
            raise ValueError(
                "The project has several Recipe Managers (" + u", ".join(m.Path for m in managers)
                + "). Pass the application the recipe definition belongs to.")
        manager = managers[0]
        for existing in manager.Definitions:
            if _same_name(existing.Name, name):
                raise ValueError("Recipe definition '" + existing.Path + "' already exists.")
        created = manager.Object.create_recipedefinition(name)
        definition = RecipeDefinition(created, manager.Path + u"/" + object_name(created), manager)
        manager.Definitions.append(definition)
        return definition

    # -- creation --------------------------------------------------------
    def CreatePou(self, name, pou_type="PRG", language="ST", return_type=None, parent_path=None):
        parent = self.ResolveParent(parent_path)
        self._assert_unique(name)

        kwargs = {"name": name, "type": _pou_type(pou_type)}

        language_value = _language(language)
        if language_value is not None:
            kwargs["language"] = language_value

        if _normalize_pou_type(pou_type) == "FUN":
            kwargs["return_type"] = return_type or "BOOL"

        created = _try_call(parent, "create_pou", kwargs)
        self._invalidate()
        return Pou(created, self._path_of(parent_path, name))

    def CreateGvl(self, name, parent_path=None):
        parent = self.ResolveParent(parent_path)
        self._assert_unique(name)
        created = _try_call(parent, "create_gvl", {"name": name})
        self._invalidate()
        return Gvl(created, self._path_of(parent_path, name))

    def CreateDut(self, name, dut_kind="struct", base_type=None, parent_path=None):
        parent = self.ResolveParent(parent_path)
        self._assert_unique(name)

        kwargs = {"name": name, "type": _dut_type(dut_kind)}
        if base_type:
            kwargs["base_type"] = base_type

        created = _try_call(parent, "create_dut", kwargs)
        self._invalidate()
        return created

    def _assert_unique(self, name):
        self._scan()
        for collection in (self._pous, self._gvls, self._duts, self._enums):
            existing = self.Find(collection, name)
            if existing is not None:
                raise ValueError(
                    "An object named '" + name + "' already exists at '" + existing.Path + "'.")

    @staticmethod
    def _path_of(parent_path, name):
        return (parent_path.rstrip(u"/") + u"/" + name) if parent_path else name

    def _invalidate(self):
        self._scanned = False
        self._pous = []
        self._gvls = []
        self._duts = []
        self._enums = []
        self._applications = []
        self._folders = []
        self._task_configurations = []
        self._recipe_managers = []
        self._other = []

    # -- lifecycle -------------------------------------------------------
    def Compiler(self):
        return Compiler(self)

    def Save(self):
        log("Saving project")
        self.Object.save()
        return True

    def Close(self):
        try:
            self.Object.close()
            return True
        except Exception as ex:
            log("Could not close the project: " + str(ex))
            return False


# ===========================================================================
# Library helpers
# ===========================================================================

# "Title, 1.2.3.4 (Company)" - how CODESYS writes a library resolution.
_RESOLUTION_RE = re.compile(r"^\s*(?P<title>.+?)\s*,\s*(?P<version>[^\s(]+)\s*\((?P<company>.*)\)\s*$")

SOURCE_LIBRARY_EXTENSIONS = (".library",)
COMPILED_LIBRARY_EXTENSIONS = (".compiled-library", ".compiled-library-v3")


def is_library_path(path):
    """True for a source library file (.library); compiled libraries do not count."""
    return (path or u"").strip().lower().endswith(SOURCE_LIBRARY_EXTENSIONS)
DEFAULT_LIBRARY_REPOSITORY = r"C:\ProgramData\CODESYS\Managed Libraries"


def parse_library_resolution(text):
    """Split "Title, 1.2.3.4 (Company)" into its parts; None for anything else."""
    match = _RESOLUTION_RE.match(text or u"")
    if not match:
        return None
    return {
        "title": match.group("title").strip(),
        "version": match.group("version").strip(),
        "company": match.group("company").strip(),
    }


def _object_key(obj):
    for name in ("guid", "id"):
        value = getattr(obj, name, None)
        if value is not None:
            return str(value)
    return str(id(obj))


def _library_reference_info(reference):
    def text(name):
        try:
            value = getattr(reference, name, None)
        except Exception:
            return None
        if value is None or callable(value):
            return None
        return mcp_io._to_text(value)

    def flag(name):
        try:
            return bool(getattr(reference, name, False))
        except Exception:
            return False

    info = {
        "name": text("name"),
        "placeholderName": text("placeholder_name"),
        "namespace": text("namespace"),
        "isPlaceholder": flag("is_placeholder"),
        "isManaged": flag("is_managed"),
        "isRedirected": flag("is_redirected"),
        "optional": flag("optional"),
        "systemLibrary": flag("system_library"),
        "qualifiedOnly": flag("qualified_only"),
        "effectiveResolution": text("effective_resolution"),
        "defaultResolution": text("default_resolution"),
        "resolutionInfo": text("resolution_info"),
    }
    parsed = (parse_library_resolution(info["effectiveResolution"])
              or parse_library_resolution(info["defaultResolution"])
              or parse_library_resolution(info["name"]))
    info["title"] = parsed["title"] if parsed else None
    info["version"] = parsed["version"] if parsed else None
    info["company"] = parsed["company"] if parsed else None
    return info


def _library_aliases(info):
    aliases = set()
    for key in ("name", "placeholderName", "namespace", "title", "effectiveResolution", "defaultResolution"):
        value = info.get(key)
        if value:
            aliases.add(value.strip().lower())
            aliases.add(value.strip().lstrip(u"#").lower())
    return aliases


def _library_repository_roots():
    roots = []
    manager = resolve("librarymanager", required=False)
    if manager is not None:
        try:
            for repository in manager.repositories:
                root = getattr(repository, "root_folder", None)
                if root:
                    roots.append(mcp_io._to_text(root))
        except Exception as ex:
            log("Could not list library repositories: " + mcp_io._describe(ex))
    if not roots:
        roots.append(DEFAULT_LIBRARY_REPOSITORY)
    return roots


def _version_key(text):
    parts = []
    for part in re.split(r"[.\-]", text or u""):
        parts.append((0, int(part), u"") if part.isdigit() else (1, 0, part))
    return parts


def _library_files(directory):
    """(path, kind) for every library file directly inside directory."""
    found = []
    try:
        names = os.listdir(directory)
    except Exception:
        return found
    for name in names:
        path = os.path.join(directory, name)
        lowered = name.lower()
        if not os.path.isfile(path):
            continue
        if lowered.endswith(SOURCE_LIBRARY_EXTENSIONS):
            found.append((path, "source"))
        elif lowered.endswith(COMPILED_LIBRARY_EXTENSIONS):
            found.append((path, "compiled"))
    return found


def _prefer_source(candidates):
    sources = [c for c in candidates if c[1] == "source"]
    return (sources or candidates)[0] if candidates else None


def _alnum(text):
    return u"".join(c for c in (text or u"").lower() if c.isalnum())


def _strip_library_extension(name):
    lowered = name.lower()
    for extension in COMPILED_LIBRARY_EXTENSIONS + SOURCE_LIBRARY_EXTENSIONS:
        if lowered.endswith(extension):
            return name[:-len(extension)]
    return name


def find_library_source(title, version, company, project_dir, repository_roots=None):
    """
    Where a referenced library can be read from:
      1. an installed copy in a library repository: <root>/<company>/<title>/<version>/,
         the newest version when the reference asks for "*";
      2. a file next to the project named after the library (Title.library,
         Title_1.2.3.library, ...), the version-matching one first.
    A source .library beats a compiled one in the same place. Returns
    {"file", "kind": "source"|"compiled", "location": "repository"|"projectFolder"} or None.
    """
    if not title:
        return None

    exact_version = version if version and version != u"*" else None

    if repository_roots is None:
        repository_roots = _library_repository_roots()

    for root in repository_roots:
        if not company:
            break
        title_dir = os.path.join(root, company, title)
        if not os.path.isdir(title_dir):
            continue
        if exact_version:
            versions = [exact_version]
        else:
            try:
                versions = sorted(os.listdir(title_dir), key=_version_key, reverse=True)
            except Exception:
                versions = []
        for candidate in versions:
            chosen = _prefer_source(_library_files(os.path.join(title_dir, candidate)))
            if chosen:
                return {"file": chosen[0], "kind": chosen[1], "location": "repository"}

    if project_dir:
        # Compare without separators, so "My Lib", "My_Lib" and "MyLib" all match; whatever
        # follows the title must be a version (or nothing), so "Lib" never matches "LibExtra".
        wanted = _alnum(title)
        version_text = _alnum(exact_version) if exact_version else None
        exact = []
        loose = []
        for path, kind in _library_files(project_dir):
            stem = _alnum(_strip_library_extension(os.path.basename(path)))
            if not stem.startswith(wanted):
                continue
            rest = stem[len(wanted):]
            if version_text and rest == version_text:
                exact.append((path, kind))
            elif rest == u"" or rest[0].isdigit():
                loose.append((path, kind))
        chosen = _prefer_source(exact) or _prefer_source(sorted(loose, reverse=True))
        if chosen:
            return {"file": chosen[0], "kind": chosen[1], "location": "projectFolder"}

    return None


# ===========================================================================
# Text search helpers
# ===========================================================================

# Object kinds that normally have an implementation; when it is missing, the body is
# graphical (FBD/LD/CFC/SFC) and was not searched.
_KINDS_WITH_BODY = ("PRG", "FB", "FUN", "METHOD", "ACTION", "TRANSITION", "ACCESSOR")


def _member_entries(owner, pou_name, prefix):
    for member in owner.MemberObjects():
        chain = prefix + member.Name
        yield member.Type, pou_name, chain, member
        for entry in _member_entries(member, pou_name, chain + u"."):
            yield entry


def _search_section(regex, text, ignore_comments, max_results, matches, where):
    """Append one match per matching line. Returns False once max_results is exceeded."""
    haystack = _mask(text)[0] if ignore_comments else text
    line_starts = None
    last_line = 0

    for match in regex.finditer(haystack):
        if line_starts is None:
            line_starts = [0] + [m.end() for m in re.finditer(u"\n", text)]
        line = bisect.bisect_right(line_starts, match.start())
        if line == last_line:
            continue
        last_line = line

        if len(matches) >= max_results:
            return False

        start = line_starts[line - 1]
        end = text.find(u"\n", start)
        entry = dict(where)
        entry["line"] = line
        entry["text"] = text[start:end if end >= 0 else len(text)].strip()[:400]
        matches.append(entry)

    return True


# ===========================================================================
# Task configuration helpers
# ===========================================================================

def _task_attr(task, name):
    """A task property as text; None when missing or empty."""
    try:
        value = getattr(task, name)
    except Exception:
        return None
    if value is None:
        return None
    text = _squash(str(value))
    return text or None


def _task_info(task, path):
    kind = _task_attr(task, "kind_of_task")
    kind = kind.split(u".")[-1] if kind else None
    interval = _task_attr(task, "interval")
    unit = _task_attr(task, "interval_unit")
    event = _task_attr(task, "event")
    external_event = _task_attr(task, "external_event")
    priority = _task_attr(task, "priority")
    interval_ms = _interval_ms(interval, unit)

    try:
        pous = [_squash(str(p)) for p in task.pous]
    except Exception:
        # Older engines without task.pous: the POU calls are the task's children.
        pous = [object_name(c) for c in _children(task)]

    watchdog = None
    try:
        dog = task.watchdog
        watchdog = {
            "enabled": _flag(dog, "enabled"),
            "time": _task_attr(dog, "time"),
            "timeUnit": _task_attr(dog, "time_unit"),
            "sensitivity": _task_attr(dog, "sensitivity"),
        }
    except Exception:
        pass

    parsed_priority = _try_int(priority) if priority else None
    return {
        "name": object_name(task),
        "path": path,
        "kind": kind,
        "priority": parsed_priority if parsed_priority is not None else priority,
        "interval": interval,
        "intervalUnit": unit,
        "intervalMs": interval_ms,
        "event": event,
        "externalEvent": external_event,
        "trigger": _task_trigger(kind, interval_ms, interval, unit, event, external_event),
        "watchdog": watchdog,
        "pous": pous,
    }


_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|us|ns|d|h|m|s)")
_DURATION_MS = {
    u"d": 86400000.0, u"h": 3600000.0, u"m": 60000.0, u"s": 1000.0,
    u"ms": 1.0, u"us": 0.001, u"ns": 0.000001,
}


def _interval_ms(interval, unit):
    """Task interval in milliseconds: "100" + "ms", "t#30ms", "T#1s500ms", ..."""
    text = (interval or u"").strip().lower().replace(u"_", u"")
    if not text:
        return None

    if u"#" in text:
        body = text.split(u"#", 1)[1]
        parts = _DURATION_PART_RE.findall(body)
        if not parts or u"".join(n + part_unit for n, part_unit in parts) != body:
            return None
        total = sum(float(n) * _DURATION_MS[part_unit] for n, part_unit in parts)
    else:
        factor = _DURATION_MS.get((unit or u"ms").strip().lower())
        if factor is None:
            return None
        try:
            total = float(text) * factor
        except ValueError:
            return None

    return int(total) if total == int(total) else total


def _task_trigger(kind, interval_ms, interval, unit, event, external_event):
    """Human-readable summary of what starts the task (per the CODESYS task types)."""
    name = (kind or u"").lower()
    if name == u"cyclic":
        if interval_ms is not None:
            return u"cyclic, every %s ms" % interval_ms
        return u"cyclic, every " + (interval or u"?") + (u" " + unit if unit else u"")
    if name == u"freewheeling":
        return u"freewheeling (restarts as soon as the previous cycle ends)"
    if name == u"event":
        return u"event: rising edge of " + (event or u"<no variable set>")
    if name == u"status":
        return u"status: runs while " + (event or u"<no variable set>") + u" is TRUE"
    if u"external" in name:
        return u"external event: " + (external_event or u"<no event set>")
    return kind


# ===========================================================================
# Enum-ish argument resolution
# ===========================================================================

_POU_TYPE_ALIASES = {
    "PRG": "PRG", "PROGRAM": "PRG",
    "FB": "FB", "FUNCTIONBLOCK": "FB", "FUNCTION_BLOCK": "FB",
    "FUN": "FUN", "FC": "FUN", "FUNCTION": "FUN",
}

_POU_TYPE_MEMBERS = {
    "PRG": ("Program", "program"),
    "FB": ("FunctionBlock", "function_block", "functionblock"),
    "FUN": ("Function", "function"),
}

_LANGUAGE_ALIASES = {
    "ST": "ST", "STRUCTUREDTEXT": "ST", "STRUCTURED_TEXT": "ST",
    "IL": "IL", "INSTRUCTIONLIST": "IL",
    "LD": "LD", "LADDER": "LD", "LADDERDIAGRAM": "LD",
    "FBD": "FBD", "FUNCTIONBLOCKDIAGRAM": "FBD",
    "SFC": "SFC", "SEQUENTIALFUNCTIONCHART": "SFC",
    "CFC": "CFC", "CONTINUOUSFUNCTIONCHART": "CFC",
}

# The scripting engine exposes ImplementationLanguages.st / instruction_list / ladder /
# fbd / sfc / cfc (Guid values); the longer spellings are kept for other versions.
_LANGUAGE_MEMBERS = {
    "ST": ("st", "structured_text", "StructuredText", "ST"),
    "IL": ("instruction_list", "il", "InstructionList", "IL"),
    "LD": ("ladder", "ld", "ladder_diagram", "ladder_logic_diagram", "LadderDiagram", "LD"),
    "FBD": ("fbd", "function_block_diagram", "FunctionBlockDiagram", "FBD"),
    "SFC": ("sfc", "sequential_function_chart", "SequentialFunctionChart", "SFC"),
    "CFC": ("cfc", "continuous_function_chart", "ContinuousFunctionChart", "CFC"),
}

_DUT_TYPE_MEMBERS = {
    "struct": ("Structure", "Struct", "structure"),
    "enum": ("Enumeration", "Enum", "enumeration"),
    "union": ("Union", "union"),
    "alias": ("Alias", "alias"),
}


def _normalize_pou_type(value):
    key = re.sub(r"\s+", u"", (value or u"PRG")).upper()
    if key not in _POU_TYPE_ALIASES:
        raise ValueError("Unsupported POU type '" + str(value) + "'. Use PRG, FB or FUN.")
    return _POU_TYPE_ALIASES[key]


def _normalize_language(value):
    key = re.sub(r"[\s_]+", u"", (value or u"ST")).upper()
    if key not in _LANGUAGE_ALIASES:
        raise ValueError(
            "Unsupported language '" + str(value) + "'. Use ST, IL, LD, FBD, SFC or CFC.")
    return _LANGUAGE_ALIASES[key]


def _normalize_language_name(text):
    key = re.sub(r"[\s_]+", u"", text or u"").upper()
    return _LANGUAGE_ALIASES.get(key, text)


def _pou_type(value):
    normalized = _normalize_pou_type(value)
    enumeration = resolve("PouType")
    return _member(enumeration, _POU_TYPE_MEMBERS[normalized], "PouType")


def _language(value):
    """
    The ImplementationLanguages Guid for a language name. create_pou only accepts that
    Guid (or None), never the name itself, so this returns None for ST when the
    enumeration cannot be resolved (CODESYS then defaults to ST) and raises otherwise.
    """
    normalized = _normalize_language(value)
    enumeration = resolve("ImplementationLanguages", required=False)
    if enumeration is not None:
        candidates = _LANGUAGE_MEMBERS[normalized]
        for candidate in candidates:
            member = getattr(enumeration, candidate, None)
            if member is not None:
                return member
        # Last resort: case-insensitive match against what the enumeration offers.
        wanted = set(c.lower() for c in candidates)
        for attribute in dir(enumeration):
            if attribute.lower() in wanted:
                member = getattr(enumeration, attribute, None)
                if member is not None:
                    return member
    if normalized == "ST":
        return None
    raise RuntimeError(
        "Language " + normalized + " cannot be selected in this CODESYS version "
        "(no matching ImplementationLanguages member).")


def _dut_type(kind):
    enumeration = resolve("DutType", required=False)
    if enumeration is None:
        return None
    return _member(enumeration, _DUT_TYPE_MEMBERS[kind], "DutType")


def _member(enumeration, candidates, label):
    for candidate in candidates:
        value = getattr(enumeration, candidate, None)
        if value is not None:
            return value
    raise RuntimeError(
        "None of " + str(list(candidates)) + " exist on " + label + " in this CODESYS version.")


def _try_call(target, method_name, kwargs):
    """Call a create_* method, degrading to positional arguments if the signature differs."""
    method = getattr(target, method_name, None)
    if method is None:
        raise RuntimeError(
            "'" + method_name + "' is not available on this object (" + str(type(target)) + ").")

    filtered = dict([(k, v) for k, v in kwargs.items() if v is not None])

    try:
        return method(**filtered)
    except TypeError:
        pass

    ordered = [filtered[k] for k in ("name", "type", "language", "return_type", "base_type")
               if k in filtered]
    return method(*ordered)


# ===========================================================================
# Application entry point
# ===========================================================================

class Application(object):
    """
    Entry point of the facade.

    Note: this is *not* the CODESYS "Application" PLC object - it is the script-side
    application handle requested by the API spec. PLC applications are reachable via
    Project.Applications().
    """

    def __init__(self):
        self.system = resolve("system")
        self.projects = resolve("projects")

    def OpenProject(self, path, password=None, update=False):
        """
        Open a project, reusing the primary project when it is already the requested one.
        Without an explicit password, the one the server supplied for this request (if any)
        is used. A failure that is about the password raises ProjectPasswordError, so the
        server can ask the user for it instead of just reporting a failed open.
        """
        primary = self._primary()
        if primary is not None and _same_path(_project_path(primary), path):
            log("Reusing already-open project: " + str(path))
            return Project(primary, path)

        if not password:
            password = mcp_io.request_password()

        log("Opening project: " + str(path) + (" (with password)" if password else ""))
        kwargs = {}
        if password:
            kwargs["password"] = password
        if update:
            kwargs["update_project"] = True

        try:
            try:
                script_project = self.projects.open(path, **kwargs) if kwargs else self.projects.open(path)
            except TypeError:
                script_project = self.projects.open(path)
        except Exception as ex:
            if _is_password_error(ex):
                raise ProjectPasswordError(path, bool(password), ex)
            if _is_cancelled_prompt(ex):
                # A password-protected project opened without (the right) password shows a
                # password dialog, which --noUI cancels like any other question. Report it as
                # a password problem so the settings page asks for one; the message still
                # lists the other dialogs that end the same way.
                raise ProjectPasswordError(path, bool(password), ex, prompted=True)
            raise

        return Project(script_project, path)

    def PrimaryProject(self):
        primary = self._primary()
        if primary is None:
            return None
        return Project(primary, _project_path(primary))

    def _primary(self):
        try:
            return self.projects.primary
        except Exception:
            return None


class ProjectPasswordError(Exception):
    """CODESYS refused to open a project because its password is missing or wrong."""

    def __init__(self, path, password_given, cause, prompted=False):
        self.code = "password_invalid" if password_given else "password_required"
        if password_given:
            text = "The password for project '%s' was rejected." % path
        else:
            text = "Project '%s' is password protected; a password is required to open it." % path
        if prompted:
            # Only a cancelled dialog to go by: most likely the password prompt, not certainly.
            text = ("CODESYS cancelled opening project '%s' because it asked a question that "
                    "cannot be shown without a UI, most likely for the project password%s. "
                    "If the project has no password, the dialog was something else: %s"
                    % (path, " (the given one was not accepted)" if password_given else "",
                       _OTHER_DIALOG_CAUSES))
        Exception.__init__(self, text + " (CODESYS: " + mcp_io._describe(cause) + ")")


# Words CODESYS uses (English / German UI languages) when opening fails for lack of the
# right password: encrypted projects, password-protected projects.
_PASSWORD_HINTS = (u"password", u"passwort", u"kennwort", u"encrypt", u"decrypt", u"verschl")


def _is_password_error(ex):
    text = mcp_io._to_text(ex).lower()
    return any(hint in text for hint in _PASSWORD_HINTS)


# Dialogs besides the password prompt that --noUI cancels while opening a project.
_OTHER_DIALOG_CAUSES = (
    "Usual causes: the project is open in another CODESYS instance (lock file next to the "
    ".project), it was saved with a different CODESYS version or profile and asks to "
    "update/convert, or devices/libraries it references are not installed. Open it once in "
    "the CODESYS GUI with the same profile, answer the dialog, save and close it, then retry.")


# CODESYS answers every prompt with Cancel under --noUI and then aborts the open with this.
_CANCELLED_HINTS = (u"cancelled by user", u"canceled by user", u"vom benutzer abgebrochen")


def _is_cancelled_prompt(ex):
    text = mcp_io._to_text(ex).lower()
    return any(hint in text for hint in _CANCELLED_HINTS)


def _project_path(script_project):
    for name in ("path", "project_path", "filename"):
        value = getattr(script_project, name, None)
        if value:
            return str(value)
    return u""


def _same_path(left, right):
    if not left or not right:
        return False
    return left.replace(u"/", u"\\").lower() == right.replace(u"/", u"\\").lower()


# ===========================================================================
# Declaration text generation
# ===========================================================================

def build_gvl_declaration(variables):
    lines = [u"{attribute 'qualified_only'}", u"VAR_GLOBAL"]
    for variable in variables or []:
        lines.append(u"\t" + _variable_line(variable))
    lines.append(u"END_VAR")
    return u"\n".join(lines)


def build_struct_declaration(name, fields, base_type=None):
    header = u"TYPE " + name
    if base_type:
        header += u" EXTENDS " + base_type
    header += u" :"

    lines = [header, u"STRUCT"]
    for field in fields or []:
        lines.append(u"\t" + _variable_line(field))
    lines.append(u"END_STRUCT")
    lines.append(u"END_TYPE")
    return u"\n".join(lines)


def build_enum_declaration(name, values, base_type=None):
    entries = []
    for value in values or []:
        entries.append(u"\t" + _squash(value))

    lines = [u"{attribute 'qualified_only'}",
             u"TYPE " + name + u" :",
             u"("]
    lines.append(u",\n".join(entries))
    lines.append(u") " + (base_type or u"INT") + u";")
    lines.append(u"END_TYPE")
    return u"\n".join(lines)


def _variable_line(variable):
    name = (variable.get("name") or u"").strip()
    type_name = (variable.get("type") or u"").strip()
    initial = variable.get("initialValue")
    comment = variable.get("comment")

    if not name or not type_name:
        raise ValueError("Every variable/field needs a name and a type.")

    line = name + u" : " + type_name
    if initial:
        line += u" := " + str(initial).strip()
    line += u";"
    if comment:
        line += u" // " + _squash(comment)
    return line
