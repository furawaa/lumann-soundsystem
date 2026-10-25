/**
 * Select a range in a textarea and scroll it into view.
 *
 * setSelectionRange alone does not scroll reliably, and a textarea exposes no
 * geometry for a character offset. The measurement below is the standard way
 * around that: truncate the value, read the resulting scrollHeight — that is
 * where the offset sits — then put the value back. Writing .value directly does
 * not fire onChange, and React's own value prop never changed, so the
 * controlled component is none the wiser.
 *
 * `focus` is false while the find bar is driving: the caret has to stay in the
 * query field for Enter to keep stepping through matches, and a blurred
 * textarea still shows its selection, greyed.
 */
export function selectAndReveal(
  el: HTMLTextAreaElement, start: number, end: number, focus = true,
) {
  const full = el.value;
  el.value = full.slice(0, start);
  const offsetTop = el.scrollHeight;
  el.value = full;

  if (focus) el.focus({ preventScroll: true });
  el.setSelectionRange(start, end);
  el.scrollTop = Math.max(0, offsetTop - el.clientHeight / 2);
}
