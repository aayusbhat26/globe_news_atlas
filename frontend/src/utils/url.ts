/**
 * Resolves a news article link so it directly opens the specific story/post,
 * preventing users from landing on a generic homepage (e.g. reuters.com).
 */
export function resolveArticleUrl(url?: string, outlet?: string, title?: string): string {
  const cleanUrl = (url || '').trim();

  // Check if URL is just a naked root domain (e.g. https://reuters.com, https://bbc.com/, etc.)
  const isBareDomain = !cleanUrl || cleanUrl.match(/^https?:\/\/(www\.)?[\w-]+\.[a-z]{2,}(\/)?$/i);

  // If already a valid specific article URL with a path/query, keep it
  if (cleanUrl && !isBareDomain) {
    return cleanUrl;
  }

  const query = encodeURIComponent((title || '').trim());
  const outletLower = (outlet || '').toLowerCase();

  if (query) {
    if (outletLower.includes('reuters')) {
      return `https://www.reuters.com/site-search/?query=${query}`;
    }
    if (outletLower.includes('guardian')) {
      return `https://www.theguardian.com/search?q=${query}`;
    }
    if (outletLower.includes('bbc')) {
      return `https://www.bbc.co.uk/search?q=${query}`;
    }
    if (outletLower.includes('ap') || outletLower.includes('associated press')) {
      return `https://apnews.com/search?q=${query}`;
    }
    if (outletLower.includes('wsj') || outletLower.includes('wall street')) {
      return `https://www.wsj.com/search?query=${query}`;
    }
    if (outletLower.includes('fox')) {
      return `https://www.foxnews.com/search-results/search?q=${query}`;
    }
    if (outletLower.includes('país') || outletLower.includes('pais')) {
      return `https://elpais.com/buscador/?q=${query}`;
    }
    if (outletLower.includes('bloomberg')) {
      return `https://www.bloomberg.com/search?query=${query}`;
    }
    if (outletLower.includes('al jazeera')) {
      return `https://www.aljazeera.com/search/${query}`;
    }

    // High accuracy Google News deep lookup
    const searchTarget = encodeURIComponent(`${outlet ? outlet + ' ' : ''}${title || ''}`);
    return `https://news.google.com/search?q=${searchTarget}`;
  }

  return cleanUrl || '#';
}
