"""The built-in word lists (DESIGN2 §6.6). Each can be extended or narrowed in zigdag.toml."""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from zigdag.core.texts import Word


class LexiconName(enum.Enum):
    VERBS = "verbs"
    SOLUTION_WORDS = "solution-words"
    VAGUE_WORDS = "vague-words"
    UNITS = "units"
    COMPARATIVES = "comparatives"
    PRONOUNS = "pronouns"
    ESCAPE_CLAUSES = "escape-clauses"
    OPEN_ENDINGS = "open-endings"
    MODALS = "modals"


def _words(text: str) -> frozenset[str]:
    return frozenset(w.strip().lower() for w in text.replace("\n", ",").split(",") if w.strip())


VERBS = _words("""
accept, access, account, achieve, acquire, act, adapt, add, adjust, admit, adopt, advance, advise, affect, aggregate,
alert, align, allocate, allow, analyse, analyze, announce, answer, append, apply, approve, archive, arrange, ask,
assemble, assess, assign, assist, attach, attempt, audit, authenticate, authorise, authorize, avoid, back, balance,
become, begin, bill, bind, block, book, bound, break, bring, broadcast, browse, build, buy, cache, calculate, call,
cancel, capture, carry, catch, change, charge, check, choose, claim, classify, clean, clear, close, collect, combine,
come, commit, compare, compile, complete, compose, compress, compute, confirm, connect, consider, consume, contain,
continue, control, convert, copy, correct, count, cover, create, cut, deal, debit, decide, declare, decline, decode,
decompose, decrypt, deduplicate, define, delete, deliver, deny, depend, deploy, derive, describe, design, detect,
determine, develop, disable, discard, disconnect, discover, display, distribute, divide, do, download, draw, drop,
edit, emit, enable, encode, encrypt, end, enforce, ensure, enter, erase, estimate, evaluate, exchange, exclude,
execute, exist, expand, expire, explain, export, expose, express, extend, extract, fail, fetch, fill, filter, find,
finish, fit, fix, flag, follow, forbid, forecast, format, forward, free, gather, generate, get, give, go, grant,
group, guarantee, guard, handle, have, help, hide, hold, identify, ignore, import, improve, include, increase, index,
indicate, infer, inform, initialise, initialize, insert, inspect, install, integrate, interpret, invite, invoice,
issue, join, keep, know, label, launch, lead, learn, leave, let, limit, link, list, listen, load, locate, lock, log,
look, make, manage, map, mark, match, measure, meet, merge, migrate, minimise, minimize, mirror, model, modify,
monitor, move, name, navigate, need, normalise, normalize, notify, obtain, offer, open, order, organise, organize,
output, own, package, page, parse, pass, pause, pay, perform, permit, persist, pick, place, plan, play, post, predict,
prepare, present, preserve, prevent, print, prioritise, prioritize, process, produce, prompt, protect, prove,
provide, publish, purchase, push, put, query, queue, raise, rank, rate, reach, read, receive, recognise, recognize,
recommend, reconcile, record, recover, redirect, reduce, refer, refresh, refund, refuse, register, reject, release,
reload, remember, remind, remove, rename, render, renew, reorder, repair, repeat, replace, replay, reply, report,
represent, request, require, reserve, reset, resize, resolve, respond, restore, restrict, resume, retain, retry,
return, reuse, reveal, review, revoke, rotate, route, run, save, scale, scan, schedule, score, search, secure, see,
select, sell, send, separate, serve, set, settle, share, ship, show, sign, simulate, skip, sort, specify, split,
start, state, stop, store, stream, submit, subscribe, subtract, suggest, summarise, summarize, supply, support,
suspend, switch, synchronise, synchronize, tag, take, tell, terminate, test, throttle, total, track, trade, train,
transfer, transform, translate, transmit, trigger, trim, trust, turn, type, undo, unify, unlock, update, upgrade,
upload, use, validate, value, verify, view, wait, warn, watch, work, write
""")

SOLUTION_WORDS = _words("""
api, apis, app, application, algorithm, aws, azure, backend, bucket, button, cache, class, cloud, cluster, container,
cron, css, dashboard, database, db, docker, dropdown, endpoint, framework, frontend, function, gcp, graphql, html,
http, https, json, kafka, kubernetes, lambda, library, microservice, module, mongodb, mysql, nosql, orm, page,
popup, postgres, python, queue, react, redis, rest, rpc, s3, screen, script, sdk, server, service, sql, table,
thread, ui, webhook, website, widget, xml, yaml
""")

VAGUE_WORDS = _words("""
adequate, adequately, appropriate, appropriately, approximately, bad, best, better, easily, easy, effective,
efficient, efficiently, enough, fast, few, flexible, frequently, generally, good, intuitive, intuitively, large,
many, maximal, minimal, modern, nice, normal, normally, often, optimal, optimally, quick, quickly, rarely,
reasonable, reasonably, robust, scalable, seamless, seamlessly, several, significant, significantly, simple,
simply, slow, small, some, sufficient, sufficiently, typical, typically, user-friendly, usually, various
""")

UNITS = _words("""
%, b, byte, bytes, call, calls, character, characters, child, children, day, days, file, files, gb, h, hour, hours, item, items,
kb, line, lines, mb, millisecond, milliseconds, min, minute, minutes, ms, ns, percent, request, requests, row, rows,
s, sec, second, seconds, step, steps, tb, time, times, us, user, users, week, weeks, year, years
""")

COMPARATIVES = _words("""
better, bigger, cheaper, easier, fewer, greater, harder, higher, larger, less, lower, more, quicker, safer, shorter,
slower, smaller, sooner, faster, longer, worse
""")

PRONOUNS = _words("it, its, they, them, their, theirs, this, these, those")

ESCAPE_CLAUSES = _words("""
if possible, as appropriate, where practical, as needed, if necessary, where possible, as required, if practical,
to the extent possible, as far as possible
""")

OPEN_ENDINGS = _words("etc, and so on, such as, including but not limited to, among others")

MODALS = _words("should, may, will, must, might, could, would")


@dataclass(frozen=True)
class Lexicons:
    verbs: frozenset[Word] = VERBS
    solution_words: frozenset[Word] = SOLUTION_WORDS
    vague_words: frozenset[Word] = VAGUE_WORDS
    units: frozenset[Word] = UNITS
    comparatives: frozenset[Word] = COMPARATIVES
    pronouns: frozenset[Word] = PRONOUNS
    escape_clauses: frozenset[Word] = ESCAPE_CLAUSES
    open_endings: frozenset[Word] = OPEN_ENDINGS
    modals: frozenset[Word] = MODALS

    def tuned(self, changes: Mapping[LexiconName, tuple[Iterable[Word], Iterable[Word]]]) -> Lexicons:
        """Add, then remove, the words given for each lexicon."""
        out = self
        for name, (add, remove) in changes.items():
            field = name.value.replace("-", "_")
            words = (getattr(out, field) | {w.lower() for w in add}) - {w.lower() for w in remove}
            out = replace(out, **{field: frozenset(words)})
        return out
