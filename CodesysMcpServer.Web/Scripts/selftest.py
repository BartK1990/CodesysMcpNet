# -*- coding: utf-8 -*-
"""
Self-test for the Structured Text parsing and generation layer of codesys_api.

This does NOT need CODESYS: it only exercises the pure text handling, which is the
part most likely to need tweaking for a particular coding style. Run it with any
Python 2.7 / 3.x interpreter, or with the IronPython shipped with CODESYS:

    python selftest.py

Exit code 0 means every check passed.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import codesys_api as api


FAILURES = []


def check(label, actual, expected):
    if actual == expected:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s\n         expected: %r\n         actual:   %r" % (label, expected, actual))
        FAILURES.append(label)


def gvl_variables(declaration):
    st = api.StText(declaration)
    variables = []
    for _kind, _qualifiers, start, end in api.find_var_blocks(st):
        variables.extend(api.parse_variables(st, start, end))
    return variables


def test_gvl():
    print("GVL declaration")
    declaration = u"""{attribute 'qualified_only'}
VAR_GLOBAL
    gMotorOn : BOOL := FALSE; // drive enable
    gSpeed, gSetpoint : REAL := 1.5;
    gCounter AT %MW10 : WORD;
    (* END_VAR inside a comment must not close the block *)
    gLabel : STRING(80) := 'a;b';
END_VAR
VAR_GLOBAL CONSTANT
    cMax : INT := 100;
END_VAR"""

    variables = gvl_variables(declaration)

    check("variable count", len(variables), 6)
    check("names", [v["name"] for v in variables],
          [u"gMotorOn", u"gSpeed", u"gSetpoint", u"gCounter", u"gLabel", u"cMax"])
    check("first type", variables[0]["type"], u"BOOL")
    check("first initial", variables[0]["initialValue"], u"FALSE")
    check("first comment", variables[0]["comment"], u"drive enable")
    check("shared initial value", variables[2]["initialValue"], u"1.5")
    check("address", variables[3]["address"], u"%MW10")
    check("string initial with semicolon", variables[4]["initialValue"], u"'a;b'")
    check("constant block qualifier", variables[5]["type"], u"INT")


def test_struct():
    print("STRUCT declaration")
    declaration = u"""TYPE ST_Axis EXTENDS ST_Base :
STRUCT
    Position : LREAL := 0.0; // mm
    Velocity : LREAL;
    Limits : ARRAY[1..3] OF INT := [1, 2, 3];
END_STRUCT
END_TYPE"""

    parsed = api.parse_type_declaration(declaration)

    check("kind", parsed["kind"], "struct")
    check("name", parsed["name"], u"ST_Axis")
    check("base type", parsed["baseType"], u"ST_Base")
    check("field names", [f["name"] for f in parsed["elements"]],
          [u"Position", u"Velocity", u"Limits"])
    check("array type", parsed["elements"][2]["type"], u"ARRAY[1..3] OF INT")
    check("array initial", parsed["elements"][2]["initialValue"], u"[1, 2, 3]")
    check("field comment", parsed["elements"][0]["comment"], u"mm")


def test_enum():
    print("ENUM declaration")
    declaration = u"""{attribute 'qualified_only'}
