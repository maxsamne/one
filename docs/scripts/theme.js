(function () {
  const themeDock = document.getElementById('theme-dock');
  const themeToggle = document.getElementById('theme-toggle');
  if (!themeDock || !themeToggle) return;

  const themeToggleIcon = themeToggle.querySelector('.theme-toggle__icon');
  const THEME_KEY = 'one-theme';
  const THEME_POSITION_KEY = 'one-theme-toggle-position';
  const THEME_GRID_SIZE = 24;
  const THEME_DRAG_THRESHOLD = 10;

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const isDark = theme === 'dark';
    themeToggle.setAttribute('aria-pressed', String(isDark));
    themeToggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    themeToggle.setAttribute('title', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    if (themeToggleIcon) themeToggleIcon.textContent = isDark ? '◑' : '◐';
  }

  let savedTheme = null;
  try { savedTheme = localStorage.getItem(THEME_KEY); } catch (e) {}
  const initialTheme = savedTheme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(initialTheme);

  function setThemeDockPosition(x, y) {
    const rect = themeDock.getBoundingClientRect();
    const maxX = Math.max(0, document.documentElement.clientWidth - rect.width);
    const maxY = Math.max(0, document.documentElement.clientHeight - rect.height);
    const nextX = Math.min(Math.max(0, x), maxX);
    const nextY = Math.min(Math.max(0, y), maxY);
    themeDock.style.setProperty('--theme-toggle-x', `${nextX}px`);
    themeDock.style.setProperty('--theme-toggle-y', `${nextY}px`);
    return { x: nextX, y: nextY };
  }

  function snapThemeDockPosition(x, y) {
    const gridOriginX = (document.documentElement.clientWidth - THEME_GRID_SIZE) / 2;
    const snappedX = gridOriginX + Math.round((x - gridOriginX) / THEME_GRID_SIZE) * THEME_GRID_SIZE;
    const snappedY = Math.round(y / THEME_GRID_SIZE) * THEME_GRID_SIZE;
    return setThemeDockPosition(snappedX, snappedY);
  }

  function restoreThemeDockPosition() {
    try {
      const saved = JSON.parse(localStorage.getItem(THEME_POSITION_KEY) || 'null');
      if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
        snapThemeDockPosition(saved.x, saved.y);
        return;
      }
    } catch (e) {}
    snapThemeDockPosition(document.documentElement.clientWidth - 48, 24);
  }

  restoreThemeDockPosition();

  let dragState = null;
  let ignoreNextThemeClick = false;

  function toggleTheme() {
    const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, nextTheme); } catch (e) {}
    applyTheme(nextTheme);
  }

  function startThemeDockDrag(event, pointerId = event.pointerId) {
    if (dragState) return;
    const rect = themeDock.getBoundingClientRect();
    dragState = {
      pointerId,
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
      moved: false,
    };
    if (event.pointerId !== undefined && themeDock.setPointerCapture) {
      try { themeDock.setPointerCapture(event.pointerId); } catch (e) {}
    }
    themeDock.classList.add('is-dragging');
  }

  function moveThemeDock(event, pointerId = event.pointerId) {
    if (!dragState || dragState.pointerId !== pointerId) return;
    const dx = event.clientX - dragState.startX;
    const dy = event.clientY - dragState.startY;
    if (Math.hypot(dx, dy) > THEME_DRAG_THRESHOLD) dragState.moved = true;
    if (dragState.moved) setThemeDockPosition(dragState.left + dx, dragState.top + dy);
  }

  function finishThemeDockDrag(event, pointerId = event.pointerId) {
    if (!dragState || dragState.pointerId !== pointerId) return;
    const wasMoved = dragState.moved;
    const nextX = dragState.left + event.clientX - dragState.startX;
    const nextY = dragState.top + event.clientY - dragState.startY;
    let finalPosition = null;
    if (wasMoved) finalPosition = snapThemeDockPosition(nextX, nextY);
    else setThemeDockPosition(dragState.left, dragState.top);
    themeDock.classList.remove('is-dragging');
    dragState = null;
    ignoreNextThemeClick = true;
    window.setTimeout(() => { ignoreNextThemeClick = false; }, 0);
    if (wasMoved) {
      try { localStorage.setItem(THEME_POSITION_KEY, JSON.stringify(finalPosition)); } catch (e) {}
    } else {
      toggleTheme();
    }
  }

  function cancelThemeDockDrag() {
    themeDock.classList.remove('is-dragging');
    dragState = null;
  }

  themeDock.addEventListener('pointerdown', startThemeDockDrag);
  themeDock.addEventListener('pointermove', moveThemeDock);
  themeDock.addEventListener('pointerup', finishThemeDockDrag);
  themeDock.addEventListener('pointercancel', cancelThemeDockDrag);
  themeDock.addEventListener('mousedown', (event) => startThemeDockDrag(event, 'mouse'));
  window.addEventListener('mousemove', (event) => moveThemeDock(event, dragState ? dragState.pointerId : 'mouse'));
  window.addEventListener('mouseup', (event) => finishThemeDockDrag(event, dragState ? dragState.pointerId : 'mouse'));
  window.addEventListener('resize', () => {
    const rect = themeDock.getBoundingClientRect();
    const finalPosition = snapThemeDockPosition(rect.left, rect.top);
    try { localStorage.setItem(THEME_POSITION_KEY, JSON.stringify(finalPosition)); } catch (e) {}
  });

  themeToggle.addEventListener('click', (event) => {
    if (ignoreNextThemeClick) {
      event.preventDefault();
      return;
    }
    toggleTheme();
  });
})();
