import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Disclaimer",
};

// Kept in sync with the repository's root DISCLAIMER.md by hand: the frontend build
// only ever copies the frontend/ directory, so this page carries its own copy of the
// same text rather than reading a file outside that directory at runtime.
const DISCLAIMER_TEXT =
  'ReadyTrader-Crypto is provided for informational and educational purposes only and does not constitute financial, investment, legal, or tax advice. Trading digital assets involves substantial risk and may result in partial or total loss of funds. Past performance is not indicative of future results. You are solely responsible for any decisions, trades, configurations, supervision, and the security of your keys/credentials. ReadyTrader-Crypto is provided "AS IS", without warranties of any kind, and we make no guarantees regarding profitability, performance, availability, or outcomes. By using ReadyTrader-Crypto, you acknowledge and accept these risks.';

export default function Page() {
  return (
    <section className="panel" aria-labelledby="disclaimer-heading">
      <h2 id="disclaimer-heading">Important disclaimer</h2>
      <p>{DISCLAIMER_TEXT}</p>
    </section>
  );
}
