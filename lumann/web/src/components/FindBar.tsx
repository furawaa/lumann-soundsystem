import { useEffect, useRef } from "react";
import type { FindOptions } from "../find";
import { useI18n } from "../i18n";
import type { Find } from "../useFind";

interface Props {
  find: Find;
  onClose: () => void;
}

/**
 * ⌘F over the formatted-text editor: find, replace, replace all.
 *
 * Presentation only — the state and the matching live in useFind, because the
 * editor draws a highlight for every match and needs the same list.
 */
export function FindBar({ find, onClose }: Props) {
  const { t } = useI18n();
  const queryRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    find.seed();
    queryRef.current?.focus();
    queryRef.current?.select();
  }, []);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "Enter") {
      event.preventDefault();
      find.step(event.shiftKey ? -1 : 1);
    } else if ((event.metaKey || event.ctrlKey) && event.key === "f") {
      // Already open: re-aim rather than let the browser's own bar take over.
      event.preventDefault();
      queryRef.current?.focus();
      queryRef.current?.select();
    }
  }

  return (
    <div className="find-bar" onKeyDown={onKeyDown}>
      <div className="find-row">
        <input
          ref={queryRef}
          className="find-input"
          value={find.query}
          spellCheck={false}
          placeholder={t("find.placeholder")}
          onChange={(event) => find.setQuery(event.target.value)}
        />
        <div className="find-opts">
          {([
            ["caseSensitive", "Aa", t("find.caseSensitive")],
            ["wholeWord", "|а|", t("find.wholeWord")],
            ["regex", ".*", t("find.regex")],
            ["foldYo", "е=ё", t("find.foldYo")],
          ] as [keyof FindOptions, string, string][]).map(([key, label, title]) => (
            <button
              key={key}
              className={find.opts[key] ? "find-opt on" : "find-opt"}
              aria-pressed={find.opts[key]}
              title={title}
              onClick={() => find.toggle(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className={find.broken ? "find-count bad" : "find-count"}>
          {find.broken ? t("find.badRegex")
            : find.replaced !== null ? t("find.replaced", { n: find.replaced })
            : find.matches.length
              ? t("find.position", { n: find.index + 1, total: find.matches.length })
            : find.query ? t("find.none")
            : ""}
        </span>
        <button
          className="find-step"
          disabled={!find.matches.length}
          title={t("find.prev")}
          onClick={() => find.step(-1)}
        >
          ↑
        </button>
        <button
          className="find-step"
          disabled={!find.matches.length}
          title={t("find.next")}
          onClick={() => find.step(1)}
        >
          ↓
        </button>
        <button className="find-close" title={t("find.close")} onClick={onClose}>×</button>
      </div>

      <div className="find-row">
        <input
          className="find-input"
          value={find.replacement}
          spellCheck={false}
          placeholder={find.opts.regex ? t("find.replaceWithGroups") : t("find.replaceWith")}
          onChange={(event) => find.setReplacement(event.target.value)}
        />
        <button className="find-act" disabled={!find.current} onClick={find.replaceCurrent}>
          {t("find.replace")}
        </button>
        <button
          className="find-act"
          disabled={!find.matches.length}
          onClick={find.replaceEvery}
        >
          {t("find.replaceAll")}
        </button>
      </div>
    </div>
  );
}
