// Android can stop an installed app in the background, and the next launch
// opens the manifest's start_url. The start_url carries ?launch, so a launch
// can send the reader back to the page and scroll position they left.
(() => {
  if (!matchMedia("(display-mode: standalone)").matches) return

  const KEY = "protean-app-last-page"

  if (new URLSearchParams(location.search).has("launch")) {
    let saved = null
    try {
      saved = JSON.parse(localStorage.getItem(KEY))
    } catch {}
    if (saved?.url && new URL(saved.url).origin === location.origin) {
      try {
        sessionStorage.setItem(KEY, String(saved.y))
      } catch {}
      location.replace(saved.url)
      return
    }
    history.replaceState(null, "", location.pathname + location.hash)
  }

  let y = null
  try {
    y = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
  } catch {}
  if (y !== null) addEventListener("load", () => scrollTo(0, Number(y)))

  // Hidden is the last state an app is sure to reach before Android stops it.
  addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "hidden") return
    try {
      localStorage.setItem(KEY, JSON.stringify({ url: location.href, y: scrollY }))
    } catch {}
  })
})()
