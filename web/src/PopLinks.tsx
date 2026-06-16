// One-click cross-reference to each grading company's population report for a
// card. The sites (PSA/GemRate/CGC) are bot-protected and don't expose clean
// card-search URLs, so each button opens a scoped Google search that lands on
// that provider's pop page for the card — works in the user's browser.
const PROVIDERS: { key: string; label: string; suffix: string }[] = [
  { key: "gemrate", label: "GemRate (all)", suffix: "gemrate pop report" },
  { key: "psa", label: "PSA", suffix: "PSA pop report" },
  { key: "sgc", label: "SGC", suffix: "SGC pop report" },
  { key: "cgc", label: "CGC", suffix: "CGC population report" },
];

export default function PopLinks({ card }: { card?: string | null }) {
  const c = (card || "").trim();
  if (!c) return null;
  return (
    <div className="pop-links">
      <span className="pop-links-label">📊 Pop reports:</span>
      {PROVIDERS.map(p => (
        <a
          key={p.key}
          className="pop-link"
          href={`https://www.google.com/search?q=${encodeURIComponent(`${c} ${p.suffix}`)}`}
          target="_blank"
          rel="noreferrer"
          title={`Cross-reference ${c} population on ${p.label}`}
        >
          {p.label}
        </a>
      ))}
    </div>
  );
}
