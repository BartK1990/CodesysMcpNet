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

import re

from mcp_io import log


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

        found = []
        for c_start, _c_end, text in self.comments:
            if not text:
                continue
            above = shared_line_end <= c_start < content_start
            inside = content_start <= c_start <= line_end
            if above or inside:
                found.append(text)
        return u" ".join(found).strip()


def _mask(text):
    """Return (masked_text, [(start, end, comment_text), ...])."""
    out = []
    comments = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        # Block comment, possibly nested.
        if text.startswith(u"(*", index):
            start = index
            depth = 1
            index += 2
            while index < length and depth > 0:
                if text.startswith(u"(*", index):
                    depth += 1
                    index += 2
                elif text.startswith(u"*)", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            comments.append((start, index, text[start + 2:max(start + 2, index - 2)].strip()))
            out.append(_blank(text[start:index]))
            continue

        # Line comment.
        if text.startswith(u"//", index):
            start = index
            index = text.find(u"\n", index)
            if index < 0:
                index = length
            comments.append((start, index, text[start + 2:index].strip()))
            out.append(_blank(text[start:index]))
            continue

        # Pragma / attribute.
        if char == u"{":
            start = index
            index = text.find(u"}", index)
            index = length if index < 0 else index + 1
            out.append(_blank(text[start:index]))
            continue

        # String literal - kept verbatim so initial values survive.
        if char == u"'" or char == u'"':
            quote = char
            start = index
            index += 1
            while index < length:
                if text[index] == u"$":       # ST escape character
                    index += 2
                    continue
                if text[index] == quote:
                    index += 1
                    break
                index += 1
            out.append(text[start:index])
            continue

        out.append(char)
        index += 1

    return u"".join(out), comments


def _blank(chunk):
    """Replace a chunk with spaces, preserving newlines and total length."""
    return u"".join([c if c in u"\r\n" else u" " for c in chunk])


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

    def Members(self):
        members = []
        for child in _children(self.Object):
            declaration = _textual(child, "textual_declaration")
            members.append({
                "name": object_name(child),
                "kind": detect_pou_kind(declaration),
            })
        return members

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

    def Content(self):
        return {
            "name": self.Name,
            "path": self.Path,
            "declaration": self.GetDeclaration(),
            "variables": self.Variables,
        }


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
            messages.append({
                "severity": _severity(item),
                "text": _squash(str(getattr(item, "text", item))),
                "object": _optional_str(item, "object_name", "objectname", "object"),
                "position": _optional_str(item, "position", "line"),
            })
    except Exception:
        return messages, len(messages) > 0

    return messages, True


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
        self._other = []

    # -- scanning --------------------------------------------------------
    def _scan(self):
        if self._scanned:
            return

        self._walk(self.Object, u"")
        self._scanned = True
        log("Scanned project: %d POU(s), %d GVL(s), %d DUT(s), %d ENUM(s)"
            % (len(self._pous), len(self._gvls), len(self._duts), len(self._enums)))

    def _walk(self, parent, prefix):
        for child in _children(parent):
            name = object_name(child)
            path = name if not prefix else prefix + u"/" + name

            if _flag(child, "is_folder"):
                self._folders.append(path)
                self._walk(child, path)
                continue

            if _flag(child, "is_application"):
                self._applications.append((child, path))
                self._walk(child, path)
                continue

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
                    continue

                if _POU_KIND_RE.search(masked):
                    self._pous.append(Pou(child, path))
                    continue

                self._gvls.append(Gvl(child, path))
                continue

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

    # -- structure -------------------------------------------------------
    def Structure(self):
        return {
            "projectPath": self.Path,
            "pous": [p.Summary() for p in self.Pous],
            "gvls": [g.Summary() for g in self.GVLs],
            "duts": [d.Summary() for d in self.DUTs],
            "enums": [e.Summary() for e in self.Enums],
            "applications": [path for _, path in self.Applications()],
            "folders": self.Folders(),
            "counts": {
                "pous": len(self.Pous),
                "gvls": len(self.GVLs),
                "duts": len(self.DUTs),
                "enums": len(self.Enums),
            },
        }

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

_LANGUAGE_MEMBERS = {
    "ST": ("structured_text", "StructuredText", "ST"),
    "IL": ("instruction_list", "InstructionList", "IL"),
    "LD": ("ladder_diagram", "ladder_logic_diagram", "LadderDiagram", "LD"),
    "FBD": ("function_block_diagram", "FunctionBlockDiagram", "FBD"),
    "SFC": ("sequential_function_chart", "SequentialFunctionChart", "SFC"),
    "CFC": ("continuous_function_chart", "ContinuousFunctionChart", "CFC"),
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
    normalized = _normalize_language(value)
    enumeration = resolve("ImplementationLanguages", required=False)
    if enumeration is None:
        return normalized
    try:
        return _member(enumeration, _LANGUAGE_MEMBERS[normalized], "ImplementationLanguages")
    except Exception:
        return normalized


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
        """Open a project, reusing the primary project when it is already the requested one."""
        primary = self._primary()
        if primary is not None and _same_path(_project_path(primary), path):
            log("Reusing already-open project: " + str(path))
            return Project(primary, path)

        log("Opening project: " + str(path))
        kwargs = {}
        if password:
            kwargs["password"] = password
        if update:
            kwargs["update_project"] = True

        try:
            script_project = self.projects.open(path, **kwargs) if kwargs else self.projects.open(path)
        except TypeError:
            script_project = self.projects.open(path)

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
