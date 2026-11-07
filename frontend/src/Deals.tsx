import { useEffect, useRef, useState } from "preact/hooks";

import { api } from "./api";
import { CheckerLine } from "./CheckerLine";
import { checkNow } from "./checkNow";
import { candidateWords, withExclusion } from "./exclude";
import { ago, money, safeLink, sourceName } from "./format";
import { hide, loadHidden, saveHidden, unhide } from "./hidden";
import { markSeen, unseenIds } from "./seen";
import type { Deal, Rule, Source } from "./types";

const MAX_DEALS = 100; // what the API returns
const AWAY_MS = 5 * 60000; // away at least this long: reload the deals on return

function Card({
  deal,
  fresh,
  hidden,
  onToggle,
}: {
  deal: Deal;
  fresh: boolean;
  hidden: boolean;
  onToggle: () => void;
}) {
  const link = safeLink(deal.url); // feed links are untrusted: https only
  const body = (
    <>
      <div class="deal-head">
        <div class="title wrap">
          {fresh && <span class="new">New</span>}
          {deal.title ?? "Deal"}
        </div>
        {typeof deal.price === "number" && (
          <div class="deal-price">{money(deal.price)}</div>
        )}
      </div>
      <div class="deal-meta muted small">
        {deal.keyword && <span class="tag">{deal.keyword}</span>}
        <span>
          {[
            deal.retailer,
            sourceName(deal.source),
            deal.publishedAt ? ago(deal.publishedAt) : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
    </>
  );
  return (
    <li class={hidden ? "dealrow faded" : "dealrow"}>
      {link ? (
        <a
          class="card block"
          href={link}
          target="_blank"
          rel="noopener noreferrer"
        >
          {body}
        </a>
      ) : (
        <div class="card block">{body}</div>
      )}
      <button
        type="button"
        class="x"
        aria-label={hidden ? "Show this deal again" : "Hide this deal"}
        onClick={onToggle}
      >
        {hidden ? "↩" : "✕"}
      </button>
    </li>
  );
}

export function Deals() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [picking, setPicking] = useState<Deal | null>(null); // "Exclude a word" is open for this deal
  const [excluding, setExcluding] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [source, setSource] = useState<Source | "all">("all");
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false); // the refresh button asked the backend to read the feeds, and it is still at it
  const mounted = useRef(true);
  const left = useRef(0); // when the app last went to the background
  const [hiddenIds, setHiddenIds] = useState<string[]>(loadHidden);
  const [showHidden, setShowHidden] = useState(false);
  const [undo, setUndo] = useState<string | null>(null);
  const [onlyNew, setOnlyNew] = useState(false);
  const [keyword, setKeyword] = useState("all");
  const [maxPrice, setMaxPrice] = useState("");
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const ids = useRef<string[]>([]);

  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  // The refresh button reads the feeds now, then loads what they found.
  const refresh = () => {
    setChecking(true);
    void checkNow(() => mounted.current).finally(() => {
      if (!mounted.current) return;
      setChecking(false);
      setAttempt((n) => n + 1);
    });
  };

  // Deals are marked seen when the person leaves, so "New" stays visible for the whole visit.
  useEffect(() => {
    const save = () => markSeen(ids.current);
    addEventListener("pagehide", save);
    return () => {
      removeEventListener("pagehide", save);
      save();
    };
  }, []);

  // Coming back after a while reloads the deals; a quick look away does not.
  useEffect(() => {
    const onChange = () => {
      if (document.visibilityState === "hidden") left.current = Date.now();
      else if (left.current && Date.now() - left.current >= AWAY_MS)
        setAttempt((n) => n + 1);
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .deals()
      .then(
        (found) => {
          if (!live) return;
          const foundIds = found.map((d) => d.id);
          if (ids.current.length === 0) setFresh(unseenIds(foundIds));
          else
            setFresh(
              (was) =>
                new Set([
                  ...was,
                  ...foundIds.filter((id) => !ids.current.includes(id)),
                ]),
            ); // arrived while the app was open
          ids.current = foundIds;
          setDeals(found);
          setError("");
        },
        (e: Error) => live && setError(e.message),
      )
      .finally(() => live && setLoading(false));
    // The keyword count is a nicety: if it fails the deals still show.
    api.rules().then(
      (found) => live && setRules(found),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  const change = (next: string[]) => (setHiddenIds(next), saveHidden(next));
  useEffect(() => {
    if (undo === null || picking) return; // the word picker keeps the bar open
    const t = setTimeout(() => setUndo(null), 6000);
    return () => clearTimeout(t);
  }, [undo, picking]);

  const keywords =
    rules === null ? null : rules.filter((r) => r.enabled).length;
  const undoDeal =
    undo === null ? undefined : (deals ?? []).find((d) => d.id === undo);
  const undoRule = undoDeal?.keyword
    ? (rules ?? []).find((r) => r.keyword === undoDeal.keyword)
    : undefined;
  const words =
    undoDeal && undoRule
      ? candidateWords(undoDeal.title ?? "", undoRule.keyword)
      : [];
  const exclude = async (rule: Rule, word: string) => {
    const keyword = withExclusion(rule.keyword, word);
    if (keyword === null) return setNote("That keyword would be too long.");
    setExcluding(true);
    try {
      const updated = await api.editRule(rule.id, { keyword });
      if (!mounted.current) return;
      setRules((current) =>
        (current ?? []).map((r) => (r.id === rule.id ? updated : r)),
      );
      setNote(`Skipping "${word}" for ${rule.keyword} from now on.`);
      setPicking(null);
      setUndo(null);
    } catch (e) {
      if (mounted.current) setNote((e as Error).message);
    } finally {
      if (mounted.current) setExcluding(false);
    }
  };
  const sources = [
    ...new Set((deals ?? []).flatMap((d) => (d.source ? [d.source] : []))),
  ]; // only feeds that have deals
  const keywordList = [
    ...new Set((deals ?? []).flatMap((d) => (d.keyword ? [d.keyword] : []))),
  ];
  const limit = maxPrice.trim() === "" ? null : Number(maxPrice);
  const priceLimit =
    limit !== null && Number.isFinite(limit) && limit >= 0 ? limit : null;
  const hiddenCount = (deals ?? []).filter((d) =>
    hiddenIds.includes(d.id),
  ).length;
  const shown = (deals ?? []).filter(
    (d) =>
      (showHidden || !hiddenIds.includes(d.id)) &&
      (source === "all" || d.source === source) &&
      (keyword === "all" || d.keyword === keyword) &&
      (!onlyNew || fresh.has(d.id)) &&
      (priceLimit === null ||
        (typeof d.price === "number" && d.price <= priceLimit)), // a deal with no price can't be under a limit
  );
  const filtered =
    source !== "all" || keyword !== "all" || onlyNew || priceLimit !== null;
  const markAllSeen = () => {
    markSeen(ids.current);
    setFresh(new Set());
    setOnlyNew(false);
  };
  return (
    <main class="screen">
      <header>
        <div class="top">
          <div>
            <h1>Deals</h1>
            <div class="muted">
              {keywords === null
                ? " "
                : `Matches for your ${keywords} active ${keywords === 1 ? "keyword" : "keywords"}`}
            </div>
            <CheckerLine reload={attempt} />
          </div>
          <button
            type="button"
            class={loading || checking ? "refresh spin" : "refresh"}
            aria-label="Check for new deals"
            disabled={loading || checking}
            onClick={refresh}
          >
            ↻
          </button>
        </div>
      </header>

      {error && (
        <div class="notice" role="alert">
          <span>{error}</span>
          <button
            class="button"
            type="button"
            onClick={() => setAttempt(attempt + 1)}
          >
            Retry
          </button>
        </div>
      )}

      {deals && fresh.size > 0 && (
        <div class="chips">
          <button
            type="button"
            class={onlyNew ? "chip on" : "chip"}
            aria-pressed={onlyNew}
            onClick={() => setOnlyNew(!onlyNew)}
          >
            New ({fresh.size})
          </button>
          <button type="button" class="textbutton" onClick={markAllSeen}>
            Mark all as seen
          </button>
        </div>
      )}

      {deals && sources.length > 1 && (
        <div class="chips">
          {(["all", ...sources] as const).map((id) => (
            <button
              key={id}
              type="button"
              class={source === id ? "chip on" : "chip"}
              aria-pressed={source === id}
              onClick={() => setSource(id)}
            >
              {id === "all" ? "All" : sourceName(id)}
            </button>
          ))}
        </div>
      )}

      {deals &&
        deals.length > 0 &&
        (keywordList.length > 1 ||
          deals.some((d) => typeof d.price === "number")) && (
          <div class="filters">
            {keywordList.length > 1 && (
              <select
                class="select"
                aria-label="Keyword"
                value={keyword}
                onChange={(e) => setKeyword(e.currentTarget.value)}
              >
                <option value="all">All keywords</option>
                {keywordList.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            )}
            <input
              class="select"
              type="number"
              inputMode="decimal"
              min="0"
              placeholder="Max price"
              aria-label="Max price"
              value={maxPrice}
              onInput={(e) => setMaxPrice(e.currentTarget.value)}
            />
          </div>
        )}

      {deals && deals.length === 0 && (
        <section class="empty">
          <p>No deals yet.</p>
          <p class="muted">Deals that match your keywords show up here.</p>
          <a class="button" href="#/keywords">
            Edit keywords
          </a>
        </section>
      )}
      {deals && deals.length > 0 && shown.length === 0 && (
        <p class="muted center">
          {filtered
            ? "No deals match these filters."
            : "Nothing in the latest deals."}{" "}
          {filtered && (
            <button
              type="button"
              class="textbutton"
              onClick={() => {
                setSource("all");
                setKeyword("all");
                setOnlyNew(false);
                setMaxPrice("");
              }}
            >
              Clear filters
            </button>
          )}
        </p>
      )}
      <ul class="list">
        {shown.map((d) => (
          <Card
            key={d.id}
            deal={d}
            fresh={fresh.has(d.id)}
            hidden={hiddenIds.includes(d.id)}
            onToggle={() => {
              if (hiddenIds.includes(d.id))
                return change(unhide(hiddenIds, d.id));
              change(hide(hiddenIds, d.id));
              setUndo(d.id);
            }}
          />
        ))}
      </ul>
      {hiddenCount > 0 && (
        <p class="center">
          <button
            type="button"
            class="textbutton"
            onClick={() => setShowHidden(!showHidden)}
          >
            {showHidden
              ? "Hide hidden deals"
              : `Show ${hiddenCount} hidden ${hiddenCount === 1 ? "deal" : "deals"}`}
          </button>
        </p>
      )}
      {note && !picking && undo === null && (
        <div class="undo" role="status">
          <span>{note}</span>
          <button type="button" class="textbutton" onClick={() => setNote("")}>
            OK
          </button>
        </div>
      )}
      {undo !== null && picking && undoRule && (
        <div
          class="undo picker"
          role="group"
          aria-label={`Skip a word for ${undoRule.keyword}`}
        >
          <span class="small">
            Skip deals for {undoRule.keyword} that mention:
          </span>
          <div class="chips">
            {words.map((w) => (
              <button
                key={w}
                type="button"
                class="chip"
                disabled={excluding}
                onClick={() => void exclude(undoRule, w)}
              >
                {w}
              </button>
            ))}
          </div>
          {note && (
            <span class="small" role="alert">
              {note}
            </span>
          )}
          <button
            type="button"
            class="textbutton"
            onClick={() => (setPicking(null), setNote(""), setUndo(null))}
          >
            Cancel
          </button>
        </div>
      )}
      {undo !== null && !picking && (
        <div class="undo" role="status">
          <span>Deal hidden</span>
          {undoRule && words.length > 0 && (
            <button
              type="button"
              class="textbutton"
              onClick={() => {
                setNote("");
                setPicking(undoDeal ?? null);
              }}
            >
              Skip a word…
            </button>
          )}
          <button
            type="button"
            class="textbutton"
            onClick={() => {
              change(unhide(hiddenIds, undo));
              setUndo(null);
            }}
          >
            Undo
          </button>
        </div>
      )}
      {deals && deals.length >= MAX_DEALS && (
        <p class="muted small center">Showing the latest {MAX_DEALS} deals.</p>
      )}
    </main>
  );
}