TYPE E_State :
(
    Idle := 10, // waiting
    Running,
    Faulted := 99
) DINT;
END_TYPE"""

    parsed = api.parse_type_declaration(declaration)

    check("kind", parsed["kind"], "enum")
    check("name", parsed["name"], u"E_State")
    check("base type", parsed["baseType"], u"DINT")
    check("value names", [v["name"] for v in parsed["values"]],
          [u"Idle", u"Running", u"Faulted"])
    check("explicit values", [v["value"] for v in parsed["values"]],
          [u"10", None, u"99"])
    check("resolved ordinals", [v["ordinal"] for v in parsed["values"]], [10, 11, 99])
    check("value comment", parsed["values"][0]["comment"], u"waiting")


def test_alias():
    print("ALIAS declaration")
    check("simple alias",
          api.parse_type_declaration(u"TYPE T_Speed : REAL; END_TYPE")["kind"], "alias")

    parenthesised = api.parse_type_declaration(u"TYPE T_Name : STRING(80); END_TYPE")
    check("STRING(80) is not an enum", parenthesised["kind"], "alias")
    check("STRING(80) base type", parenthesised["baseType"], u"STRING(80)")


def test_pou_kind():
    print("POU kind detection")
    check("program", api.detect_pou_kind(u"PROGRAM Main\nVAR\nEND_VAR"), "PRG")
    check("function block", api.detect_pou_kind(u"FUNCTION_BLOCK FB_Motor\nVAR\nEND_VAR"), "FB")
    check("function", api.detect_pou_kind(u"FUNCTION Add : INT\nVAR_INPUT\nEND_VAR"), "FUN")
    check("comment is ignored",
          api.detect_pou_kind(u"(* FUNCTION_BLOCK in a comment *)\nPROGRAM Main"), "PRG")


def test_round_trips():
    print("Generation round-trips")

    struct = api.build_struct_declaration(u"ST_New", [
        {"name": u"A", "type": u"INT", "initialValue": u"5", "comment": u"first"},
        {"name": u"B", "type": u"STRING(20)"},
    ], base_type=u"ST_Base")
    parsed = api.parse_type_declaration(struct)
    check("struct round-trip kind", parsed["kind"], "struct")
    check("struct round-trip base", parsed["baseType"], u"ST_Base")
    check("struct round-trip fields",
          [(f["name"], f["type"], f["initialValue"]) for f in parsed["elements"]],
          [(u"A", u"INT", u"5"), (u"B", u"STRING(20)", None)])

    enumeration = api.build_enum_declaration(u"E_New", [u"Idle := 3", u"Busy"], base_type=u"INT")
    parsed = api.parse_type_declaration(enumeration)
    check("enum round-trip kind", parsed["kind"], "enum")
    check("enum round-trip values",
          [(v["name"], v["ordinal"]) for v in parsed["values"]],
          [(u"Idle", 3), (u"Busy", 4)])
    check("enum round-trip base", parsed["baseType"], u"INT")

    gvl = api.build_gvl_declaration([
        {"name": u"gA", "type": u"BOOL", "initialValue": u"TRUE", "comment": u"c"},
    ])
    variables = gvl_variables(gvl)
    check("gvl round-trip",
          [(v["name"], v["type"], v["initialValue"], v["comment"]) for v in variables],
          [(u"gA", u"BOOL", u"TRUE", u"c")])


def test_name_filter():
    print("GVL name filter")
    names = [u"xFault", u"_Fault", u"RedundancyStateError", u"xRun"]
    check("substring", [n for n in names if api.name_matcher(u"fault")(n)], [u"xFault", u"_Fault"])
    check("wildcard", [n for n in names if api.name_matcher(u"x*")(n)], [u"xFault", u"xRun"])
    check("single char", [n for n in names if api.name_matcher(u"x?un")(n)], [u"xRun"])


def test_search():
    print("Text search")
    import re
    text = u"a := 1;\n_Fault := TRUE; // _Fault set\n(* _Fault := FALSE; *)\nb := _Fault;"
    where = {"pou": u"P"}

    matches = []
    api._search_section(re.compile(u"_Fault\\s*:=", re.I | re.M), text, False, 100, matches, where)
    check("one hit per line, raw", [(m["line"], m["text"]) for m in matches],
          [(2, u"_Fault := TRUE; // _Fault set"), (3, u"(* _Fault := FALSE; *)")])

    matches = []
    api._search_section(re.compile(u"_Fault\\s*:=", re.I | re.M), text, True, 100, matches, where)
    check("ignore comments", [m["line"] for m in matches], [2])

    matches = []
    complete = api._search_section(re.compile(u"_Fault", re.M), text, False, 2, matches, where)
    check("truncation", (complete, len(matches)), (False, 2))


def test_interval():
    print("Task interval")
    check("plain ms", api._interval_ms(u"1000", u"ms"), 1000)
    check("plain us", api._interval_ms(u"500", u"us"), 0.5)
    check("time literal", api._interval_ms(u"t#30ms", u"ms"), 30)
    check("compound literal", api._interval_ms(u"T#1s500ms", u"ms"), 1500)
    check("garbage", api._interval_ms(u"t#abc", u"ms"), None)
    check("empty", api._interval_ms(None, u"ms"), None)


def main():
    for test in (test_gvl, test_struct, test_enum, test_alias, test_pou_kind, test_round_trips,
                 test_name_filter, test_search, test_interval):
        test()

    print("")
    if FAILURES:
        print("%d check(s) FAILED: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
