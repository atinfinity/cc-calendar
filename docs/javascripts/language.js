// The language switcher keeps you on the same page. The theme only does this for
// sibling sites, but the Japanese site is nested under the English one (/ja/), and
// every page exists in both (tests/test_docs.py checks this).
document.addEventListener(
  "click",
  (event) => {
    const link = event.target.closest?.("a[hreflang]");
    if (!link || event.metaKey || event.ctrlKey) return;
    const bases = [...document.querySelectorAll("a[hreflang]")]
      .map((a) => new URL(a.href).pathname)
      .sort((a, b) => b.length - a.length); // the nested /ja/ first
    const here = location.pathname;
    const base = bases.find((b) => here.startsWith(b));
    if (base === undefined) return;
    event.preventDefault();
    event.stopPropagation();
    location.assign(new URL(link.href).pathname + here.slice(base.length) + location.hash);
  },
  true,
);
