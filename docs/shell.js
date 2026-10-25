// Open MCT shell adjustments for readers of the dashboard (issue #7): narrower browse pane, inspector collapsed
// by default, and a content-only "viewer" mode (?viewer=1, or the button at the top right). Everything stays reachable.
(function () {
  const VIEWER_PARAM = /[?&]viewer=1\b/;
  const root = document.documentElement;
  const btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'sh-viewer-btn';
  function setViewer(on) {
    root.classList.toggle('sh-viewer', on);
    btn.textContent = on ? '通常表示' : '全画面表示';
    btn.title = on ? 'ツリーと操作パネルを戻す' : 'ツリーと操作パネルを隠して、内容だけを表示する';
    try {
      const u = new URL(location.href);
      if (on) u.searchParams.set('viewer', '1'); else u.searchParams.delete('viewer');
      history.replaceState(null, '', u);
    } catch (e) { /* the page still works without the URL flag */ }
    window.dispatchEvent(new Event('resize'));  // maps resize to the new content area
  }
  btn.addEventListener('click', () => setViewer(!root.classList.contains('sh-viewer')));
  document.addEventListener('DOMContentLoaded', () => { document.body.appendChild(btn); setViewer(VIEWER_PARAM.test(location.search)); });

  // Once the shell exists: tree 200 px (a later drag by the reader overrides the inline width), inspector collapsed.
  const done = { tree: false, inspector: false };
  const mo = new MutationObserver(() => {
    const tree = document.querySelector('.l-shell__pane-tree');
    if (tree && !done.tree) { done.tree = true; tree.style.width = '200px'; }
    const collapse = document.querySelector('.l-shell__pane-inspector .l-pane__collapse-button');
    if (collapse && !done.inspector) {
      done.inspector = true;
      // Open MCT's collapse writes a URL parameter through its router, which is not ready the moment the pane appears
      setTimeout(() => {
        const pane = document.querySelector('.l-shell__pane-inspector');
        try { if (pane && !pane.classList.contains('l-pane--collapsed')) collapse.click(); } catch (e) { /* stays open; harmless */ }
      }, 800);
    }
    if (done.tree && done.inspector) mo.disconnect();
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });
})();
