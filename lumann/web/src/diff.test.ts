// npm test
//
// No test framework on the front end, and one algorithm worth testing. Every
// case here is a way the alignment went wrong while it was being written: all
// three of the "wrong paragraph blamed" bugs below were found on the real
// chapter, not invented.
import { diffText } from "./diff";

// The only thing this file needs from node, and @types/node is a dependency the
// browser build has no other reason to carry.
declare const process: { exit(code: number): void };

let failures = 0;

function check(name: string, ok: boolean, detail = "") {
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

const P = (...blocks: string[]) => blocks.join("\n\n");

// --- the basics -------------------------------------------------------------

let d = diffText(P("aa", "bb", "cc"), P("aa", "bb", "cc"));
check("identical text has no changes",
      d.added === 0 && d.deleted === 0 && d.changed === 0);
check("identical text is all context", d.rows.every((row) => row.op === "same"));

d = diffText("он пришел домой", "он пришёл домой");
check("a reworded paragraph is one change", d.changed === 1 && !d.added && !d.deleted);
check("word marks cover the changed word only",
      d.rows[0].leftParts!.filter((p) => p.changed).map((p) => p.text).join("") === "пришел"
      && d.rows[0].rightParts!.filter((p) => p.changed).map((p) => p.text).join("") === "пришёл");

d = diffText(P("aaa bbb", "ccc ddd"), P("aaa bbb", "xxx yyy", "ccc ddd"));
check("an inserted paragraph is one addition", d.added === 1 && !d.changed && !d.deleted);

d = diffText(P("aaa bbb", "xxx yyy", "ccc ddd"), P("aaa bbb", "ccc ddd"));
check("a removed paragraph is one deletion", d.deleted === 1 && !d.changed && !d.added);

d = diffText(P("aa", "bb bb", "cc", "dd dd"), P("aa", "XX XX", "cc", "YY YY"));
check("separate edits are separate hunks", d.hunks.length === 2, JSON.stringify(d.hunks));
check("a hunk never starts on a context row",
      d.hunks.every((hunk) => d.rows[hunk.row].op !== "same"));

// --- the alignment traps ----------------------------------------------------

// A deletion at the head of a run used to shift every pair after it, so the
// last paragraph of the run was reported deleted and an unrelated one changed.
d = diffText(P("keep one", "* *", "мы спасем ее сказала она", "keep two"),
             P("keep one", "мы спасём её сказала она", "keep two"));
check("a deletion at the head of a run does not shift the pairing",
      d.deleted === 1 && d.changed === 1
      && d.rows.find((row) => row.op === "del")!.left === "* *",
      `${d.deleted} del / ${d.changed} changed`);

// Two paragraphs rewritten past all recognition are two rewrites, not a
// delete-then-insert pair chosen by position.
d = diffText(P("общий текст", "первый абзац про поезд", "второй абзац про мост"),
             P("общий текст", "первый абзац про поезда", "второй абзац про мосты"));
check("similar paragraphs pair up in order", d.changed === 2 && !d.added && !d.deleted);

// Unrelated content is a delete and an insert, not one implausible rewrite.
d = diffText(P("общий", "красный автомобиль едет быстро"),
             P("общий", "философия языка и сознания"));
check("unrelated paragraphs are not paired as a rewrite",
      d.deleted === 1 && d.added === 1 && d.changed === 0);

// Line numbers address paragraphs on their own side, which is what the jump
// buttons scroll to.
d = diffText(P("aa", "bb", "cc"), P("aa", "cc"));
const deletion = d.rows.find((row) => row.op === "del")!;
check("a deleted paragraph keeps its own number and none on the other side",
      deletion.leftNo === 2 && deletion.rightNo === null);

// --- scale ------------------------------------------------------------------

const big = Array.from({ length: 3000 }, (_, i) => `абзац номер ${i} со словами`);
const edited = big.map((line, i) => (i % 7 ? line : `${line} и правка`));
const started = Date.now();
d = diffText(P(...big), P(...edited));
const elapsed = Date.now() - started;
check("3000 paragraphs, every seventh edited", d.changed === Math.ceil(3000 / 7),
      `${d.changed} changed in ${elapsed} ms`);
check("and it stays interactive", elapsed < 3000, `${elapsed} ms`);

console.log(failures ? `\n${failures} failed` : "\nall passed");
process.exit(failures ? 1 : 0);
