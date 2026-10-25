// npm test
//
// The cases that matter are Russian ones: \b does not work on Cyrillic, and ё
// has to be findable by typing е without being destroyed by the replacement.
import {
  DEFAULT_OPTIONS, findAll, markParts, matchAfter, replaceAll, type FindOptions,
} from "./find";

declare const process: { exit(code: number): void };

let failures = 0;

function check(name: string, ok: boolean, detail = "") {
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

const opts = (over: Partial<FindOptions> = {}): FindOptions =>
  ({ ...DEFAULT_OPTIONS, foldYo: false, ...over });

const count = (text: string, query: string, over: Partial<FindOptions> = {}) =>
  findAll(text, query, opts(over)).length;

// --- literals ---------------------------------------------------------------

check("finds every occurrence", count("норма, норма, норма", "норма") === 3);
check("empty query finds nothing", count("норма", "") === 0);
check("a literal query is not a regex",
      count("цена 5$ (со скидкой)", "5$ (со") === 1);

// --- case -------------------------------------------------------------------

check("case-insensitive by default", count("Оля и оля", "оля") === 2);
check("case-sensitive finds one", count("Оля и оля", "оля", { caseSensitive: true }) === 1);
check("case folding works on Cyrillic",
      count("ЖИЛА-БЫЛА", "жила") === 1);

// --- whole word: the reason \b is not used ----------------------------------

check("substring matches without the option", count("она оно он", "он") === 3);
check("whole word rejects the Cyrillic prefix",
      count("она оно он", "он", { wholeWord: true }) === 1);
check("whole word holds at punctuation",
      count("«он», — он. он!", "он", { wholeWord: true }) === 3);
check("whole word holds across a hyphen",
      count("какой-то", "какой", { wholeWord: true }) === 1);
check("whole word still respects case",
      count("Он и он", "он", { wholeWord: true, caseSensitive: true }) === 1);
check("whole word is not fooled by a digit",
      count("дом 5 дом5", "дом", { wholeWord: true }) === 1);

// --- ё ----------------------------------------------------------------------

check("ё is not found by typing е when folding is off", count("пришёл", "пришел") === 0);
check("ё is found by typing е", count("пришёл", "пришел", { foldYo: true }) === 1);
check("е is found by typing ё", count("пришел", "пришёл", { foldYo: true }) === 1);
check("Ё folds with its case", count("ЕЩЁ", "ещё", { foldYo: true }) === 1);
check("folding does not damage the rest of the text",
      replaceAll("он пришёл ещё раз", "раз", "два", opts({ foldYo: true })).text
      === "он пришёл ещё два");

// --- regex ------------------------------------------------------------------

check("regex matches", count("а1 б22 в333", "\\d+", { regex: true }) === 3);
check("an unfinished regex finds nothing rather than throwing",
      count("текст", "(", { regex: true }) === 0);
check("groups come back for $1",
      findAll("Гусев Борис", "(\\p{L}+) (\\p{L}+)", opts({ regex: true }))[0].groups.length === 2);
check("\\p{L} is what matches a Cyrillic letter",
      count("Гусев", "\\p{L}+", { regex: true }) === 1);
check("\\w is ASCII and finds none of it",
      count("Гусев", "\\w+", { regex: true }) === 0);

let r = replaceAll("Гусев Борис", "(\\p{L}+) (\\p{L}+)", "$2 $1", opts({ regex: true }));
check("$1 and $2 swap", r.text === "Борис Гусев", r.text);

r = replaceAll("норма", "норма", "$100", opts());
check("$ in a literal replacement stays a $", r.text === "$100", r.text);

r = replaceAll("а", "а", "$$", opts({ regex: true }));
check("$$ is one dollar in regex mode", r.text === "$", r.text);

check("a pattern that matches nothing terminates",
      count("ааа", "б*", { regex: true }) > 0);

// A group captured out of ё-folded text would return "пришел" and eat the ё.
r = replaceAll("он пришёл", "(пришел)", "быстро $1", opts({ regex: true, foldYo: true }));
check("$1 keeps the ё that folding hid", r.text === "он быстро пришёл", r.text);

// --- replace ----------------------------------------------------------------

r = replaceAll("норма норма", "норма", "правило", opts());
check("replace all replaces all", r.text === "правило правило" && r.count === 2);

r = replaceAll("и и и", "и", "или", opts());
check("a replacement containing the query is not replaced again",
      r.text === "или или или" && r.count === 3, r.text);

r = replaceAll("он и она", "он", "человек", opts({ wholeWord: true }));
check("replace all respects whole word", r.text === "человек и она", r.text);

r = replaceAll("текст", "нет", "да", opts());
check("no matches leaves the text alone", r.text === "текст" && r.count === 0);

// --- navigation -------------------------------------------------------------

const m = findAll("аа аа аа", "аа", opts());
check("first match after the caret", matchAfter(m, 0) === 0);
check("caret mid-text picks the next one", matchAfter(m, 1) === 1);
check("caret past the end wraps to the first", matchAfter(m, 99) === 0);

// --- the highlight layer ----------------------------------------------------

// If the parts do not rejoin into the exact text, the layer under the textarea
// drifts and every highlight after the drift sits on the wrong word.
function rejoins(text: string, query: string, over: Partial<FindOptions> = {}, limit = 100) {
  const found = findAll(text, query, opts(over));
  return markParts(text, found, 0, limit).map((part) => part.text).join("") === text;
}

check("parts rejoin into the text", rejoins("норма норма норма", "норма"));
check("parts rejoin when the match is at the very start", rejoins("норма и", "норма"));
check("parts rejoin when the match is at the very end", rejoins("и норма", "норма"));
check("parts rejoin with adjacent matches", rejoins("аааа", "аа"));
check("parts rejoin past the cap", rejoins("аа аа аа аа", "аа", {}, 2));
check("parts rejoin with no matches at all", rejoins("текст", "нет"));
check("parts rejoin with ё folded", rejoins("он пришёл ещё", "пришел", { foldYo: true }));

let parts = markParts("аа бб аа", findAll("аа бб аа", "аа", opts()), 1, 100);
check("exactly one part is current",
      parts.filter((part) => part.hit === "current").length === 1);
check("the current part is the one asked for",
      parts.findIndex((part) => part.hit === "current") === 2, JSON.stringify(parts));

parts = markParts("аа аа аа", findAll("аа аа аа", "аа", opts()), 0, 2);
check("the cap limits marks, not text",
      parts.filter((part) => part.hit !== "none").length === 2
      && parts.map((part) => part.text).join("") === "аа аа аа");

console.log(failures ? `\n${failures} failed` : "\nall good");
if (failures) process.exit(1);
