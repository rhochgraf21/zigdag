// zigdag's watcher for vitest: which of the project's files had code run during each test.
//
// vitest takes setup files only from its config, so a project attaches this by one line there:
//
//   test: { setupFiles: process.env.ZIGDAG_WATCHER ? [process.env.ZIGDAG_WATCHER] : [] }
//
// zigdag test sets ZIGDAG_WATCHER to this file, ZIGDAG_SEEN to the file to write to, and ZIGDAG_ROOT to the
// project's root. Run any other way, the variables are unset and this file is never loaded.
//
// What ran is asked of V8 itself (precise coverage, by function), so nothing in the project's code is changed or
// wrapped. The counts are taken, which also resets them, before and after each test: what is left is what ran in
// between. Code at the top of a module runs when the module is loaded, before any test, and is no test's.
//
// One line is written for each test as it ends, since vitest may run test files in several processes at once, and
// a line is appended whole. Each file is written with a digest of what it held, so that zigdag check can tell a
// run that is still about the code as it is from one that is not.
import { afterEach, beforeEach } from "vitest";
import { createHash } from "node:crypto";
import { appendFileSync, readFileSync } from "node:fs";
import inspector from "node:inspector";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SEEN = process.env.ZIGDAG_SEEN;
const ROOT = process.env.ZIGDAG_ROOT;
const OWN = fileURLToPath(import.meta.url);
const LIBRARIES = `${path.sep}node_modules${path.sep}`;
const GROUPS = " > "; // how vitest joins a test's groups and its name, and zigdag names a test

const session = new inspector.Session();
session.connect();

/** Ask the inspector for something. On the thread it is asked from, it answers before this returns. */
function ask(method, parameters) {
  let answer;
  session.post(method, parameters, (error, result) => {
    answer = error ? undefined : result;
  });
  return answer;
}

ask("Profiler.enable");
ask("Profiler.startPreciseCoverage", { callCount: true, detailed: false });

const digests = new Map();

/** A file as the project names it, with a digest of what it holds now; undefined for a file that is not there. */
function described(file) {
  if (!digests.has(file)) {
    try {
      digests.set(file, createHash("sha256").update(readFileSync(file)).digest("hex"));
    } catch {
      digests.set(file, undefined);
    }
  }
  const digest = digests.get(file);
  return digest === undefined ? undefined : { file: path.relative(ROOT, file).split(path.sep).join("/"), digest };
}

/** Whether a script is a file of the project's own: under its root, and no library's. */
function own(url) {
  if (!url.startsWith("file://")) return false;
  const file = fileURLToPath(url);
  return file !== OWN && file.startsWith(ROOT + path.sep) && !file.includes(LIBRARIES);
}

/** A test's name as vitest's report gives it: the groups it is in, outermost first, then its own. */
function named(task) {
  const names = [task.name];
  for (let group = task.suite; group && group.id !== task.file.id; group = group.suite) {
    names.unshift(group.name);
  }
  return names.join(GROUPS);
}

beforeEach(() => {
  ask("Profiler.takePreciseCoverage"); // forget what ran before this test
});

afterEach(({ task }) => {
  const taken = ask("Profiler.takePreciseCoverage");
  const ran = (taken?.result ?? [])
    .filter((script) => own(script.url))
    .filter((script) => script.functions.some((f) => f.ranges.some((range) => range.count > 0)))
    .map((script) => described(fileURLToPath(script.url)))
    .filter((file) => file !== undefined);
  const test = described(task.file.filepath);
  if (test === undefined) return;
  const line = { test: { ...test, name: named(task) }, ran: ran.filter((file) => file.file !== test.file) };
  appendFileSync(SEEN, JSON.stringify(line) + "\n");
});
