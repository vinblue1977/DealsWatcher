const MAX_KEYWORD = 60; // the API's limit on a keyword
const MAX_WORDS = 8;
const SKIP = new Set(['the', 'and', 'for', 'with', 'from', 'off', 'new', 'free', 'sale', 'deal', 'deals', 'save', 'all', 'your', 'you', 'more', 'this', 'that', 'now', 'only']);

/** The matcher lets a plural "s" or "es" through, so "headphones" is the keyword "headphone" and skipping it would cancel the keyword. */
const sameWord = (word: string, keywordWords: Set<string>): boolean => [...keywordWords].some((k) => word === `${k}s` || word === `${k}es` || k === `${word}s` || k === `${word}es`);

/** Words from a deal title the person could exclude: letters first (a `-` only excludes before a letter), not already in the keyword, no filler, each once, in title order. */
export function candidateWords(title: string, keyword: string): string[] {
  const inKeyword = new Set((keyword.match(/[a-z][a-z0-9]*/gi) ?? []).map((w) => w.toLowerCase()));
  const out: string[] = [];
  for (const match of title.match(/(?<![a-z0-9])[a-z][a-z0-9]{2,}(?![a-z0-9])/gi) ?? []) {
    const word = match.toLowerCase();
    if (inKeyword.has(word) || sameWord(word, inKeyword) || SKIP.has(word) || out.includes(word)) continue;
    out.push(word);
  }
  return out.slice(0, MAX_WORDS);
}

/** The keyword with `-word` added, or null when it would be longer than the API allows. */
export function withExclusion(keyword: string, word: string): string | null {
  const next = `${keyword.trim()} -${word}`;
  return next.length <= MAX_KEYWORD ? next : null;
}
