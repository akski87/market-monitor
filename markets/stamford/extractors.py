#!/usr/bin/env python3
"""Stamford — per-market extractors for the shared engine.

Stub: no live availability sources wired yet (buildings are roster-only until a
scrapable source + extractor is added per building). The engine binds NAV / EX /
normalize / BASIS / CONC / PYFETCH from here; empty dicts mean every building is
skipped ("skipped_no_parser") until populated.
"""
NAV = {}
EX = {}
BASIS = {}
CONC = {}
PYFETCH = {}


def normalize(slug, r):
    return r
